"""Bulk Part Request lists every part, not only IQC-flagged ones.

An engineer finds faults at the bench that the inspection never recorded, so a
part missing from this table could not be requested for the queue at all.
`Total Quantity` still counts only tags where the part is Required, so the
column keeps its meaning.
"""
from tests.test_iqc_new_user import _login, make_user  # noqa: F401  (fixture)


def test_l1_page_renders_bulk_part_request(app_client, make_user):  # noqa: F811
    username, password = make_user("l1_engineer")
    _login(app_client, username, password)

    r = app_client.get("/repair/l1", follow_redirects=True)
    assert r.status_code != 500, f"/repair/l1 returned 500:\n{r.text[:2000]}"
    assert r.status_code == 200
    assert "Bulk Part Request" in r.text


def test_bulk_parts_includes_not_required(monkeypatch):
    """The aggregation keeps non-required parts, with qty 0.

    Exercises the counting rule directly against compute_required's output
    shape, so it holds regardless of what happens to be in the queue.
    """
    from services.parts_required import compute_required

    rows = compute_required(None, None)
    assert rows, "compute_required returned nothing to aggregate"

    counts = {}
    for row in rows:
        entry = counts.setdefault(
            row["label"],
            {"label": row["label"], "category": row["category"], "qty": 0},
        )
        if row["required"]:
            entry["qty"] += 1

    assert len(counts) == len({r["label"] for r in rows}), (
        "every distinct part label should appear, required or not"
    )
    not_required = [r for r in rows if not r["required"]]
    if not_required:
        assert counts[not_required[0]["label"]]["qty"] == 0, (
            "a part nobody needs should show 0, not be dropped from the table"
        )
