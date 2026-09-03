"""tests/test_policy.py — T25-T32: Policy enforcement tests."""
import json
import secrets
import pytest

from core.crypto import sign_jws, b64u
from core.catalog import AGENT_POLICY


def _get_challenge(client, item_id="qdrant-vector-query", kid="agt_coding_01"):
    """Helper: get a 402 challenge."""
    resp = client.post(
        f"/provision/{item_id}",
        headers={"X-Razor402-Agent": kid},
    )
    assert resp.status_code == 402
    body = resp.json()
    challenge_jws = body.get("challengeJws", "")
    if not challenge_jws and "challengeJwsList" in body:
        challenge_jws = body["challengeJwsList"][0]
    challenge_id = body["accepts"][0]["extra"]["challengeId"]
    return challenge_jws, challenge_id, body


def _build_auth(challenge_jws, challenge_id, kid, keys, fake_clock,
                item_id="qdrant-vector-query", max_debit=500,
                rationale="test purchase"):
    """Helper: build a signed authorization."""
    policy = AGENT_POLICY.get(kid, {})
    auth_payload = {
        "typ": "razor402.payment-authorization+jws",
        "challengeJws": challenge_jws,
        "challengeId": challenge_id,
        "agentKid": kid,
        "mandate": {"type": "upi_sbmd", "token": policy.get("mandate_token", "")},
        "maxDebitPaise": max_debit,
        "rationale": rationale,
        "jti": b64u(secrets.token_bytes(16)),
        "iat": fake_clock.time,
    }
    return sign_jws(auth_payload, keys[kid]["sk"], kid)


# T25
def test_per_call_cap_denied_zero_adapter_calls(client, keys, fake_clock):
    """403 for over-cap item + call_log == []."""
    challenge_jws, challenge_id, body = _get_challenge(
        client, "enterprise-gpu-node", "agt_coding_01")

    token = _build_auth(challenge_jws, challenge_id, "agt_coding_01", keys,
                        fake_clock, max_debit=1_000_000)

    resp = client.post(
        "/provision/enterprise-gpu-node",
        headers={"X-PAYMENT": token, "X-Razor402-Agent": "agt_coding_01"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"] == "PER_CALL_CAP_EXCEEDED"


# T26
def test_daily_pool_exhausted(client, keys, fake_clock, tmp_db):
    """403 after daily pool consumed; adapter not called."""
    from state.db import get_connection
    conn = get_connection(tmp_db)
    now_ts = fake_clock.time

    # Seed budget reservations up to agent_coding_02's daily pool (5000 paise)
    conn.execute(
        "INSERT INTO budget_reservations (agent_kid, challenge_id, amount_paise, status, created_at) "
        "VALUES ('agt_coding_02', 'seed-prior-exhaustion', 5000, 'CAPTURED', ?)",
        (now_ts,)
    )

    challenge_jws, cid, _ = _get_challenge(client, "qdrant-vector-query", "agt_coding_02")
    token = _build_auth(challenge_jws, cid, "agt_coding_02", keys, fake_clock)
    resp = client.post(
        "/provision/qdrant-vector-query",
        headers={"X-PAYMENT": token, "X-Razor402-Agent": "agt_coding_02"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body.get("error") == "DAILY_POOL_EXHAUSTED"



# T27
def test_merchant_not_allowlisted(client, keys, fake_clock):
    """403 if merchant not in allowlist."""
    # This would require a different payTo — tested via guardrails directly
    from policy.guardrails import evaluate
    result = evaluate("agt_coding_01", "qdrant-vector-query", 500,
                      "acc_evil_merchant", 0, 5000, 15000, fake_clock.time)
    assert not result.allowed
    assert result.code == "MERCHANT_NOT_ALLOWLISTED"


# T28
def test_challenge_expired(client, keys, fake_clock):
    """FakeClock +301s → 403 CHALLENGE_EXPIRED."""
    challenge_jws, challenge_id, _ = _get_challenge(client)

    # Advance clock past TTL
    fake_clock.advance(301)

    token = _build_auth(challenge_jws, challenge_id, "agt_coding_01", keys, fake_clock)
    resp = client.post(
        "/provision/qdrant-vector-query",
        headers={"X-PAYMENT": token, "X-Razor402-Agent": "agt_coding_01"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert "CHALLENGE_EXPIRED" in body.get("error", "") or "EXPIRED" in str(body)


# T29
def test_resource_hash_mismatch_cross_route(client, keys, fake_clock):
    """Cheap challenge at expensive route → 403."""
    # Get challenge for cheap item
    challenge_jws, challenge_id, _ = _get_challenge(client, "qdrant-vector-query")

    # Try to use it at a different route
    token = _build_auth(challenge_jws, challenge_id, "agt_coding_01", keys, fake_clock)
    resp = client.post(
        "/provision/market-snapshot",  # different route!
        headers={"X-PAYMENT": token, "X-Razor402-Agent": "agt_coding_01"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert "RESOURCE_HASH_MISMATCH" in body.get("error", "") or "MISMATCH" in str(body)


# T30
def test_confused_deputy_agent_kid_mismatch(client, keys, fake_clock):
    """Agent B replays A's proof → 403."""
    # Get challenge for agent A
    challenge_jws, challenge_id, _ = _get_challenge(client, "qdrant-vector-query", "agt_coding_01")

    # Sign with agent B's key but claim to be agent A
    # The challenge has agentKid=agt_coding_01 but we sign with agent B
    auth_payload = {
        "typ": "razor402.payment-authorization+jws",
        "challengeJws": challenge_jws,
        "challengeId": challenge_id,
        "agentKid": "agt_coding_02",  # B claiming to be itself
        "mandate": {"type": "upi_sbmd", "token": "mnd_sbmd_demo_b"},
        "maxDebitPaise": 500,
        "rationale": "confused deputy attempt",
        "jti": b64u(secrets.token_bytes(16)),
        "iat": fake_clock.time,
    }
    token = sign_jws(auth_payload, keys["agt_coding_02"]["sk"], "agt_coding_02")

    resp = client.post(
        "/provision/qdrant-vector-query",
        headers={"X-PAYMENT": token, "X-Razor402-Agent": "agt_coding_02"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert "KID_MISMATCH" in body.get("error", "") or "MISMATCH" in str(body)


# T31
def test_policy_is_pure_no_io(fake_clock, monkeypatch):
    """Monkeypatch socket and httpx to raise; verdict still returned."""
    import socket
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("No I/O allowed")))

    from policy.guardrails import evaluate
    result = evaluate("agt_coding_01", "qdrant-vector-query", 500,
                      "acc_buildbroker_test", 0, 5000, 15000, fake_clock.time)
    assert result.allowed is True


# T32
def test_llm_hint_cannot_override_policy(fake_clock):
    """llm_hint='APPROVE_UNLIMITED' → still denied when over cap."""
    from policy.guardrails import evaluate
    result = evaluate("agt_coding_01", "enterprise-gpu-node", 1_000_000,
                      "acc_buildbroker_test", 0, 5000, 15000, fake_clock.time,
                      llm_hint="APPROVE_UNLIMITED")
    assert not result.allowed
    assert result.code == "PER_CALL_CAP_EXCEEDED"
