"""facilitator/settler.py — Settlement flow."""
from dataclasses import dataclass

from core.clock import now
from core.errors import PaymentFailed
from state.ledger import cas, note


@dataclass
class SettleResult:
    status: str  # "settled" | "in_doubt" | "failed"
    payment_id: str | None = None
    order_id: str | None = None
    payment_mode: str | None = None


def settle(conn, adapter, cid: str, paise: int,
           mandate_token: str | None = None) -> SettleResult:
    """
    Settlement flow:
    1. CAS → SETTLING (WAL intent before network I/O)
    2. Create order + debit
    3. On success: CAS → SETTLED
    4. On timeout: CAS → SETTLEMENT_UNKNOWN
    5. On decline: CAS → FAILED
    """
    from core.catalog import POLICY_VERSION

    # WAL INTENT BEFORE ANY NETWORK I/O
    result, seq = cas(conn, cid, "SETTLING", actor="settler",
                      event="SETTLE_PENDING",
                      payload={"policy_version": POLICY_VERSION})
    if result != "APPLIED":
        return SettleResult(status="failed")

    try:
        order = adapter.create_order(cid, paise)
        pay = adapter.debit(order, cid)
    except PaymentFailed as e:
        # Authoritative decline
        cas(conn, cid, "FAILED", actor="settler", event="SETTLE_FAILED",
            fail_reason=str(e), payment_mode=adapter.mode,
            payload={"policy_version": POLICY_VERSION, "payment_mode": adapter.mode},
            also=(
                ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                 (cid,)),
            ))
        return SettleResult(status="failed")
    except Exception as e:
        # Timeout / connection error — NEVER FAILED from an exception
        cas(conn, cid, "SETTLEMENT_UNKNOWN", actor="settler",
            event="SETTLE_IN_DOUBT", attempt_inc=1,
            payment_mode=adapter.mode,
            payload={"policy_version": POLICY_VERSION, "payment_mode": adapter.mode,
                     "error": str(e)})
        return SettleResult(status="in_doubt", payment_mode=adapter.mode)

    # Success
    payment_id = pay.get("id", pay.get("razorpay_payment_id", ""))
    order_id = order.get("id", "")

    also_writes = [
        ("UPDATE mandates SET debited_paise=debited_paise+? WHERE token=?",
         (paise, mandate_token)),
    ] if mandate_token else []

    cas(conn, cid, "SETTLED", actor="settler", event="SETTLED",
        order_id=order_id, payment_id=payment_id,
        settled_via="sync", payment_mode=adapter.mode,
        payload={"policy_version": POLICY_VERSION, "payment_mode": adapter.mode},
        also=tuple(also_writes))

    return SettleResult(
        status="settled",
        payment_id=payment_id,
        order_id=order_id,
        payment_mode=adapter.mode,
    )
