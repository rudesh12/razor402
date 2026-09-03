"""gateway/replay.py — JTI idempotency resolution."""
from dataclasses import dataclass
import sqlite3
import json


@dataclass
class ReplayDecision:
    action: str  # PROCEED | REPLAY | ERROR
    status_code: int | None = None
    body: dict | bytes | None = None
    headers: dict | None = None
    challenge_id: str | None = None


def resolve(conn, jti: str, resource_hash_val: str,
            cid: str) -> ReplayDecision:
    """
    JTI idempotency resolution.
    Returns ReplayDecision indicating how to proceed.
    """
    from core.clock import now

    # Try to insert; UNIQUE constraint on jti decides the race winner
    try:
        conn.execute(
            "INSERT INTO jti_seen (jti, challenge_id, resource_hash, seen_at) "
            "VALUES (?, ?, ?, ?)",
            (jti, cid, resource_hash_val, now())
        )
        conn.commit()
        return ReplayDecision(action="PROCEED")
    except sqlite3.IntegrityError:
        pass

    # JTI seen — look up what happened
    row = conn.execute(
        "SELECT challenge_id, resource_hash FROM jti_seen WHERE jti=?", (jti,)
    ).fetchone()

    if row is None:
        return ReplayDecision(action="PROCEED")

    # Different resource hash → 409 IDEMPOTENCY_KEY_REUSE
    if row["resource_hash"] != resource_hash_val:
        return ReplayDecision(
            action="ERROR",
            status_code=409,
            body={"error": "IDEMPOTENCY_KEY_REUSE",
                  "detail": "Same jti used for different resource"},
            challenge_id=row["challenge_id"],
        )

    # Same resource hash — look up the txn state
    existing_cid = row["challenge_id"]
    txn = conn.execute(
        "SELECT state, rank, resp_status, resp_body, payment_id, refund_id, "
        "amount_paise, payment_mode, fail_reason "
        "FROM txn WHERE challenge_id=?", (existing_cid,)
    ).fetchone()

    if txn is None:
        return ReplayDecision(
            action="ERROR",
            status_code=409,
            body={"error": "IN_FLIGHT", "detail": "Transaction in progress"},
            headers={"Retry-After": "1"},
            challenge_id=existing_cid,
        )

    state = txn["state"]

    if state == "FULFILLED":
        # Replay cached response byte-identical
        resp_body = txn["resp_body"]
        if isinstance(resp_body, bytes):
            try:
                resp_body = json.loads(resp_body)
            except Exception:
                pass
        return ReplayDecision(
            action="REPLAY",
            status_code=txn["resp_status"] or 200,
            body=resp_body,
            headers={
                "X-Razor402-Replay": "true",
                "X-Razor402-State": "FULFILLED",
                "X-PAYMENT-RESPONSE": json.dumps({
                    "paymentId": txn["payment_id"],
                    "amountPaise": txn["amount_paise"],
                    "status": "captured",
                    "paymentMode": txn["payment_mode"] or "harness",
                }),
            },
            challenge_id=existing_cid,
        )

    if state == "COMPENSATED":
        return ReplayDecision(
            action="REPLAY",
            status_code=502,
            body={
                "error": "UPSTREAM_FULFILMENT_FAILED",
                "settlement": {
                    "status": "refunded",
                    "paymentId": txn["payment_id"],
                    "refundId": txn["refund_id"],
                    "amountPaise": txn["amount_paise"],
                },
                "retryable": True,
            },
            headers={
                "X-Razor402-Replay": "true",
                "X-Razor402-State": "COMPENSATED",
            },
            challenge_id=existing_cid,
        )

    if state == "FAILED":
        return ReplayDecision(
            action="REPLAY",
            status_code=402,
            body={
                "error": txn["fail_reason"] or "PAYMENT_FAILED",
                "detail": "Previously failed",
            },
            headers={
                "X-Razor402-Replay": "true",
                "X-Razor402-State": "FAILED",
            },
            challenge_id=existing_cid,
        )

    # In-flight (rank 20-40)
    from state.states import RANK
    rank = txn["rank"]
    if 20 <= rank <= 40:
        return ReplayDecision(
            action="ERROR",
            status_code=409,
            body={"error": "IN_FLIGHT", "detail": f"State: {state}"},
            headers={
                "Retry-After": "1",
                "X-Razor402-State": state,
            },
            challenge_id=existing_cid,
        )

    # Any other state
    return ReplayDecision(
        action="ERROR",
        status_code=409,
        body={"error": "STATE_CONFLICT", "detail": f"State: {state}"},
        challenge_id=existing_cid,
    )
