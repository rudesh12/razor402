"""policy/server_gate.py — Authoritative server-side gate, inside transaction."""
from core.catalog import AGENT_POLICY, POLICY_VERSION, MERCHANT_ACCOUNT
from core.clock import now
from core.errors import Razor402Error


def authorize(conn, cid: str, kid: str, paise: int, pay_to: str,
              now_ts: int | None = None) -> int:
    """
    Authoritative gate called inside the ISSUED → VERIFIED CAS transaction.
    On allow: inserts HELD reservation. Returns reservation id.
    On deny: raises Razor402Error. Zero adapter calls.
    """
    if now_ts is None:
        now_ts = now()

    policy = AGENT_POLICY.get(kid)
    if policy is None:
        raise Razor402Error("AGENT_NOT_ALLOWLISTED", f"Unknown agent: {kid}",
                            challenge_id=cid)

    if pay_to not in policy["allowlist"]:
        raise Razor402Error("MERCHANT_NOT_ALLOWLISTED",
                            f"Merchant {pay_to} not in allowlist", challenge_id=cid)

    if paise > policy["per_call_cap_paise"]:
        raise Razor402Error("PER_CALL_CAP_EXCEEDED",
                            f"{paise} > {policy['per_call_cap_paise']}", challenge_id=cid,
                            extra={"policyVersion": POLICY_VERSION})

    # Compute spent today from budget_reservations (HELD + CAPTURED)
    day_start = now_ts - (now_ts % 86400)
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_paise), 0) as spent FROM budget_reservations "
        "WHERE agent_kid=? AND created_at >= ? AND status IN ('HELD', 'CAPTURED')",
        (kid, day_start)
    ).fetchone()
    spent = row["spent"]

    if spent + paise > policy["daily_pool_paise"]:
        raise Razor402Error("DAILY_POOL_EXHAUSTED",
                            f"{spent}+{paise} > {policy['daily_pool_paise']}",
                            challenge_id=cid,
                            extra={"policyVersion": POLICY_VERSION})

    # Insert HELD reservation in the same transaction
    cursor = conn.execute(
        "INSERT INTO budget_reservations (agent_kid, challenge_id, amount_paise, status, created_at) "
        "VALUES (?, ?, ?, 'HELD', ?)",
        (kid, cid, paise, now_ts)
    )
    return cursor.lastrowid  # type: ignore
