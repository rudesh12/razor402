"""agent/wallet.py — Agent keypair, mandate token, local budget tracking."""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from core.catalog import AGENT_POLICY
from core.money import rupees


class AgentWallet:
    """Client-side budget tracking and key management."""

    def __init__(self, kid: str, sk_hex: str):
        self.kid = kid
        self.sk = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sk_hex))
        self.pk = self.sk.public_key()

        policy = AGENT_POLICY.get(kid, {})
        self.per_call_cap_paise = policy.get("per_call_cap_paise", 0)
        self.daily_pool_paise = policy.get("daily_pool_paise", 0)
        self.mandate_token = policy.get("mandate_token", "")
        self.allowlist = policy.get("allowlist", [])

        self.held_paise = 0
        self.captured_paise = 0

    def remaining_paise(self) -> int:
        return self.daily_pool_paise - self.held_paise - self.captured_paise

    def hold(self, paise: int) -> bool:
        if self.held_paise + self.captured_paise + paise > self.daily_pool_paise:
            return False
        self.held_paise += paise
        return True

    def capture(self, paise: int):
        self.held_paise -= paise
        self.captured_paise += paise

    def release(self, paise: int):
        self.held_paise = max(0, self.held_paise - paise)

    def summary(self) -> dict:
        return {
            "kid": self.kid,
            "remaining_paise": self.remaining_paise(),
            "held_paise": self.held_paise,
            "captured_paise": self.captured_paise,
            "daily_pool_paise": self.daily_pool_paise,
            "per_call_cap_paise": self.per_call_cap_paise,
            "remaining_display": rupees(self.remaining_paise()),
        }
