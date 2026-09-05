"""tests/test_demo_api.py — Verification of demo endpoints: agent/buy, attacks, audit verify, txn detail, sweep, stats."""
import pytest
from core.catalog import CATALOG


def test_agent_buy_success(client):
    """POST /api/v1/agent/buy runs full 402 challenge negotiation and captures wire frames."""
    resp = client.post("/api/v1/agent/buy", json={"item_id": "deepseek-v4-flash", "agent": "agt_coding_01"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["final_state"] == "FULFILLED"
    assert data["challenge_id"]
    assert len(data["frames"]) >= 4

    # Frame 1: Unpaid request
    assert data["frames"][0]["dir"] == "req"
    assert data["frames"][0]["path"] == "/provision/deepseek-v4-flash"

    # Frame 2: 402 challenge
    assert data["frames"][1]["dir"] == "res"
    assert data["frames"][1]["status"] == 402

    # Frame 3: Paid request with X-PAYMENT
    assert data["frames"][2]["dir"] == "req"
    assert "X-PAYMENT" in data["frames"][2]["headers"]

    # Frame 4: 200 OK delivery
    assert data["frames"][3]["dir"] == "res"
    assert data["frames"][3]["status"] == 200

def test_agent_buy_paid_but_undelivered_triggers_compensation(client):
    """When failure injection is rzp_refund_timeout, settlement succeeds but fulfilment triggers compensation auto-refund."""
    client.post("/chaos", json={"mode": "rzp_refund_timeout"})
    try:
        resp = client.post("/api/v1/agent/buy", json={"item_id": "deepseek-v4-flash", "agent": "agt_coding_01"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["final_state"] == "COMPENSATED"
        assert len(data["frames"]) == 4

        # Frame 4 should be 502 Bad Gateway with COMPENSATED state header
        f4 = data["frames"][3]
        assert f4["status"] == 502
        assert f4["headers"]["x-razor402-state"] == "COMPENSATED"
        assert "x-payment-response" in f4["headers"]
        assert f4["body"]["error"] == "UPSTREAM_FULFILMENT_FAILED"
        assert f4["body"]["settlement"]["status"] == "refunded"
        assert f4["body"]["settlement"]["refundId"].startswith("rfnd_")
    finally:
        client.post("/chaos", json={"mode": "ok"})


def test_agent_buy_validations(client):
    """POST /api/v1/agent/buy validates unknown items and agents."""
    r1 = client.post("/api/v1/agent/buy", json={"item_id": "nonexistent-item"})
    assert r1.status_code == 404

    r2 = client.post("/api/v1/agent/buy", json={"item_id": "deepseek-v4-flash", "agent": "unknown_agent"})
    assert r2.status_code == 404


def test_demo_attack_prompt_injection(client):
    """POST /api/v1/demo/attack: prompt_injection attempts honeypot and is rejected by server gate."""
    resp = client.post("/api/v1/demo/attack", json={"kind": "prompt_injection"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "prompt_injection"
    assert data["defended"] is True
    assert data["http_status"] == 403
    assert data["error_code"] == "PER_CALL_CAP_EXCEEDED"
    assert len(data["frames"]) >= 4


def test_demo_attack_confused_deputy(client):
    """POST /api/v1/demo/attack: confused_deputy signs with mismatched kid and is rejected."""
    resp = client.post("/api/v1/demo/attack", json={"kind": "confused_deputy"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "confused_deputy"
    assert data["defended"] is True
    assert data["http_status"] == 403
    assert data["error_code"] == "AGENT_KID_MISMATCH"


def test_demo_attack_replay(client):
    """POST /api/v1/demo/attack: replay sends identical token and returns cached response with no double debit."""
    resp = client.post("/api/v1/demo/attack", json={"kind": "replay"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "replay"
    assert data["defended"] is True
    assert data["http_status"] == 200


def test_demo_attack_pool_drain(client):
    """POST /api/v1/demo/attack: pool_drain exceeds daily pool and is rejected by authoritative gate."""
    resp = client.post("/api/v1/demo/attack", json={"kind": "pool_drain"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "pool_drain"
    assert data["defended"] is True
    assert data["http_status"] == 403
    assert data["error_code"] in ("DAILY_POOL_EXHAUSTED", "DAILY_POOL_EXCEEDED")


def test_demo_attack_revoked_envelope(client):
    """POST /api/v1/demo/attack: revoked_envelope rejects transaction when operator killswitch is active."""
    resp = client.post("/api/v1/demo/attack", json={"kind": "revoked_envelope"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["kind"] == "revoked_envelope"
    assert data["defended"] is True
    assert data["http_status"] == 403
    assert data["error_code"] == "ENVELOPE_REVOKED"


def test_audit_verify_intact_and_tampered(client):
    """GET /api/v1/audit?verify=1 performs per-entry SHA-256 validation and identifies tampered seq."""
    # Run a purchase first to have audit entries
    client.post("/api/v1/agent/buy", json={"item_id": "deepseek-v4-flash"})

    # Check intact chain
    r1 = client.get("/api/v1/audit?verify=1")
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["chain_valid"] is True
    assert d1["first_bad_seq"] is None
    assert d1["verified_count"] > 0
    assert "chain_height" in d1
    assert all(e.get("hash_ok") is True for e in d1["entries"])

    # Tamper with an entry
    r_tamper = client.post("/api/v1/demo/tamper")
    assert r_tamper.status_code == 200

    # Re-verify: must catch broken link
    r2 = client.get("/api/v1/audit?verify=1")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["chain_valid"] is False
    assert d2["first_bad_seq"] is not None


def test_txn_detail_and_timeline(client):
    """GET /api/v1/txns/{id} returns state machine drill-down with timeline."""
    buy_resp = client.post("/api/v1/agent/buy", json={"item_id": "deepseek-v4-flash"})
    cid = buy_resp.json()["challenge_id"]

    resp = client.get(f"/api/v1/txns/{cid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["challenge_id"] == cid
    assert data["item_id"] == "deepseek-v4-flash"
    assert data["state"] == "FULFILLED"
    assert isinstance(data["timeline"], list)
    assert len(data["timeline"]) > 0

    # 404 for unknown challenge
    r_unknown = client.get("/api/v1/txns/cid_nonexistent_999")
    assert r_unknown.status_code == 404


def test_demo_sweep(client):
    """POST /api/v1/demo/sweep runs synchrononous sweeper tick."""
    resp = client.post("/api/v1/demo/sweep")
    assert resp.status_code == 200
    data = resp.json()
    assert "swept" in data
    assert "resolved" in data
    assert data["next_auto_sweep_in_s"] == 15


def test_stats_protocol_metrics(client):
    """GET /api/v1/stats returns all protocol counters for the dashboard strip."""
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    data = resp.json()
    for field in [
        "challenges_issued", "fulfilled_count", "in_doubt_count",
        "compensated_count", "attacks_blocked", "chain_height", "reconciler_tick_s"
    ]:
        assert field in data, f"Missing field in stats: {field}"
