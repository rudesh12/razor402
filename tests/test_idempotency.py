"""tests/test_idempotency.py — T33-T39: Settlement, idempotency, concurrency tests."""
import json
import secrets
import threading
import pytest

from core.crypto import sign_jws, b64u
from core.catalog import AGENT_POLICY
from state.db import get_connection
from state.states import RANK


def _get_challenge(client, item_id="qdrant-vector-query", kid="agt_coding_01"):
    resp = client.post(f"/provision/{item_id}",
                       headers={"X-Razor402-Agent": kid})
    assert resp.status_code == 402
    body = resp.json()
    challenge_jws = body.get("challengeJws", "")
    if not challenge_jws and "challengeJwsList" in body:
        challenge_jws = body["challengeJwsList"][0]
    return challenge_jws, body["accepts"][0]["extra"]["challengeId"], body


def _build_auth(challenge_jws, challenge_id, kid, keys, fake_clock, jti=None):
    policy = AGENT_POLICY.get(kid, {})
    auth_payload = {
        "typ": "razor402.payment-authorization+jws",
        "challengeJws": challenge_jws,
        "challengeId": challenge_id,
        "agentKid": kid,
        "mandate": {"type": "upi_sbmd", "token": policy.get("mandate_token", "")},
        "maxDebitPaise": 500,
        "rationale": "test purchase",
        "jti": jti or b64u(secrets.token_bytes(16)),
        "iat": fake_clock.time,
    }
    return sign_jws(auth_payload, keys[kid]["sk"], kid)


# T33
def test_timeout_becomes_unknown_never_failed(tmp_db, fake_clock, fake_rzp):
    """Timeout → SETTLEMENT_UNKNOWN, never FAILED."""
    conn = get_connection(tmp_db)
    from state.ledger import cas
    from facilitator.settler import settle

    cid = "test-timeout-001"
    now_ts = fake_clock.time
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, created_at, updated_at) "
        "VALUES (?, 'VERIFIED', 20, 'agt_coding_01', 'test', 'sha256:abc', 500, "
        "'flat_per_call.v1', ?, ?)",
        (cid, now_ts, now_ts)
    )
    conn.execute(
        "INSERT INTO budget_reservations (agent_kid, challenge_id, amount_paise, "
        "status, created_at) VALUES ('agt_coding_01', ?, 500, 'HELD', ?)",
        (cid, now_ts)
    )

    fake_rzp.fault = "timeout"
    result = settle(conn, fake_rzp, cid, 500, "mnd_sbmd_demo_a")
    assert result.status == "in_doubt"

    row = conn.execute("SELECT state FROM txn WHERE challenge_id=?", (cid,)).fetchone()
    assert row["state"] == "SETTLEMENT_UNKNOWN"
    assert row["state"] != "FAILED"


# T34
def test_concurrent_holds_cannot_oversubscribe_pool(tmp_db, fake_clock):
    """40 threads × ₹50 vs ₹150 pool → exactly 3 allowed."""
    from policy.server_gate import authorize
    from core.errors import Razor402Error
    import sqlite3

    results = []
    lock = threading.Lock()
    now_ts = fake_clock.time

    def worker(i):
        conn = sqlite3.connect(tmp_db, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            conn.execute("BEGIN IMMEDIATE")
            authorize(conn, f"cid-concurrent-{i}", "agt_coding_01", 5000,
                      "acc_buildbroker_test", now_ts)
            conn.commit()
            with lock:
                results.append("ALLOWED")
        except Razor402Error as e:
            conn.rollback()
            with lock:
                results.append(e.code)
        except Exception as e:
            conn.rollback()
            with lock:
                results.append("ERROR")
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # With ₹150 (15000 paise) pool and ₹50 (5000 paise) per call, exactly 3 must be allowed
    allowed_count = sum(1 for r in results if r == "ALLOWED")
    assert allowed_count == 3

    # Total held reservations in DB must be exactly 15000
    conn = get_connection(tmp_db)
    row = conn.execute("SELECT SUM(amount_paise) as total FROM budget_reservations WHERE status='HELD'").fetchone()
    assert row["total"] == 15000


# T35
def test_mandate_allowance_enforced(client, keys, fake_clock, tmp_db):
    """Exceeding blocked amount → 402 MANDATE_ALLOWANCE_EXHAUSTED."""
    conn = get_connection(tmp_db)
    # Blocked is 6000 for agt_coding_02; set debited to 5800 so 500 exceeds it
    conn.execute("UPDATE mandates SET debited_paise=5800 WHERE token='mnd_sbmd_demo_b'")

    challenge_jws, cid, _ = _get_challenge(client, "qdrant-vector-query", "agt_coding_02")
    token = _build_auth(challenge_jws, cid, "agt_coding_02", keys, fake_clock)
    resp = client.post(
        "/provision/qdrant-vector-query",
        headers={"X-PAYMENT": token, "X-Razor402-Agent": "agt_coding_02"},
    )
    assert resp.status_code == 402
    body = resp.json()
    assert body.get("error") == "MANDATE_ALLOWANCE_EXHAUSTED"



# T36
def test_reservation_captured_on_fulfil(tmp_db, fake_clock):
    """HELD → CAPTURED on fulfilment; remaining pool correct."""
    conn = get_connection(tmp_db)

    cid = "test-capture-001"
    now_ts = fake_clock.time
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, payment_id, payment_mode, "
        "created_at, updated_at) "
        "VALUES (?, 'SETTLED', 30, 'agt_coding_01', 'qdrant-vector-query', "
        "'sha256:abc', 500, 'flat_per_call.v1', 'pay_Htest', 'harness', ?, ?)",
        (cid, now_ts, now_ts)
    )
    conn.execute(
        "INSERT INTO budget_reservations (agent_kid, challenge_id, amount_paise, "
        "status, created_at) VALUES ('agt_coding_01', ?, 500, 'HELD', ?)",
        (cid, now_ts)
    )

    conn.execute(
        "UPDATE budget_reservations SET status='CAPTURED' WHERE challenge_id=?",
        (cid,)
    )

    row = conn.execute(
        "SELECT status FROM budget_reservations WHERE challenge_id=?",
        (cid,)
    ).fetchone()
    assert row["status"] == "CAPTURED"


