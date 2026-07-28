from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from database import get_db
from models.user import User, UserRole
from models.settings import AppSetting
from models.role_permissions import (
    set_cached_page_title, _PAGE_TITLE_CACHE,
    set_cached_breadcrumb_enabled, _BREADCRUMB_CACHE,
)
from auth.dependencies import get_current_user, require_roles, verify_csrf
from templates_config import templates

router = APIRouter(
    prefix="/admin/landing-pages",
    tags=["landing_pages"],
    dependencies=[Depends(verify_csrf)],
)
admin_only = require_roles(UserRole.admin)

SETTING_PREFIX = "page_title_"


async def load_page_titles_to_cache(db: AsyncSession) -> None:
    """Populate the in-memory page-title cache from AppSetting rows.
    Called at app startup and after every save/reset."""
    rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.like(f"{SETTING_PREFIX}%"))
    )).scalars().all()
    _PAGE_TITLE_CACHE.clear()
    for r in rows:
        module_key = r.key[len(SETTING_PREFIX):]
        if r.value:
            _PAGE_TITLE_CACHE[module_key] = r.value


BREADCRUMB_PREFIX = "breadcrumb_"


async def load_breadcrumb_settings_to_cache(db: AsyncSession) -> None:
    """Populate the in-memory breadcrumb-toggle cache from AppSetting rows.
    Called at app startup and after every toggle. Missing rows default to
    enabled (True) via get_cached_breadcrumb_enabled()."""
    rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.like(f"{BREADCRUMB_PREFIX}%"))
    )).scalars().all()
    _BREADCRUMB_CACHE.clear()
    for r in rows:
        module_key = r.key[len(BREADCRUMB_PREFIX):]
        _BREADCRUMB_CACHE[module_key] = (r.value == "1")

