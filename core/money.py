"""core/money.py — Paise type and display formatting."""

Paise = int


def rupees(p: Paise) -> str:
    """Format paise as rupees for display. Only at render boundaries."""
    sign = "-" if p < 0 else ""
    abs_p = abs(p)
    r = abs_p // 100
    remainder = abs_p % 100
    return f"{sign}₹{r}.{remainder:02d}"
