"""facilitator/refunder.py — Compensation saga."""
import json

from core.clock import now
from core.catalog import MAX_ATTEMPTS, POLICY_VERSION
from state.ledger import cas, bump


def compensate(conn, adapter, cid: str, reason: str) -> dict:
    """
    Compensation saga:
    1. CAS → COMPENSATING
    2. If no payment_id: cancel obligation pre-settlement
    3. Read-before-write: list existing refunds
    4. If matching refund exists: converge
    5. Issue refund with idempotency key
    6. CAS → COMPENSATED or bump on failure
    """
    result, seq = cas(conn, cid, "COMPENSATING", actor="refunder",
                      event="COMPENSATION_START",
                      fail_reason=reason,
                      payload={"policy_version": POLICY_VERSION, "reason": reason})

    if result == "STALE":
        # Already at or past COMPENSATING — re-read state
        txn = conn.execute(
            "SELECT * FROM txn WHERE challenge_id=?", (cid,)
        ).fetchone()
        if txn and txn["state"] == "COMPENSATED":
            return _receipt(txn)
    elif result != "APPLIED":
        return {"error": "STATE_CONFLICT", "detail": f"CAS result: {result}"}

    txn = conn.execute(
        "SELECT * FROM txn WHERE challenge_id=?", (cid,)
    ).fetchone()

    if txn is None:
        return {"error": "ORPHAN", "detail": "Transaction not found"}

    # If no payment was made, cancel the obligation
    if txn["payment_id"] is None:
        cas(conn, cid, "COMPENSATED", actor="refunder",
            event="OBLIGATION_CANCELLED_PRE_SETTLEMENT",
            payload={"policy_version": POLICY_VERSION, "payment_mode": "none"},
            also=(
                ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                 (cid,)),
            ))
        return _receipt_no_refund(txn)

    # READ BEFORE WRITE — check for existing refund
    try:
        existing = adapter.list_refunds(txn["payment_id"])
    except Exception:
        existing = []

    mine = [r for r in existing if (r.get("notes") or {}).get("challenge_id") == cid]
    if mine:
        refund_id = mine[0]["id"]
        amount = txn["amount_paise"]
        mandate_token = _get_mandate_token(txn["agent_kid"])

        also_writes = [
            ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
             (cid,)),
        ]
        if mandate_token:
            also_writes.append(
                ("UPDATE mandates SET debited_paise=debited_paise-? WHERE token=?",
                 (amount, mandate_token))
            )

        cas(conn, cid, "COMPENSATED", actor="refunder",
            refund_id=refund_id, event="COMPENSATION_CONVERGED",
            payment_mode=txn["payment_mode"],
            payload={"policy_version": POLICY_VERSION,
                     "payment_mode": txn["payment_mode"] or "harness"},
            also=tuple(also_writes))
        return _receipt(conn.execute(
            "SELECT * FROM txn WHERE challenge_id=?", (cid,)).fetchone())

    # Issue refund
    try:
        ref = adapter.refund(txn["payment_id"], txn["amount_paise"], cid)
    except Exception as e:
        bump(conn, cid, reason="refund_in_doubt", next_at=now() + 5,
             event="FULFIL_ATTEMPT_FAILED")

        # Check max attempts
        txn_fresh = conn.execute(
            "SELECT attempts FROM txn WHERE challenge_id=?", (cid,)
        ).fetchone()
        if txn_fresh and txn_fresh["attempts"] >= MAX_ATTEMPTS:
            cas(conn, cid, "DEAD_LETTER", actor="refunder",
                event="ALERT_DEAD_LETTER",
                payload={"policy_version": POLICY_VERSION})

        return {
            "error": "UPSTREAM_FULFILMENT_FAILED",
            "settlement": {"status": "refund_pending",
                           "paymentId": txn["payment_id"],
                           "amountPaise": txn["amount_paise"]},
            "retryable": True,
        }

    # Refund success
    refund_id = ref["id"]
    amount = txn["amount_paise"]
    mandate_token = _get_mandate_token(txn["agent_kid"])

    also_writes = [
        ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
         (cid,)),
    ]
    if mandate_token:
        also_writes.append(
            ("UPDATE mandates SET debited_paise=debited_paise-? WHERE token=?",
             (amount, mandate_token))
        )

    cas(conn, cid, "COMPENSATED", actor="refunder",
        refund_id=refund_id, event="COMPENSATION_DONE",
        payment_mode=txn["payment_mode"],
        payload={"policy_version": POLICY_VERSION,
                 "payment_mode": txn["payment_mode"] or "harness"},
        also=tuple(also_writes))

    txn_final = conn.execute(
        "SELECT * FROM txn WHERE challenge_id=?", (cid,)
    ).fetchone()
    return _receipt(txn_final)


def _get_mandate_token(kid: str) -> str | None:
    from core.catalog import AGENT_POLICY
    policy = AGENT_POLICY.get(kid)
    return policy["mandate_token"] if policy else None


def _receipt(txn) -> dict:
    return {
        "error": "UPSTREAM_FULFILMENT_FAILED",
        "settlement": {
            "status": "refunded",
            "paymentId": txn["payment_id"],
            "refundId": txn["refund_id"],
            "amountPaise": txn["amount_paise"],
        },
        "budget": {
            "heldPaise": 0,
            "releasedPaise": txn["amount_paise"],
        },
        "retryable": True,
        "auditRef": txn["challenge_id"],
    }


def _receipt_no_refund(txn) -> dict:
    return {
        "error": "UPSTREAM_FULFILMENT_FAILED",
        "settlement": {
            "status": "cancelled_pre_settlement",
            "paymentId": None,
            "refundId": None,
            "amountPaise": txn["amount_paise"],
        },
        "retryable": True,
        "auditRef": txn["challenge_id"],
    }