# (module_key, nav_label, default_page_title, route_url)
NAV_PAGE_TITLES = [
    ("dashboard",            "Admin Dashboard",               "Admin Dashboard",               "/dashboard"),
    ("dispatch",             "TRC Dashboard",                 "TRC Dashboard",                 "/dispatch"),
    ("inventory_requests",   "Inventory Request",             "Inventory Request",             "/inventory-requests"),
    ("model_requested",      "Model Requested",               "Model Requested",               "/model-requested"),
    ("devices",              "Inventory Search",              "Inventory Search",              "/devices"),
    ("attendance",           "My Attendance",                 "My Attendance",                 "/attendance"),
    ("attendance_report",    "Attendance Report",             "Attendance Report",             "/attendance/report"),
    ("grn",                  "GRN with Invoice",              "GRN with Invoice",              "/grn"),
    ("lots",                 "Lot Overview",                  "Lot Overview",                  "/lots"),
    ("iqc",                  "IQC Line Items",                "IQC Line Items",                "/iqc"),
    ("grn_post_iqc",         "GRN post IQC",                  "GRN post IQC",                  "/grn/post-iqc"),
    ("grn_records",          "GRN Records",                   "GRN Records",                   "/grn/records"),
    ("stock",                "Stock Inwards",                 "Stock Inwards",                 "/stock"),
    ("production_manager",   "Production Manager",            "Production Manager",            "/trc-production"),
    ("scrap_products",       "Scrap Products",                "Scrap Products",                "/scrap-products"),
    ("transfers",            "Move Device",                   "Move Device",                   "/transfers"),
    ("repair_l1",            "L1 Repair",                     "L1 Repair",                     "/repair/l1"),
    ("repair_l2",            "L2 Repair",                     "L2 Repair",                     "/repair/l2"),
    ("repair_l3",            "L3 Repair",                     "L3 Repair",                     "/repair/l3"),
    ("qc_check",             "Stress Test",                   "Stress Test",                   "/qc"),
    ("cosmetic",             "Cosmetic & Paint",              "Cosmetic & Paint",              "/cosmetic/cleaning"),
    ("cosmetic_finalqc",     "Final QC",                      "Final QC",                      "/cosmetic/final_qc"),
    ("workid_status",        "WorkID Status",                 "WorkID Status",                 "/workid-status"),
    ("spare_parts",          "Parts Dashboard",               "Parts Dashboard",               "/spare-parts"),
    ("spare_parts_purchase", "Parts Purchased",               "Parts Purchased",               "/spare-parts/purchase"),
    ("parts_tracking",       "Parts Tracking",                "Parts Tracking",                "/ram-tracking"),
    ("parts_consumption",    "Parts Consumption",             "Parts Consumption",             "/spare-parts/consume"),
    ("crm_dashboard",        "CRM Dashboard",                 "CRM Dashboard",                 "/crm/"),
    ("crm_contacts",         "Contact Leads",                 "Contact Leads",                 "/crm/contacts"),
    ("crm_sourcing",         "Sourcing Deals",                "Sourcing Deals",                "/crm/sourcing"),
    ("crm_sales_opp",        "Sales Opportunities",           "Sales Opportunities",           "/crm/sales"),
    ("crm_price_matrix",     "Price Matrix",                  "Price Matrix",                  "/crm/price-matrix"),
    ("crm_purchase_orders",  "Purchase Orders",               "Purchase Orders",               "/crm/purchase-orders"),
    ("crm_analytics",        "CRM Analytics",                 "CRM Analytics",                 "/crm/reports"),
    ("crm_assign_leads",     "Assign Social Leads",           "Assign Social Leads",           "/crm/assign-social-leads"),
    ("telesales_dashboard",  "TeleSales Dashboard",           "TeleSales Dashboard",           "/telesales-dashboard"),
    ("sales",                "Ready to Sale / Sales List",    "Ready to Sale",                 "/sales/ready"),
    ("gate_pass",            "Gate Pass",                     "Gate Pass",                     "/gate-pass"),
    ("returns",              "Returns",                       "Process Return",                "/returns"),
    ("dealers",              "Dealers",                       "Dealers",                       "/dealers"),
    ("telecalling",          "Telecalling",                   "Telecalling",                   "/telecalling"),
    ("quotations",           "Quotations",                    "Quotations",                    "/quotations"),
    ("model_requests",       "Model Requests",                "Model Requests",                "/model-requests"),
    ("whatsapp",             "WhatsApp",                      "WhatsApp",                      "/whatsapp"),
    ("assign_dealer_leads",  "Assign Dealer Leads",           "Assign Dealer Leads",           "/assign-dealer-leads"),
    ("finance",              "Accounts",                      "Accounts",                      "/accounts"),
    ("finance_supplier",     "Supplier Payments",             "Supplier Payments",             "/accounts/supplier-payments"),
    ("finance_customer",     "Customer Receipts",             "Customer Receipts",             "/accounts/customer-receipts"),
    ("locations",            "Location Map",                  "Location Map",                  "/locations/dashboard"),
    ("location_gaps",        "Gap Alerts",                    "Gap Alerts",                    "/locations/gaps"),
    ("location_audit",       "Physical Audit",                "Physical Audit",                "/locations/audit"),
    ("location_master",      "Manage Locations",              "Manage Locations",              "/locations/master"),
    ("location_trash",       "Trash",                         "Trash",                         "/trash"),
    ("reports",              "Lot P&L",                       "Lot P&L",                       "/reports/lot-pl"),
    ("report_sales",         "Sales Report",                  "Sales Report",                  "/reports/sales"),
    ("report_stage",         "Stage Log",                     "Stage Log",                     "/reports/stage-movement"),
    ("report_bizpl",         "Business P&L",                  "Business P&L",                  "/reports/business-pl"),
    ("report_aging",         "Stock Aging",                   "Stock Aging",                   "/reports/stock-aging"),
    ("report_overdue",       "Overdue Devices",               "Overdue Devices",               "/reports/overdue"),
    ("report_receivables",   "Receivables",                   "Receivables",                   "/reports/receivables"),
    ("market",               "Market Intel",                  "Market Intel",                  "/market"),
    # ── ADMIN (admin-only) ─────────────────────────────────────────────────
    ("qa",                   "QA Dashboard",                  "QA Dashboard",                  "/qa/"),
    ("manuals",              "Manuals",                       "Manuals",                       "/manuals/"),
    # ── APPLICATION SETTINGS (admin-only by default; grantable via matrix) ─
    ("move_device_internal", "Move Device Internal",          "Move Device Internal",          "/repair/move/form"),
    ("stage_control",        "Stage Control",                 "Stage Control",                 "/stage-control"),
    ("aging_tracker",        "Aging Tracker",                 "Aging Tracker",                 "/stage-control/aging"),
    ("stage_audit_log",      "Stage Audit Log",               "Stage Audit Log",               "/stage-control/audit"),
    ("system_audit_log",     "System Audit Log",              "System Audit Log",              "/admin/audit-log"),
    ("sidebar_config",       "Sidebar Config",                "Sidebar Config",                "/admin/sidebar-config"),
    ("landing_pages",        "Landing Pages",                 "Landing Pages",                 "/admin/landing-pages"),
    ("wa_audit_log",         "WA Audit Log",                  "WA Audit Log",                  "/whatsapp/audit"),
    # ── ADMIN SETTINGS accordion (admin-only by default; grantable to
    #    sub_admin — or any role — via the Module Permissions matrix) ────────
    ("admin_users",          "Users",                         "Users",                         "/admin/users"),
    ("admin_master",         "Master Data",                   "Master Data",                   "/admin/master"),
    ("company_settings",     "Company Settings",              "Company Settings",              "/admin/company-settings"),
    ("attendance_config",    "Attendance Config",             "Attendance Config",             "/admin/attendance-config"),
    ("terms_conditions",     "Terms & Conditions",             "Terms & Conditions",            "/admin/terms-conditions"),
]