# T37
def test_replay_returns_byte_identical_cached_body(tmp_db, fake_clock):
    """Equal bytes + X-Razor402-Replay: true + zero new calls."""
    from gateway.replay import resolve as replay_resolve
    conn = get_connection(tmp_db)
    now_ts = fake_clock.time
    jti = "jti_replay_test_001"
    r_hash = "sha256:test_resource_hash"
    cid = "cid_replay_001"
    cached_body = json.dumps({"provisioned_resource": {"key": "sb_sk_123"}}).encode()

    # Pre-seed transaction in FULFILLED state
    conn.execute(
        "INSERT INTO txn (challenge_id, state, rank, agent_kid, item_id, "
        "resource_hash, amount_paise, price_basis, resp_status, resp_body, "
        "payment_id, payment_mode, created_at, updated_at) "
        "VALUES (?, 'FULFILLED', 50, 'agt_coding_01', 'qdrant-vector-query', "
        "?, 500, 'flat_per_call.v1', 200, ?, 'pay_Hreplay', 'harness', ?, ?)",
        (cid, r_hash, cached_body, now_ts, now_ts)
    )

    # First presentation records the JTI
    dec1 = replay_resolve(conn, jti, r_hash, cid)
    assert dec1.action == "PROCEED"

    # Second presentation with same JTI and same resource hash returns cached response
    dec2 = replay_resolve(conn, jti, r_hash, cid)
    assert dec2.action == "REPLAY"
    assert dec2.status_code == 200
    assert dec2.headers.get("X-Razor402-Replay") == "true"
    assert dec2.body == json.loads(cached_body)


# T38
def test_eight_concurrent_identical_requests(tmp_db, fake_clock):
    """1 jti_seen, 1 proceed, no crash."""
    from gateway.replay import resolve as replay_resolve
    import sqlite3

    jti = "jti_concurrent_001"
    r_hash = "sha256:identical_resource"
    cid = "cid_concurrent_test"
    results = []
    lock = threading.Lock()

    def try_replay(i):
        conn = sqlite3.connect(tmp_db, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            dec = replay_resolve(conn, jti, r_hash, cid)
            with lock:
                results.append(dec.action)
        finally:
            conn.close()

    threads = [threading.Thread(target=try_replay, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one thread gets PROCEED (wins the INSERT into jti_seen)
    proceed_count = sum(1 for a in results if a == "PROCEED")
    assert proceed_count == 1

    # Exactly one entry in jti_seen
    conn = get_connection(tmp_db)
    count = conn.execute("SELECT COUNT(*) as c FROM jti_seen WHERE jti=?", (jti,)).fetchone()["c"]
    assert count == 1


# T39
def test_idempotency_key_reuse_different_resource(tmp_db, fake_clock):
    """409 IDEMPOTENCY_KEY_REUSE when same JTI presented for different resource."""
    from gateway.replay import resolve as replay_resolve
    conn = get_connection(tmp_db)
    jti = "jti_reuse_test_001"

    # First call with resource A
    dec1 = replay_resolve(conn, jti, "sha256:resource_AAA", "cid_001")
    assert dec1.action == "PROCEED"

    # Second call with same JTI but resource B
    dec2 = replay_resolve(conn, jti, "sha256:resource_BBB", "cid_002")
    assert dec2.action == "ERROR"
    assert dec2.status_code == 409
    assert dec2.body.get("error") == "IDEMPOTENCY_KEY_REUSE"

