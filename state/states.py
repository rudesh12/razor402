"""state/states.py — State machine definition."""

RANK = {
    "ISSUED": 10,
    "VERIFIED": 20,
    "SETTLING": 25,
    "SETTLEMENT_UNKNOWN": 28,
    "SETTLED": 30,
    "FAILED": 35,
    "FULFILLING": 40,
    "FULFILLED": 50,
    "COMPENSATING": 60,
    "COMPENSATED": 70,
    "DEAD_LETTER": 75,
}

ALLOWED_FROM = {
    "ISSUED":             set(),                                            # row insert
    "VERIFIED":           {"ISSUED"},
    "SETTLING":           {"VERIFIED"},
    "SETTLEMENT_UNKNOWN": {"SETTLING"},                                     # timeout ONLY
    "SETTLED":            {"SETTLING", "SETTLEMENT_UNKNOWN"},
    "FAILED":             {"ISSUED", "VERIFIED", "SETTLING", "SETTLEMENT_UNKNOWN"},
    "FULFILLING":         {"SETTLED"},
    "FULFILLED":          {"FULFILLING"},
    "COMPENSATING":       {"SETTLED", "FULFILLING"},
    "COMPENSATED":        {"COMPENSATING"},
    "DEAD_LETTER":        {"SETTLING", "SETTLEMENT_UNKNOWN", "COMPENSATING", "FULFILLING"},
}

TERMINAL = {"FAILED", "FULFILLED", "COMPENSATED", "DEAD_LETTER"}
