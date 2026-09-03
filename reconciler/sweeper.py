"""reconciler/sweeper.py — Background sweeper for stuck transactions."""
import random

from core.clock import now
from core.catalog import SETTLE_GRACE_S, MAX_ATTEMPTS, POLICY_VERSION
from state.ledger import cas, note, claim_lease
from state.states import RANK


def sweep(conn, adapter):
    """
    Sweep stuck transactions.
    Called every RECONCILE_TICK_S from the gateway lifespan with its own connection.
    """
    import os
    now_ts = now()

    # Claim rows
    rows = claim_lease(
        conn,
        ["SETTLEMENT_UNKNOWN", "SETTLING", "SETTLED", "FULFILLING", "COMPENSATING"],
        limit=20,
        now_ts=now_ts,
    )

    for row in rows:
        cid = row["challenge_id"]
        state = row["state"]
        attempts = row["attempts"]

        # Max attempts → dead letter
        if attempts >= MAX_ATTEMPTS:
            result, _ = cas(conn, cid, "DEAD_LETTER", actor="sweeper",
                            event="ALERT_MAX_ATTEMPTS",
                            payload={"policy_version": POLICY_VERSION,
                                     "attempts": attempts})
            continue

        if state in ("SETTLEMENT_UNKNOWN", "SETTLING"):
            _resolve_settlement(conn, adapter, row, now_ts)
        elif state == "SETTLED":
            _recover_stranded(conn, adapter, row, now_ts)
        elif state == "FULFILLING":
            _recover_fulfilling(conn, adapter, row, now_ts)
        elif state == "COMPENSATING":
            _retry_compensation(conn, adapter, row)


def _resolve_settlement(conn, adapter, row, now_ts: int):
    """Resolve SETTLEMENT_UNKNOWN or stuck SETTLING."""
    cid = row["challenge_id"]

    # Try to find the order
    order = adapter.find_order(cid)

    if order is None:
        # No order found
        grace_expired = (now_ts - row["created_at"]) > SETTLE_GRACE_S
        if grace_expired:
            cas(conn, cid, "FAILED", actor="sweeper",
                event="RESOLVED_NO_PAYMENT",
                payload={"policy_version": POLICY_VERSION},
                also=(
                    ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                     (cid,)),
                ))
        else:
            # Backoff
            backoff = min(2 ** row["attempts"], 60) * (0.7 + 0.6 * random.random())
            conn.execute(
                "UPDATE txn SET next_at=?, attempts=attempts+1 WHERE challenge_id=?",
                (now_ts + int(backoff), cid)
            )
        return

    # Order found — check payments
    payments = adapter.order_payments(order["id"])

    if not payments:
        # No payments yet
        grace_expired = (now_ts - row["created_at"]) > SETTLE_GRACE_S
        if grace_expired:
            cas(conn, cid, "FAILED", actor="sweeper",
                event="RESOLVED_NO_PAYMENT",
                payload={"policy_version": POLICY_VERSION},
                also=(
                    ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                     (cid,)),
                ))
        else:
            backoff = min(2 ** row["attempts"], 60) * (0.7 + 0.6 * random.random())
            conn.execute(
                "UPDATE txn SET next_at=?, attempts=attempts+1 WHERE challenge_id=?",
                (now_ts + int(backoff), cid)
            )
        return

    # Check payment status
    for pay in payments:
        status = pay.get("status", "")
        if status in ("captured", "authorized"):
            from core.catalog import AGENT_POLICY
            mandate_token = None
            policy = AGENT_POLICY.get(row["agent_kid"])
            if policy:
                mandate_token = policy["mandate_token"]

            also_writes = []
            if mandate_token:
                also_writes.append(
                    ("UPDATE mandates SET debited_paise=debited_paise+? WHERE token=?",
                     (row["amount_paise"], mandate_token))
                )

            cas(conn, cid, "SETTLED", actor="sweeper",
                event="RESOLVED_SETTLED",
                order_id=order["id"], payment_id=pay["id"],
                settled_via="reconciler", payment_mode=adapter.mode,
                payload={"policy_version": POLICY_VERSION,
                         "payment_mode": adapter.mode},
                also=tuple(also_writes))
            return

        if status == "failed":
            grace_expired = (now_ts - row["created_at"]) > SETTLE_GRACE_S
            if grace_expired:
                cas(conn, cid, "FAILED", actor="sweeper",
                    event="SETTLE_FAILED",
                    payload={"policy_version": POLICY_VERSION},
                    also=(
                        ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
                         (cid,)),
                    ))
            return


def _recover_stranded(conn, adapter, row, now_ts: int):
    """Recover SETTLED rows that never progressed to FULFILLING."""
    import os
    cid = row["challenge_id"]
    updated_at = row["updated_at"]

    # Only recover if stale enough (10 seconds)
    if now_ts - updated_at < 10:
        return

    note(conn, cid, "RECOVERED_STRANDED", "sweeper",
         {"policy_version": POLICY_VERSION})

    upstream_url = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9000")
    from gateway.fulfilment import fulfil
    fulfil(conn, adapter, cid, upstream_url)


def _recover_fulfilling(conn, adapter, row, now_ts: int):
    """Recover FULFILLING rows whose lease expired."""
    import os
    cid = row["challenge_id"]
    lease = row["lease_until"]

    if lease > now_ts:
        return  # Lease still active

    upstream_url = os.environ.get("UPSTREAM_URL", "http://127.0.0.1:9000")
    from gateway.fulfilment import fulfil
    fulfil(conn, adapter, cid, upstream_url)


def _retry_compensation(conn, adapter, row):
    """Re-enter compensation for stuck COMPENSATING rows."""
    from facilitator.refunder import compensate
    compensate(conn, adapter, row["challenge_id"], "sweeper_retry")
