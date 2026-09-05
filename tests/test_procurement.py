"""tests/test_procurement.py — Rigorous tests for Sourcing Analyst, PO Approval Gate, and Merchant Growth."""
import pytest
import hashlib
from fastapi.testclient import TestClient

from gateway.app import app
from state.db import get_connection
from state.ledger import append_system_audit, is_po_approved, verify_chain


@pytest.fixture
def client():
    return TestClient(app)


def test_system_audit_hash_parity():
    """System-scoped audit events (no challenge_id) must compute valid chain hashes without breaking verify_chain()."""
    conn = get_connection()
    seq = append_system_audit(
        conn,
        event="PO_APPROVED",
        actor="Engineering Lead",
        payload={"po_number": "PO-TEST-CHAIN-01", "ceiling_paise": 10800, "bom_sha256": "abcdef"*10, "line_count": 4}
    )
    assert seq > 0

    valid, head = verify_chain(conn)
    assert valid is True, f"System-row append broke hash chain at entry #{head}"


def test_is_po_approved_superseded_by_cancellation():
    """Audit ledger is the single source of truth: cancellation supersedes approval."""
    conn = get_connection()
    po_num = "PO-TEST-CANCEL-01"

    # Not approved yet
    assert is_po_approved(conn, po_num) is None

    # Approved
    append_system_audit(
        conn,
        event="PO_APPROVED",
        actor="CTO",
        payload={"po_number": po_num, "ceiling_paise": 5000}
    )
    appr = is_po_approved(conn, po_num)
    assert appr is not None
    assert appr["approver"] == "CTO"
    assert appr["ceiling_paise"] == 5000

    # Cancelled later
    append_system_audit(
        conn,
        event="PO_CANCELLED",
        actor="operator",
        payload={"po_number": po_num, "reason": "test_cancellation"}
    )
    assert is_po_approved(conn, po_num) is None


def test_plan_generates_bom_hash_and_alternatives(client):
    """Sourcing analyst generates PO with canonical bom_sha256, unit_paise, alternatives, and savings."""
    resp = client.post("/api/console/plan", json={"mission": "compare"})
    assert resp.status_code == 200
    plan = resp.json()

    assert plan["status"] == "DRAFT"
    assert plan["po_number"].startswith("PO-")
    assert len(plan["bom_sha256"]) == 64
    assert plan["total_paise"] > 0
    assert plan["baseline_paise"] >= plan["total_paise"]
    assert plan["savings_paise"] >= 0
    assert plan["vendors_compared"] >= 1
    assert isinstance(plan["categories"], list)

    for item in plan["items"]:
        assert "item_id" in item
        assert "unit_paise" in item
        assert "alternatives" in item


def test_approve_exact_ceiling_match(client):
    """Approval requires exact ceiling match — no tolerance window."""
    plan_resp = client.post("/api/console/plan", json={"mission": "rag"})
    plan = plan_resp.json()
    po_num = plan["po_number"]
    total = plan["total_paise"]
    bom_hash = plan["bom_sha256"]

    # Reject ceiling + 1
    r_over = client.post("/api/console/approve", json={
        "approver": "Finance Controller",
        "ceiling_paise": total + 1,
        "po_number": po_num,
        "bom_sha256": bom_hash,
    })
    assert r_over.status_code == 409
    assert r_over.json()["detail"]["error"] == "CEILING_MISMATCH"

    # Reject ceiling - 1
    r_under = client.post("/api/console/approve", json={
        "approver": "Finance Controller",
        "ceiling_paise": total - 1,
        "po_number": po_num,
        "bom_sha256": bom_hash,
    })
    assert r_under.status_code == 409
    assert r_under.json()["detail"]["error"] == "CEILING_MISMATCH"

    # Accept exact ceiling
    r_ok = client.post("/api/console/approve", json={
        "approver": "Finance Controller",
        "ceiling_paise": total,
        "po_number": po_num,
        "bom_sha256": bom_hash,
    })
    assert r_ok.status_code == 200
    assert r_ok.json()["approved"] is True
    assert r_ok.json()["ceiling_paise"] == total


def test_approve_bom_mismatch(client):
    """Reject approval when client sends a mismatched BOM hash."""
    plan_resp = client.post("/api/console/plan", json={"mission": "compare"})
    plan = plan_resp.json()

    r_bad_bom = client.post("/api/console/approve", json={
        "approver": "Engineering Lead",
        "ceiling_paise": plan["total_paise"],
        "po_number": plan["po_number"],
        "bom_sha256": "0" * 64,
    })
    assert r_bad_bom.status_code == 409
    assert r_bad_bom.json()["detail"]["error"] == "BOM_MISMATCH"


