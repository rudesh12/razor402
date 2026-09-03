"""
Capability probe — detects Razorpay API mode.
Writes the outcome to DECISIONS.md. Always exits 0.
"""
import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def append_decision(text: str):
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "DECISIONS.md")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n## D1 — Payment Mode (probed {datetime.now().isoformat()})\n\n")
        f.write(text + "\n")


def main():
    key_id = os.environ.get("RZP_KEY_ID", "")
    key_secret = os.environ.get("RZP_KEY_SECRET", "")

    if not key_id or not key_secret or key_id == "rzp_test_xxxxxxxxxxxx":
        print("MODE_C — offline (no Razorpay keys configured)")
        print("  The build will use the harness adapter (simulated payments).")
        print("  All payment IDs will be prefixed pay_H / rfnd_H / order_H.")
        append_decision(
            "Mode: `MODE_C` (harness) — no Razorpay keys configured.\n"
            "All payments simulated with harness adapter. "
            "IDs prefixed `pay_H` / `rfnd_H` / `order_H`."
        )
        return

    try:
        import razorpay
        client = razorpay.Client(auth=(key_id, key_secret))

        # Step 1: Create a real order
        order = client.order.create({
            "amount": 200,
            "currency": "INR",
            "receipt": "probe-001",
        })
        order_id = order["id"]
        print(f"orders: REAL ✓ {order_id}")

        # Step 2: Attempt server-to-server payment
        try:
            pay = client.payment.createUpi({
                "amount": 200,
                "currency": "INR",
                "order_id": order_id,
                "email": "probe@razor402.dev",
                "contact": "9999999999",
                "method": "upi",
                "upi": {"vpa": "success@razorpay"},
            })
            pay_id = pay.get("razorpay_payment_id") or pay.get("id")
            print(f"s2s payment: REAL ✓ {pay_id}")
            print("MODE_A — full server-to-server")

            # Refund it
            try:
                client.payment.refund(pay_id, {"amount": 200})
                print("refund: REAL ✓")
            except Exception as e:
                print(f"refund probe: {e}")

            append_decision(
                f"Mode: `MODE_A` (live_s2s) — full server-to-server payments work.\n"
                f"Order: `{order_id}`, Payment: `{pay_id}`.\n"
                f"Recommendation: set `RZP_MODE=live_s2s` in .env."
            )
            return

        except Exception as e:
            error_msg = str(e)
            print(f"s2s payment: FAILED — {error_msg}")
            print("MODE_C (harness) — server-to-server not available on this account")
            print()
            print("MODE_B instructions: create one payment via Razorpay Checkout,")
            print("save the pay_ id to agent/fixtures/real_payment.json")

            append_decision(
                f"Mode: `MODE_C` (harness) — orders are real, s2s payments unavailable.\n"
                f"Error: `{error_msg}`\n"
                f"Order creation works (tested: `{order_id}`).\n"
                f"MODE_B alternative: save a Checkout-created `pay_` id to "
                f"`agent/fixtures/real_payment.json`."
            )
            return

    except ImportError:
        print("MODE_C — razorpay package not installed")
        append_decision("Mode: `MODE_C` — razorpay package not available.")
    except Exception as e:
        print(f"MODE_C — offline ({e})")
        append_decision(f"Mode: `MODE_C` — network/auth error: `{e}`")


if __name__ == "__main__":
    main()
