"""Daily Report: the Daily Stock exports saved automatically every day at 9 PM."""
import asyncio
import types
from datetime import date, datetime

import pytest

import services.daily_stock_reports as dr


@pytest.fixture()
def reports_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(dr, "REPORTS_DIR", tmp_path / "daily_stock_reports")
    return dr.REPORTS_DIR


def _save(day: str, kinds=("overall", "tags", "location")):
    for k in kinds:
        dr._write_atomic(dr.REPORTS_DIR / day / dr.KIND_FILES[k], f"{k},{day}\n")


# ── 9 PM schedule ────────────────────────────────────────────────────────────
def test_today_is_due_only_from_9pm_and_last_two_days_are_catch_up():
    before = datetime(2026, 10, 7, 20, 59)
    after = datetime(2026, 10, 7, 21, 0)
    assert dr.days_due(before) == [date(2026, 10, 6), date(2026, 10, 5)]
    assert dr.days_due(after) == [date(2026, 10, 7), date(2026, 10, 6), date(2026, 10, 5)]


def test_nothing_is_due_before_the_first_report_date():
    assert dr.days_due(datetime(2026, 9, 1, 22, 0)) == [date(2026, 9, 1)]
    assert dr.days_due(datetime(2026, 8, 31, 22, 0)) == []


def test_generate_missing_builds_only_what_is_not_saved(reports_dir, monkeypatch):
    _save("2026-10-06")                                        # already there
    built = []

    async def fake_generate(db, day):
        built.append(day.isoformat())
        _save(day.isoformat())

    class _Sess:
        async def __aenter__(self): return object()
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(dr, "generate_report", fake_generate)
    monkeypatch.setitem(__import__("sys").modules, "database",
                        types.SimpleNamespace(AsyncSessionLocal=lambda: _Sess()))
    done = asyncio.run(dr.generate_missing(datetime(2026, 10, 7, 21, 5)))
    assert sorted(done) == ["2026-10-05", "2026-10-07"] and sorted(built) == ["2026-10-05", "2026-10-07"]
    # a second check does nothing: every due day is now complete
    assert asyncio.run(dr.generate_missing(datetime(2026, 10, 7, 21, 6))) == []


def test_generate_report_saves_all_three_files(reports_dir, monkeypatch):
    import routers.reports as rp

    async def mk(db, day, ex, ent):
        return f"{day.isoformat()}\n"

    for name in ("build_overall_csv", "build_tags_csv", "build_location_csv"):
        monkeypatch.setattr(rp, name, mk)
    asyncio.run(dr.generate_report(object(), date(2026, 10, 6)))
    for kind in ("overall", "tags", "location"):
        assert dr.report_file("2026-10-06", kind).read_text() == "2026-10-06\n"


# ── listing, safety ──────────────────────────────────────────────────────────
def test_list_is_newest_first_and_skips_incomplete_days(reports_dir):
    _save("2026-10-05")
    _save("2026-10-07")
    _save("2026-10-06", kinds=("overall", "tags"))             # location missing -> not listed
    (reports_dir / "not-a-date").mkdir(parents=True)
    rows = dr.list_reports()
    assert [r["date"] for r in rows] == ["2026-10-07", "2026-10-05"]
    assert rows[0]["label"] == "07-Oct-2026"


def test_report_file_rejects_bad_dates_kinds_and_traversal(reports_dir):
    _save("2026-10-06")
    assert dr.report_file("2026-10-06", "overall") is not None
    assert dr.report_file("2026-10-06", "secrets") is None
    assert dr.report_file("../../etc", "overall") is None
    assert dr.report_file("2026-10-06/../2026-10-05", "overall") is None
    assert dr.report_file("2026-10-09", "overall") is None     # no such report


# ── wiring ───────────────────────────────────────────────────────────────────
def test_page_has_daily_report_table_below_daily_stock_with_global_table(monkeypatch):
    from templates_config import templates
    from models.user import UserRole
    monkeypatch.setitem(templates.env.globals, "master_options", lambda cat: [])
    user = types.SimpleNamespace(username="admin", role=UserRole.admin, full_name="Admin", is_active=True, id=1)
    html = templates.env.get_template("reports/daily_stock.html").render({
        "request": types.SimpleNamespace(url=types.SimpleNamespace(path="/reports/daily-stock"),
                                         query_params={}, session={}, cookies={}),
        "current_user": user, "selected_date": "2026-10-06", "exclude_admin": False, "selected_entity": "",
        "entity_options": [], "rows": [], "total_open": 0, "total_close": 0, "total_net": 0,
        "sold_today": 0, "is_today": False,
        "daily_reports": [{"date": "2026-10-06", "label": "06-Oct-2026"}, {"date": "2026-10-05", "label": "05-Oct-2026"}],
    })
    assert html.index("Stock on 2026-10-06") < html.index('id="dailyReportTable"')       # below the stock table
    for col in ("Report Date", "Overall", "Tag Based", "Location Based"):
        assert f"<th>{col}</th>" in html
    assert 'data-order="2026-10-06"' in html                                              # chronological sort key
    assert "/reports/daily-stock/report/2026-10-06/tags" in html
    assert "initGlobalTable('#dailyReportTable', { order: [[0, 'desc']] })" in html      # latest first


def test_scheduler_started_from_startup_and_download_route_registered():
    import inspect
    import main
    assert "daily_stock_reports" in inspect.getsource(main.startup_event)
    routes = [(r.path, set(r.methods)) for r in main.app.routes if hasattr(r, "methods")]
    assert any(p == "/reports/daily-stock/report/{report_date}/{kind}" and "GET" in m for p, m in routes)
