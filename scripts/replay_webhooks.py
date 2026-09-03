"""scripts/replay_webhooks.py — Locally signed webhook replay for testing."""
import os
import sys
import json
import random
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import httpx
from core.crypto import hmac_sha256_hex


def build_webhook_payload(event_id: str, event_type: str,
                          payment_id: str = "pay_Htest",
                          order_id: str = "order_Htest",
                          challenge_id: str = "test-cid",
                          refund_id: str | None = None) -> dict:
    """Build a webhook payload matching Razorpay's format."""
    payload: dict = {
        "event": {"id": event_id, "name": event_type},
        "payload": {}
    }

    if "payment" in event_type:
        payload["payload"]["payment"] = {
            "entity": {
                "id": payment_id,
                "order_id": order_id,
                "amount": 500,
                "status": event_type.split(".")[-1],
                "notes": {"challenge_id": challenge_id},
            }
        }

    if "order" in event_type:
        payload["payload"]["order"] = {
            "entity": {
                "id": order_id,
                "amount": 500,
                "status": "paid",
                "notes": {"challenge_id": challenge_id},
            }
        }

    if "refund" in event_type:
        payload["payload"]["refund"] = {
            "entity": {
                "id": refund_id or f"rfnd_Htest",
                "payment_id": payment_id,
                "amount": 500,
                "status": event_type.split(".")[-1],
                "notes": {"challenge_id": challenge_id},
            }
        }

    return payload


def main():
    parser = argparse.ArgumentParser(description="Replay webhook events")
    parser.add_argument("--order", default="captured,paid",
                        help="Comma-separated events to replay")
    parser.add_argument("--after-fulfil", action="store_true")
    parser.add_argument("--shuffle-seeds", type=int, default=1)
    parser.add_argument("--challenge-id", default="test-cid")
    parser.add_argument("--gateway", default=None)
    args = parser.parse_args()

    gateway_url = args.gateway or os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")
    webhook_secret = os.environ.get("RZP_WEBHOOK_SECRET", "whsec_local_demo_secret")

    events = []
    for evt in args.order.split(","):
        evt = evt.strip()
        if evt == "captured":
            events.append(("payment.captured", f"evt_cap_{random.randint(1000,9999)}"))
        elif evt == "paid":
            events.append(("order.paid", f"evt_paid_{random.randint(1000,9999)}"))
        elif evt == "failed":
            events.append(("payment.failed", f"evt_fail_{random.randint(1000,9999)}"))
        elif evt == "refund":
            events.append(("refund.processed", f"evt_rfnd_{random.randint(1000,9999)}"))

    for seed in range(args.shuffle_seeds):
        random.seed(seed)
        shuffled = list(events)
        random.shuffle(shuffled)

        print(f"[seed={seed}] Sending {len(shuffled)} events...")

        for event_type, event_id in shuffled:
            payload = build_webhook_payload(
                event_id=f"{event_id}_s{seed}",
                event_type=event_type,
                challenge_id=args.challenge_id,
            )
            raw = json.dumps(payload).encode()
            sig = hmac_sha256_hex(webhook_secret, raw)

            try:
                resp = httpx.post(
                    f"{gateway_url}/webhooks/razorpay",
                    content=raw,
                    headers={
                        "X-Razorpay-Signature": sig,
                        "Content-Type": "application/json",
                    },
                    timeout=5.0,
                )
                print(f"  {event_type}: {resp.status_code} → {resp.json()}")
            except Exception as e:
                print(f"  {event_type}: ERROR — {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
