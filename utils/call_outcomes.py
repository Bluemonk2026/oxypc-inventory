"""Canonical call outcomes, shared by Dealer Management and Telecalling.

Why this exists: the same outcome reaches the database spelled several ways.
The in-app call form stores underscore keys (`not_interested`, `no_answer`),
while Call Records Bulk Upload stores whatever the sheet said, lower-cased but
with spaces intact (`not interested`, `not connected`, `call back`). Counting
with `call_outcome == 'not_interested'` therefore missed every imported row —
on 2026-07-22 production held 1,051 calls and the KPI cards read almost zero.

Everything that counts or groups outcomes must go through normalize_outcome()
so both spellings land in the same bucket. Storage is left alone; this is a
read-side fix, so it works on history already in the database.
"""

# Canonical key -> display label. Order is the order cards render in.
OUTCOME_LABELS = {
    "interested":       "Interested",
    "not_interested":   "Not Interested",
    "details_sent":     "Detail Sent",
    "callback":         "Callback",
    "not_connected":    "Not Connected",
    "no_requirement":   "No Requirement",
    "language_barrier": "Language Barrier",
    "busy":             "Busy",
    "followup":         "Follow-up",
    "order_placed":     "Order Placed",
}

# Spellings that mean the same thing as a canonical key. Compared after
# lower-casing and turning runs of spaces/hyphens into single underscores, so
# "Not  Connected", "not-connected" and "not_connected" all arrive here alike.
_ALIASES = {
    "no_answer":        "not_connected",   # renamed: the card used to say "No Answer"
    "not_reachable":    "not_connected",
    "call_back":        "callback",
    "callback_request": "callback",
    "detail_sent":      "details_sent",
    "details_shared":   "details_sent",
    "no_requirements":  "no_requirement",
    "follow_up":        "followup",
    "order":            "order_placed",
}


def normalize_outcome(raw) -> str:
    """Fold any stored spelling of a call outcome onto its canonical key.

    Returns "" for null/blank so callers can skip it. An unrecognised value is
    returned in normalised form rather than dropped — a new outcome someone
    adds in Master Data still counts as itself instead of vanishing.
    """
    if not raw:
        return ""
    key = "_".join(str(raw).strip().lower().replace("-", " ").split())
    return _ALIASES.get(key, key)


def interested_total(counts: dict) -> int:
    """The Interested card counts Interested + Detail Sent.

    Sending details is treated as interest expressed — a dealer who asked for
    the catalogue is a live lead, not a dead one. Defined here so Dealer
    Management and Telecalling can never drift on what "Interested" means.
    Dealer Management still shows Detail Sent as its own card as well, so that
    slice is deliberately visible in both places.
    """
    return counts.get("interested", 0) + counts.get("details_sent", 0)


def variants_for(canonical: str) -> list:
    """Every normalised spelling that folds onto `canonical`.

    For filtering in SQL: compare the normalised column against this list
    instead of `== canonical`, or clicking the Not Connected card would return
    nothing for rows stored as "no answer".
    """
    key = normalize_outcome(canonical)
    if not key:
        return []
    return sorted({key} | {alias for alias, target in _ALIASES.items() if target == key})


def normalized_column(col):
    """SQL expression normalising a call_outcome column the same way
    normalize_outcome() does in Python, so the two never drift apart."""
    from sqlalchemy import func
    lowered = func.lower(func.trim(col))
    return func.replace(func.replace(lowered, "-", "_"), " ", "_")


def tally(rows) -> dict:
    """Sum (raw_outcome, count) pairs into {canonical_key: total}."""
    out: dict = {}
    for raw, cnt in rows:
        key = normalize_outcome(raw)
        if key:
            out[key] = out.get(key, 0) + int(cnt or 0)
    return out
