"""Sprint 20 unit tests — Navigation UX: barcode scan, outstanding badge, role tabs, follow-ups."""


def test_repair_list_has_barcode_scan_input():
    import glob
    templates = (
        glob.glob("templates/repair/l*.html")
        + glob.glob("templates/iqc/list.html")
        + glob.glob("templates/sales/list.html")
    )
    found_any = False
    for t in templates:
        src = open(t, encoding="utf-8", errors="ignore").read()
        if "barcodeScan" in src or ("barcode" in src.lower() and "scan" in src.lower()):
            found_any = True
            break
    assert found_any, "No repair/IQC/sales template has a barcode scan quick-search input"


def test_dealer_list_shows_outstanding_badge():
    t = "templates/dealers/list.html"
    src = open(t, encoding="utf-8").read()
    assert "outstanding" in src.lower(), f"{t} does not show outstanding amount for each dealer row"


def test_dashboard_has_role_tab_panels():
    src = open("templates/dashboard.html", encoding="utf-8").read()
    assert "nav-tabs" in src or "tab-pane" in src, \
        "dashboard.html does not have role-based tab panels"


def test_dashboard_router_passes_followups():
    src = open("routers/dashboard.py", encoding="utf-8").read()
    assert "followup" in src or "follow_up" in src, \
        "dashboard.py does not compute today's follow-ups"
