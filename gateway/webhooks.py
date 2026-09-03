"""gateway/webhooks.py — Razorpay webhook handler with HMAC verification."""
import hashlib
import json
import sqlite3

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.crypto import hmac_sha256_hex, constant_time_eq
from core.clock import now
from state.db import get_connection
from state.ledger import cas, note

router = APIRouter()


@router.post("/webhooks/razorpay")
async def receive_webhook(request: Request):
    """
    Webhook handler:
    1. Hash raw bytes (never re-serialized)
    2. HMAC verify
    3. Dedupe by event_id
    4. Extract challenge_id from notes
    5. Map event to state transition
    """
    import os
    webhook_secret = os.environ.get("RZP_WEBHOOK_SECRET", "whsec_local_demo_secret")
    conn = get_connection()

    # 1. Raw bytes
    raw = await request.body()
    raw_sha = hashlib.sha256(raw).hexdigest()

    # 2. HMAC verify
    sig_header = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac_sha256_hex(webhook_secret, raw)
    if not constant_time_eq(expected, sig_header):
        return JSONResponse(status_code=401,
                            content={"error": "WEBHOOK_BAD_SIGNATURE"})

    # Parse body
    try:
        body = json.loads(raw)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "INVALID_JSON"})

    event_id = body.get("event", {}).get("id") if isinstance(body.get("event"), dict) else None
    if not event_id:
        # Alternate format
        event_id = body.get("id", f"evt_{raw_sha[:16]}")

    event_type = body.get("event", "")
    if isinstance(event_type, dict):
        event_type = event_type.get("name", "")

    # 3. Dedupe
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO webhook_events (event_id, event_type, challenge_id, "
                "raw_sha256, received_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, event_type, None, raw_sha, now())
            )
            conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            return JSONResponse(content={"ok": True, "dedup": True})
        except Exception:
            conn.execute("ROLLBACK")
            raise
    except Exception:
        return JSONResponse(content={"ok": True, "dedup": True})

    # 4. Extract challenge_id from notes
    challenge_id = _extract_challenge_id(body)

    # Update webhook_events with challenge_id
    if challenge_id:
        conn.execute(
            "UPDATE webhook_events SET challenge_id=? WHERE event_id=?",
            (challenge_id, event_id)
        )

    # 5. Map and CAS
    cas_result = None
    if challenge_id:
        cas_result = _process_event(conn, event_type, challenge_id, body)

    return JSONResponse(content={"ok": True, "cas": cas_result})


def _extract_challenge_id(body: dict) -> str | None:
    """Extract challenge_id from payload.*.entity.notes."""
    payload = body.get("payload", {})
    for key in ("payment", "order", "refund"):
        entity = payload.get(key, {}).get("entity", {})
        notes = entity.get("notes", {})
        cid = notes.get("challenge_id")
        if cid:
            return cid
    return None


def _process_event(conn, event_type: str, challenge_id: str, body: dict) -> str | None:
    """Map webhook event to state transition."""
    from core.catalog import POLICY_VERSION

    event_map = {
        "order.paid": ("SETTLED", "WEBHOOK_order.paid"),
        "payment.captured": ("SETTLED", "WEBHOOK_payment.captured"),
        "payment.authorized": ("SETTLED", "WEBHOOK_payment.authorized"),
        "payment.failed": ("FAILED", "WEBHOOK_payment.failed"),
        "refund.processed": ("COMPENSATED", "WEBHOOK_refund.processed"),
    }

    note_only = {"refund.created", "refund.failed"}

    if event_type in note_only:
        note(conn, challenge_id, f"WEBHOOK_{event_type}", "webhook",
             {"policy_version": POLICY_VERSION})
        return "NOTE"

    mapping = event_map.get(event_type)
    if not mapping:
        note(conn, challenge_id, f"WEBHOOK_{event_type}", "webhook",
             {"policy_version": POLICY_VERSION})
        return "UNKNOWN_EVENT"

    to_state, event_name = mapping

    # Extract payment/refund details
    payment_entity = body.get("payload", {}).get("payment", {}).get("entity", {})
    refund_entity = body.get("payload", {}).get("refund", {}).get("entity", {})

    kwargs = {}
    if payment_entity.get("id"):
        kwargs["payment_id"] = payment_entity["id"]
    if payment_entity.get("order_id"):
        kwargs["order_id"] = payment_entity["order_id"]
    if refund_entity.get("id"):
        kwargs["refund_id"] = refund_entity["id"]

    also_writes = []
    if to_state == "SETTLED":
        kwargs["settled_via"] = "webhook"
    elif to_state == "COMPENSATED":
        also_writes.append(
            ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
             (challenge_id,))
        )
    elif to_state == "FAILED":
        also_writes.append(
            ("UPDATE budget_reservations SET status='RELEASED' WHERE challenge_id=?",
             (challenge_id,))
        )

    result, seq = cas(conn, challenge_id, to_state, actor="webhook",
                      event=event_name,
                      payload={"policy_version": POLICY_VERSION},
                      also=tuple(also_writes),
                      **kwargs)
    return result
