"""facilitator/rzp.py — Mode-latching Razorpay payment adapter."""
import os
import hashlib
import time

from core.errors import PaymentFailed
from core.ids import uuid7


class PaymentAdapter:
    """
    Mode-latching payment adapter.
    mode: "live_s2s" | "harness"
    receipt = challenge_id always (durable idempotency key).
    Harness IDs prefixed pay_H / rfnd_H / order_H.
    """

    def __init__(self, mode: str | None = None):
        env_mode = os.environ.get("RZP_MODE", "auto")
        if mode:
            self.mode = mode
        elif env_mode == "live_s2s":
            self.mode = "live_s2s"
        else:
            self.mode = "harness"

        self.call_log: list[tuple[str, dict]] = []
        self._rzp_client = None
        self.fault: str | None = None  # chaos hook: "timeout", "refund_timeout"

        # Harness state
        self._harness_orders: dict[str, dict] = {}
        self._harness_payments: dict[str, dict] = {}
        self._harness_refunds: dict[str, list[dict]] = {}

        if self.mode == "live_s2s":
            self._init_rzp()

    def _init_rzp(self):
        try:
            import razorpay
            key_id = os.environ.get("RAZORPAY_KEY_ID") or os.environ.get("RZP_KEY_ID", "")
            key_secret = os.environ.get("RAZORPAY_KEY_SECRET") or os.environ.get("RZP_KEY_SECRET", "")
            self._rzp_client = razorpay.Client(auth=(key_id, key_secret))
        except Exception:
            import warnings
            warnings.warn("Razorpay client init failed; latching to harness mode")
            self.mode = "harness"

    def create_order(self, cid: str, paise: int) -> dict:
        """Create an order. receipt = challenge_id."""
        self.call_log.append(("create_order", {"cid": cid, "paise": paise}))

        if self.fault == "timeout":
            import httpx
            raise httpx.TimeoutException("Chaos: order timeout")

        if self.mode == "live_s2s" and self._rzp_client:
            try:
                order = self._rzp_client.order.create({
                    "amount": paise,
                    "currency": "INR",
                    "receipt": cid,
                })
                return order
            except Exception as e:
                # Check if it's a duplicate receipt error
                existing = self.find_order(cid)
                if existing:
                    return existing
                raise

        # Harness mode
        # Check for duplicate receipt
        for oid, order in self._harness_orders.items():
            if order.get("receipt") == cid:
                return order

        order_id = f"order_H{hashlib.sha256(cid.encode()).hexdigest()[:12]}"
        order = {
            "id": order_id,
            "amount": paise,
            "currency": "INR",
            "receipt": cid,
            "status": "created",
        }
        self._harness_orders[order_id] = order
        return order

    def find_order(self, cid: str) -> dict | None:
        """Find an order by receipt == challenge_id."""
        self.call_log.append(("find_order", {"cid": cid}))

        if self.mode == "live_s2s" and self._rzp_client:
            try:
                orders = self._rzp_client.order.all({"receipt": cid})
                items = orders.get("items", [])
                return items[0] if items else None
            except Exception:
                return None

        for order in self._harness_orders.values():
            if order.get("receipt") == cid:
                return order
        return None

    def order_payments(self, order_id: str) -> list[dict]:
        """List payments for an order."""
        self.call_log.append(("order_payments", {"order_id": order_id}))

        if self.mode == "live_s2s" and self._rzp_client:
            try:
                return self._rzp_client.order.payments(order_id).get("items", [])
            except Exception:
                return []

        return [p for p in self._harness_payments.values()
                if p.get("order_id") == order_id]

    def debit(self, order: dict, cid: str, vpa: str = "success@razorpay") -> dict:
        """Create a payment against an order."""
        self.call_log.append(("debit", {"order_id": order["id"], "cid": cid, "vpa": vpa}))

        if self.fault == "timeout":
            import httpx
            raise httpx.TimeoutException("Chaos: debit timeout")

        if vpa == "failure@razorpay":
            raise PaymentFailed("Payment declined by bank")

        if self.mode == "live_s2s" and self._rzp_client:
            try:
                result = self._rzp_client.payment.createUpi({
                    "amount": order["amount"],
                    "currency": "INR",
                    "order_id": order["id"],
                    "email": "agent@razor402.dev",
                    "contact": "9999999999",
                    "method": "upi",
                    "upi": {"vpa": vpa},
                })
                return result
            except Exception as e:
                # Latch to harness on S2S capability failure
                if "not supported" in str(e).lower() or "bad request" in str(e).lower():
                    import warnings
                    warnings.warn(f"S2S payment failed ({e}); latching to harness mode")
                    self.mode = "harness"
                else:
                    raise

        # Harness mode
        pay_id = f"pay_H{hashlib.sha256(cid.encode()).hexdigest()[:12]}"
        payment = {
            "id": pay_id,
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": "INR",
            "status": "captured",
            "method": "upi",
            "notes": {"challenge_id": cid},
        }
        self._harness_payments[pay_id] = payment
        order["status"] = "paid"
        return payment

    def list_refunds(self, payment_id: str) -> list[dict]:
        """List refunds for a payment. READ BEFORE WRITE."""
        self.call_log.append(("list_refunds", {"payment_id": payment_id}))

        if self.mode == "live_s2s" and self._rzp_client:
            try:
                return self._rzp_client.payment.refunds(payment_id).get("items", [])
            except Exception:
                return []

        return self._harness_refunds.get(payment_id, [])

    def refund(self, payment_id: str, paise: int, cid: str) -> dict:
        """Issue a refund with idempotency key."""
        self.call_log.append(("refund", {"payment_id": payment_id, "paise": paise, "cid": cid}))

        if self.fault == "refund_timeout":
            import httpx
            raise httpx.TimeoutException("Chaos: refund timeout")

        if self.mode == "live_s2s" and self._rzp_client:
            try:
                return self._rzp_client.payment.refund(payment_id, {
                    "amount": paise,
                    "notes": {"challenge_id": cid},
                })
            except Exception:
                raise

        # Harness mode — check for existing refund (idempotency)
        existing = self._harness_refunds.get(payment_id, [])
        for r in existing:
            if (r.get("notes") or {}).get("challenge_id") == cid:
                return r

        rfnd_id = f"rfnd_H{hashlib.sha256(f'{cid}_refund'.encode()).hexdigest()[:12]}"
        refund_obj = {
            "id": rfnd_id,
            "payment_id": payment_id,
            "amount": paise,
            "currency": "INR",
            "status": "processed",
            "notes": {"challenge_id": cid},
        }
        self._harness_refunds.setdefault(payment_id, []).append(refund_obj)
        return refund_obj
