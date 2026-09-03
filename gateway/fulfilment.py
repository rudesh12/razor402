"""gateway/fulfilment.py — Upstream call, retries, cache."""
import json
import hashlib

import httpx

from core.clock import now
from core.catalog import FULFIL_DEADLINE_S, FULFIL_MAX_ATTEMPTS, CATALOG
from state.ledger import cas, bump
from facilitator.refunder import compensate


def fulfil(conn, adapter, cid: str,
           upstream_url: str = "http://127.0.0.1:9000") -> dict:
    """
    Fulfilment flow: loads everything from txn row.
    Retries up to FULFIL_MAX_ATTEMPTS on 5xx.
    4xx is treated as merchant-answered (FULFILLED).
    """
    from core.catalog import POLICY_VERSION

    txn = conn.execute(
        "SELECT * FROM txn WHERE challenge_id=?", (cid,)
    ).fetchone()

    if txn is None:
        return {"error": "ORPHAN"}

    # CAS → FULFILLING
    lease_until = now() + int(FULFIL_DEADLINE_S) + 5
    result, seq = cas(conn, cid, "FULFILLING", actor="fulfiller",
                      event="FULFILLING", lease_until=lease_until,
                      payload={"policy_version": POLICY_VERSION})

    if result == "STALE":
        # Already at or past FULFILLING — check if FULFILLED
        txn = conn.execute(
            "SELECT * FROM txn WHERE challenge_id=?", (cid,)
        ).fetchone()
        if txn["state"] == "FULFILLED":
            return _fulfilled_response(txn)
    elif result != "APPLIED":
        return {"error": "STATE_CONFLICT", "detail": f"CAS result: {result}"}

    item_id = txn["item_id"]
    last_reason = None

    for attempt in range(1, FULFIL_MAX_ATTEMPTS + 1):
        try:
            resp = httpx.post(
                f"{upstream_url}/provision/{item_id}",
                headers={"X-Challenge-Id": cid},
                timeout=FULFIL_DEADLINE_S,
            )

            if resp.status_code < 500:
                # Merchant answered (including 4xx) — FULFILLED
                resp_body = resp.content
                resp_sha = hashlib.sha256(resp_body).hexdigest()

                also_writes = [
                    ("UPDATE budget_reservations SET status='CAPTURED' WHERE challenge_id=?",
                     (cid,)),
                ]

                # Grant pass if day-pass item
                item = CATALOG.get(item_id, {})
                if item.get("category") == "bundle" and item.get("valid_seconds"):
                    expires_at = now() + item["valid_seconds"]
                    covers = item.get("covers", item_id)
                    also_writes.append(
                        ("INSERT INTO passes (agent_kid, item_id, expires_at, challenge_id) "
                         "VALUES (?, ?, ?, ?)",
                         (txn["agent_kid"], covers, expires_at, cid))
                    )
                    from state.ledger import note
                    note(conn, cid, "PASS_GRANTED", "fulfiller",
                         {"item_id": item_id, "covers": covers,
                          "expires_at": expires_at})

                cas(conn, cid, "FULFILLED", actor="fulfiller",
                    event="FULFILLED",
                    resp_status=resp.status_code,
                    resp_body=resp_body,
                    resp_sha256=f"sha256:{resp_sha}",
                    payment_mode=txn["payment_mode"],
                    payload={"policy_version": POLICY_VERSION,
                             "payment_mode": txn["payment_mode"] or "harness"},
                    also=tuple(also_writes))

                return _fulfilled_response(
                    conn.execute("SELECT * FROM txn WHERE challenge_id=?",
                                 (cid,)).fetchone(),
                    resp.status_code,
                    resp_body,
                )

            # 5xx — retry
            last_reason = f"upstream_{resp.status_code}"
            bump(conn, cid, reason=last_reason)

        except (httpx.TimeoutException, httpx.ConnectError, OSError) as e:
            last_reason = f"upstream_error_{type(e).__name__}"
            bump(conn, cid, reason=last_reason)

    # All retries exhausted — compensate
    return compensate(conn, adapter, cid, last_reason or "upstream_exhausted")


def _fulfilled_response(txn, status_code: int | None = None,
                        body: bytes | None = None) -> dict:
    """Build the response dict for a fulfilled transaction."""
    resp_body = body or txn["resp_body"]
    if isinstance(resp_body, bytes):
        try:
            resp_body = json.loads(resp_body)
        except Exception:
            pass

    return {
        "status_code": status_code or txn["resp_status"] or 200,
        "body": resp_body,
        "payment_response": {
            "paymentId": txn["payment_id"],
            "amountPaise": txn["amount_paise"],
            "status": "captured",
            "auditSeq": None,
            "paymentMode": txn["payment_mode"] or "harness",
        },
        "state": "FULFILLED",
    }