def test_execute_requires_human_approval(client):
    """Execution without recorded approval is blocked by server gate with 403 PO_NOT_APPROVED."""
    # Create fresh unapproved plan
    plan_resp = client.post("/api/console/plan", json={"mission": "music"})
    plan = plan_resp.json()
    po_num = plan["po_number"]

    # Reset envelope to cancel any prior lingering approvals
    client.post("/api/console/reset-envelope")

    exec_resp = client.post("/api/console/execute", json={"po_number": po_num})
    assert exec_resp.status_code == 403
    assert exec_resp.json()["detail"]["error"] == "PO_NOT_APPROVED"


def test_execute_bom_mismatch_after_approval(client):
    """Execution detects if the draft BOM was altered after approval."""
    plan_resp = client.post("/api/console/plan", json={"mission": "copilot"})
    plan = plan_resp.json()
    po_num = plan["po_number"]

    # Approve cleanly
    appr_resp = client.post("/api/console/approve", json={
        "approver": "CTO",
        "ceiling_paise": plan["total_paise"],
        "po_number": po_num,
        "bom_sha256": plan["bom_sha256"],
    })
    assert appr_resp.status_code == 200

    # Tamper with the draft's bom_sha256 in the database
    conn = get_connection()
    conn.execute("UPDATE po_drafts SET bom_sha256='tampered_hash_123' WHERE po_number=?", (po_num,))

    exec_resp = client.post("/api/console/execute", json={"po_number": po_num})
    assert exec_resp.status_code == 409
    assert exec_resp.json()["detail"]["error"] == "BOM_MISMATCH"


def test_stats_merchant_lens(client):
    """Stats endpoint contains both buyer-side controls and merchant-side growth metrics."""
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    s = resp.json()

    # Buyer lens
    assert "challenges_issued" in s
    assert "in_doubt_count" in s
    assert "attacks_blocked" in s
    assert "chain_height" in s
    assert "reconciler_tick_s" in s

    # Merchant lens
    assert "aov_single_paise" in s
    assert "aov_pass_paise" in s
    assert "upsell_offered" in s
    assert "upsell_accepted" in s
    assert "upsell_take_rate" in s
    assert "vendors_transacted" in s
    assert "repeat_purchase_count" in s
    assert "savings_realised_paise" in s

    # No negative paise
    assert s["aov_single_paise"] > 0
    assert s["aov_pass_paise"] > 0


def test_402_challenge_contains_price_options(client):
    """402 Payment Required response surfaces price_options with single call and day pass."""
    resp = client.post("/provision/deepseek-v4-flash", headers={"X-Razor402-Agent": "agt_coding_01"})
    assert resp.status_code == 402
    body = resp.json()

    assert "price_options" in body
    opts = body["price_options"]
    assert len(opts) >= 2

    single = next(o for o in opts if o["kind"] == "single")
    pass_opt = next(o for o in opts if o["kind"] == "day_pass")

    assert single["price_paise"] == 400
    assert pass_opt["price_paise"] == 4000


def test_attack_repeatability_twice(client):
    """All 5 attacks must return defended=True across repeated runs (take-proof demo)."""
    attacks = ["prompt_injection", "confused_deputy", "replay", "pool_drain", "revoked_envelope"]

    # Run 1
    for a in attacks:
        r = client.post("/api/v1/demo/attack", json={"kind": a})
        assert r.status_code == 200
        assert r.json()["defended"] is True, f"Attack {a} failed on run 1"

    # Run 2
    for a in attacks:
        r = client.post("/api/v1/demo/attack", json={"kind": a})
        assert r.status_code == 200
        assert r.json()["defended"] is True, f"Attack {a} failed on run 2"


def test_execute_returns_within_deadline_when_merchant_hangs(client, monkeypatch):
    """Execution returns structured JSON without hanging indefinitely when merchant operations timeout."""
    import httpx

    # Plan and approve
    plan_resp = client.post("/api/console/plan", json={"mission": "compare"})
    plan = plan_resp.json()
    po_num = plan["po_number"]

    appr_resp = client.post("/api/console/approve", json={
        "approver": "Test Lead",
        "ceiling_paise": plan["total_paise"],
        "po_number": po_num,
        "bom_sha256": plan["bom_sha256"],
    })
    assert appr_resp.status_code == 200

    # Simulate timeout on the AsyncClient post
    original_post = httpx.AsyncClient.post

    async def mock_hang_post(self, url, *args, **kwargs):
        if "/provision/" in str(url):
            raise httpx.ReadTimeout("Simulated merchant hang exceeding FULFIL_DEADLINE_S")
        return await original_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_hang_post)

    exec_resp = client.post("/api/console/execute", json={"po_number": po_num})
    assert exec_resp.status_code == 200
    data = exec_resp.json()

    assert "ok" in data
    assert "steps" in data
    assert len(data["steps"]) > 0
    # First step after catalog discovery was caught and marked with timeout
    procure_steps = [s for s in data["steps"] if s["tool"] == "procure"]
    assert any(s["status"] in ("failed", "settlement_unknown") for s in procure_steps)
    assert any("TIMEOUT" in (s.get("error_code") or "") for s in procure_steps)

