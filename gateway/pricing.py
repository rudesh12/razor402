"""gateway/pricing.py — Multi-option accepts[] builder, pass check."""
from core.catalog import CATALOG, PRICE_BASIS_UNIT, PRICE_BASIS_PASS
from core.clock import now


def check_pass(conn, kid: str, item_id: str, now_ts: int | None = None) -> dict | None:
    """
    Check for an active day pass covering this item.
    Returns pass row dict or None.
    """
    if now_ts is None:
        now_ts = now()

    # Check if any pass covers this item
    day_pass = None
    for pid, pdata in CATALOG.items():
        if pdata.get("covers") == item_id:
            day_pass = pdata
            break

    if day_pass is None:
        return None

    row = conn.execute(
        "SELECT id, expires_at, challenge_id FROM passes "
        "WHERE agent_kid=? AND item_id=? AND expires_at > ? "
        "ORDER BY expires_at DESC LIMIT 1",
        (kid, item_id, now_ts)
    ).fetchone()

    if row:
        return dict(row)
    return None


def count_paid_calls_today(conn, kid: str, item_id: str,
                           now_ts: int | None = None) -> int:
    """Count today's paid (non-pass) calls for this item by this agent."""
    if now_ts is None:
        now_ts = now()

    day_start = now_ts - (now_ts % 86400)
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM txn "
        "WHERE agent_kid=? AND item_id=? AND created_at >= ? "
        "AND state IN ('FULFILLED', 'SETTLED', 'FULFILLING', 'SETTLING') "
        "AND price_basis=?",
        (kid, item_id, day_start, PRICE_BASIS_UNIT)
    ).fetchone()
    return row["cnt"] if row else 0


def build_accepts(conn, kid: str, item_id: str,
                  now_ts: int | None = None) -> list[dict]:
    """
    Build the accepts[] array for a 402 challenge.
    Always includes the unit option.
    If day pass threshold met, includes the pass option.
    """
    if now_ts is None:
        now_ts = now()

    item = CATALOG.get(item_id)
    if item is None:
        return []

    accepts = []

    # Unit option
    unit_option = {
        "amountPaise": item["price_paise"],
        "priceBasis": PRICE_BASIS_UNIT,
    }
    accepts.append(unit_option)

    # Check if day pass should be offered
    day_pass = None
    day_pass_id = None
    for pid, pdata in CATALOG.items():
        if pdata.get("covers") == item_id:
            day_pass = pdata
            day_pass_id = pid
            break

    if day_pass:
        paid_calls = count_paid_calls_today(conn, kid, item_id, now_ts)
        threshold = day_pass.get("offer_after_paid_calls", 8)
        if paid_calls >= threshold:
            pass_option = {
                "amountPaise": day_pass["price_paise"],
                "priceBasis": PRICE_BASIS_PASS,
                "itemId": day_pass_id,
                "triggeredBy": f"{paid_calls}_paid_calls_today",
                "breakEvenCalls": day_pass["specs"].get("break_even_calls", 10),
            }
            accepts.append(pass_option)

    return accepts
