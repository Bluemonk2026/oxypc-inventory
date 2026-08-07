"""Device grade parsing and dropdown options — one implementation, two callers.

Grade reaches the app in two different shapes and both have to land on the same
`DeviceGrade` enum:

  * Master Data holds presentation labels ("Grade A - Like New",
    "Scrap / Parts Only"), which is what admins edit and what the dropdowns show.
  * CSV bulk uploads carry whatever the exporting system wrote ("B", "B Grade",
    "Grade B", "scrap").

`Device.grade` is a real Postgres enum, so an unrecognised string only fails at
the next flush — outside any per-row try/except. Everything that writes a grade
must go through `parse_grade` first.
"""
from __future__ import annotations

import re

from models.device import DeviceGrade
from utils.master_data import master_options

_GRADE_RE = re.compile(r"(?:grade\s*)?([abcde])(?:\s*grade)?\b")


def parse_grade(raw) -> DeviceGrade | None:
    """Normalize a free-text or label-form grade to a DeviceGrade, or None.

    Returns None rather than guessing: an unrecognised value must leave the
    column unchanged, never write a wrong grade that later prices a device.
    """
    if isinstance(raw, DeviceGrade):
        return raw
    v = (raw or "").strip().lower()
    if not v:
        return None
    # Checked before the letter match so a scrap label containing a stray
    # standalone a-e never resolves to a letter grade.
    if "scrap" in v:
        return DeviceGrade.scrap
    m = _GRADE_RE.match(v)
    if m:
        return DeviceGrade(m.group(1).upper())
    return None


# Shown when the 'grade' Master Data category is empty or holds only labels that
# do not resolve — an unconfigured install must still offer every real grade
# rather than an empty dropdown.
_FALLBACK_LABELS = {
    DeviceGrade.A: "A", DeviceGrade.B: "B", DeviceGrade.C: "C",
    DeviceGrade.D: "D", DeviceGrade.E: "E", DeviceGrade.scrap: "Scrap",
}


def grade_options() -> list[tuple[str, str]]:
    """(enum value, display label) pairs for grade dropdowns.

    Labels come from the admin-managed 'Device Grades' Master Data category so
    the wording is editable, but the posted *value* is always the enum code —
    posting the label would blow up on the enum column. Master values that do
    not resolve to a grade are dropped rather than offered as options that would
    fail on submit. Reads the warm master cache, so it is safe in a template.
    """
    seen: dict[str, str] = {}
    for label in master_options("grade"):
        g = parse_grade(label)
        if g and g.value not in seen:
            seen[g.value] = label
    if not seen:
        return [(g.value, lbl) for g, lbl in _FALLBACK_LABELS.items()]
    # Any grade the admin has not given a label for still needs to be
    # selectable, otherwise adding E to the enum would silently hide it.
    for g, lbl in _FALLBACK_LABELS.items():
        seen.setdefault(g.value, lbl)
    order = [g.value for g in _FALLBACK_LABELS]
    return [(v, seen[v]) for v in order if v in seen]
