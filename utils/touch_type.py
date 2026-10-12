"""Touch / Non-Touch helpers shared by every page that shows the T / NT badge.

Device.touch_type is chosen on the Final QC form. NULL / blank / anything that is not
an explicit "Touch" means Non-Touch (the default), shown as the badge "NT"."""

TOUCH = "Touch"
NON_TOUCH = "Non-Touch"
TOUCH_VALUES = (TOUCH, NON_TOUCH)


def normalize_touch(value) -> str:
    """Canonical stored value: "Touch" only when explicitly touch, else "Non-Touch"."""
    v = (value or "").strip().lower().replace("_", "-").replace(" ", "-")
    return TOUCH if v in ("touch", "t", "yes", "true") else NON_TOUCH


def touch_abbr(value) -> str:
    return "T" if normalize_touch(value) == TOUCH else "NT"


def touch_badge_html(value) -> str:
    """Small badge placed next to the Tag Number: green "T", grey "NT"."""
    if normalize_touch(value) == TOUCH:
        return '<span class="badge bg-success ms-1" title="Touch screen">T</span>'
    return '<span class="badge bg-secondary ms-1" title="Non-Touch screen">NT</span>'
