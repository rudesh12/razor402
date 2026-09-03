"""policy/guardrails.py — Pure advisory function, zero I/O, zero clock reads."""
from dataclasses import dataclass

from core.catalog import AGENT_POLICY, POLICY_VERSION


@dataclass
class Verdict:
    allowed: bool
    code: str
    detail: str
    policy_version: str


def evaluate(agent_kid: str, item_id: str, price_paise: int, pay_to: str,
             spent_today_paise: int, per_call_cap_paise: int,
             daily_pool_paise: int, now_ts: int,
             llm_hint: str | None = None) -> Verdict:
    """
    Pure advisory function. Zero I/O, zero clock reads (now_ts injected).
    llm_hint is accepted and deliberately unused.
    """
    policy = AGENT_POLICY.get(agent_kid)
    if policy is None:
        return Verdict(False, "AGENT_NOT_ALLOWLISTED",
                       f"Unknown agent: {agent_kid}", POLICY_VERSION)

    if pay_to not in policy["allowlist"]:
        return Verdict(False, "MERCHANT_NOT_ALLOWLISTED",
                       f"Merchant {pay_to} not in allowlist", POLICY_VERSION)

    if price_paise > policy["per_call_cap_paise"]:
        return Verdict(False, "PER_CALL_CAP_EXCEEDED",
                       f"{price_paise} > {policy['per_call_cap_paise']}", POLICY_VERSION)

    if spent_today_paise + price_paise > policy["daily_pool_paise"]:
        return Verdict(False, "DAILY_POOL_EXHAUSTED",
                       f"{spent_today_paise}+{price_paise} > {policy['daily_pool_paise']}",
                       POLICY_VERSION)

    return Verdict(True, "POLICY_ALLOW", "", POLICY_VERSION)