@router.get("/", response_class=HTMLResponse)
async def landing_pages_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.like("page_title_%"))
    )).scalars().all()
    custom_titles = {r.key[len("page_title_"):]: r.value for r in rows}

    bc_rows = (await db.execute(
        select(AppSetting).where(AppSetting.key.like(f"{BREADCRUMB_PREFIX}%"))
    )).scalars().all()
    breadcrumb_overrides = {r.key[len(BREADCRUMB_PREFIX):]: (r.value == "1") for r in bc_rows}

    modules = [
        {
            "key": mod_key,
            "nav_label": nav_label,
            "default_title": default_title,
            "current_title": custom_titles.get(mod_key, default_title),
            "is_custom": mod_key in custom_titles,
            "url": url,
            "breadcrumb_enabled": breadcrumb_overrides.get(mod_key, True),
        }
        for mod_key, nav_label, default_title, url in NAV_PAGE_TITLES
    ]

    return templates.TemplateResponse("admin/landing_pages.html", {
        "request": request,
        "current_user": current_user,
        "modules": modules,
        "success": request.query_params.get("success"),
        "error": request.query_params.get("error"),
    })


@router.post("/save")
async def save_landing_page_title(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    form = await request.form()
    module_key = (form.get("module_key") or "").strip()
    new_title = (form.get("page_title") or "").strip()

    if not module_key or not new_title:
        return RedirectResponse(
            url="/admin/landing-pages/?error=Module+key+and+title+are+required",
            status_code=302,
        )

    setting_key = f"page_title_{module_key}"
    existing = (await db.execute(
        select(AppSetting).where(AppSetting.key == setting_key)
    )).scalar_one_or_none()

    if existing:
        existing.value = new_title
        existing.updated_by = current_user.username
    else:
        db.add(AppSetting(
            key=setting_key,
            value=new_title,
            description=f"Custom page title for {module_key}",
            updated_by=current_user.username,
        ))

    await db.commit()
    set_cached_page_title(module_key, new_title)
    return RedirectResponse(
        url=f"/admin/landing-pages/?success=Title+saved+for+{module_key}",
        status_code=302,
    )


@router.post("/reset")
async def reset_landing_page_title(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    form = await request.form()
    module_key = (form.get("module_key") or "").strip()

    if not module_key:
        return RedirectResponse(url="/admin/landing-pages/?error=Module+key+required", status_code=302)

    setting_key = f"page_title_{module_key}"
    existing = (await db.execute(
        select(AppSetting).where(AppSetting.key == setting_key)
    )).scalar_one_or_none()

    if existing:
        await db.execute(delete(AppSetting).where(AppSetting.key == setting_key))
        await db.commit()
        _PAGE_TITLE_CACHE.pop(module_key, None)

    return RedirectResponse(
        url=f"/admin/landing-pages/?success=Title+reset+to+default+for+{module_key}",
        status_code=302,
    )


@router.post("/toggle-breadcrumb")
async def toggle_breadcrumb(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """AJAX toggle: enable/disable the breadcrumb trail for one page."""
    from fastapi.responses import JSONResponse

    form = await request.form()
    module_key = (form.get("module_key") or "").strip()
    enabled = (form.get("enabled") or "").strip() == "1"

    if not module_key:
        return JSONResponse({"error": "module_key required"}, status_code=400)

    setting_key = f"{BREADCRUMB_PREFIX}{module_key}"
    existing = (await db.execute(
        select(AppSetting).where(AppSetting.key == setting_key)
    )).scalar_one_or_none()

    value = "1" if enabled else "0"
    if existing:
        existing.value = value
        existing.updated_by = current_user.username
    else:
        db.add(AppSetting(
            key=setting_key,
            value=value,
            description=f"Breadcrumb enabled for {module_key}",
            updated_by=current_user.username,
        ))

    await db.commit()
    set_cached_breadcrumb_enabled(module_key, enabled)
    return JSONResponse({"success": True, "module_key": module_key, "enabled": enabled})
