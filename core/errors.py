"""core/errors.py — Error code registry with HTTP status mapping."""

# Error code → HTTP status
ERROR_STATUS = {
    "PAYMENT_REQUIRED": 402,
    "AGENT_NOT_ALLOWLISTED": 403,
    "AGENT_SIGNATURE_INVALID": 403,
    "CHALLENGE_SIGNATURE_INVALID": 403,
    "CHALLENGE_EXPIRED": 403,
    "RESOURCE_HASH_MISMATCH": 403,
    "AGENT_KID_MISMATCH": 403,
    "MERCHANT_NOT_ALLOWLISTED": 403,
    "ASSET_UNSUPPORTED": 403,
    "PER_CALL_CAP_EXCEEDED": 403,
    "DAILY_POOL_EXHAUSTED": 403,
    "MANDATE_ALLOWANCE_EXHAUSTED": 402,
    "IDEMPOTENCY_KEY_REUSE": 409,
    "IN_FLIGHT": 409,
    "STATE_CONFLICT": 409,
    "PAYMENT_FAILED": 402,
    "SETTLEMENT_IN_DOUBT": 202,
    "UPSTREAM_FULFILMENT_FAILED": 502,
    "WEBHOOK_BAD_SIGNATURE": 401,
}


class Razor402Error(Exception):
    """Base error for the Razor402 system."""
    def __init__(self, code: str, detail: str = "", challenge_id: str | None = None,
                 audit_seq: int | None = None, extra: dict | None = None):
        self.code = code
        self.detail = detail
        self.challenge_id = challenge_id
        self.audit_seq = audit_seq
        self.status = ERROR_STATUS.get(code, 500)
        self.extra = extra or {}
        super().__init__(f"{code}: {detail}")

    def to_dict(self) -> dict:
        d = {"error": self.code, "detail": self.detail}
        if self.challenge_id:
            d["challengeId"] = self.challenge_id
        if self.audit_seq is not None:
            d["auditSeq"] = self.audit_seq
        d.update(self.extra)
        return d


class PaymentFailed(Exception):
    """Raised when Razorpay declines a payment."""
    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(detail)
