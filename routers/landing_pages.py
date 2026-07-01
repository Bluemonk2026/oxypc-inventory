from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from database import get_db
from models.user import User, UserRole
from models.settings import AppSetting
from auth.dependencies import get_current_user, require_roles, verify_csrf
from templates_config import templates

router = APIRouter(
    prefix="/admin/landing-pages",
    tags=["landing_pages"],
    dependencies=[Depends(verify_csrf)],
)
admin_only = require_roles(UserRole.admin)

# (module_key, nav_label, default_page_title, route_url)
NAV_PAGE_TITLES = [
    ("dashboard",            "Admin Dashboard",               "Admin Dashboard",               "/dashboard"),
    ("dispatch",             "TRC Dashboard",                 "TRC Dashboard",                 "/dispatch"),
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
    ("cosmetic",             "Cosmetic Stages",               "Cosmetic Stages",               "/cosmetic/cleaning"),
    ("cosmetic_finalqc",     "Final QC",                      "Final QC",                      "/cosmetic/final_qc"),
    ("workid_status",        "WorkID Status",                 "WorkID Status",                 "/workid-status"),
    ("spare_parts",          "Parts Dashboard",               "Parts Dashboard",               "/spare-parts"),
    ("spare_parts_purchase", "Parts Purchased",               "Parts Purchased",               "/spare-parts/purchase"),
    ("parts_tracking",       "Parts Tracking",                "Parts Tracking",                "/ram-tracking"),
    ("parts_consumption",    "Parts Consumption",             "Parts Consumption",             "/spare-parts/consume"),
    ("crm_contacts",         "CRM Dashboard & Contact Leads", "CRM Dashboard",                 "/crm/"),
    ("crm_sourcing",         "Sourcing Deals",                "Sourcing Deals",                "/crm/sourcing"),
    ("crm_sales_opp",        "Sales Opportunities",           "Sales Opportunities",           "/crm/sales"),
    ("crm_price_matrix",     "Price Matrix",                  "Price Matrix",                  "/crm/price-matrix"),
    ("crm_purchase_orders",  "Purchase Orders",               "Purchase Orders",               "/crm/purchase-orders"),
    ("crm_analytics",        "CRM Analytics",                 "CRM Analytics",                 "/crm/reports"),
    ("crm_assign_leads",     "Assign Social Leads",           "Assign Social Leads",           "/crm/assign-leads"),
    ("telesales_dashboard",  "TeleSales Dashboard",           "TeleSales Dashboard",           "/telesales-dashboard"),
    ("sales",                "Ready to Sale / Sales List",    "Ready to Sale",                 "/sales/ready"),
    ("returns",              "Returns",                       "Process Return",                "/returns"),
    ("dealers",              "Dealers",                       "Dealers",                       "/dealers"),
    ("telecalling",          "Telecalling",                   "Telecalling",                   "/telecalling"),
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

    modules = [
        {
            "key": mod_key,
            "nav_label": nav_label,
            "default_title": default_title,
            "current_title": custom_titles.get(mod_key, default_title),
            "is_custom": mod_key in custom_titles,
            "url": url,
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

    return RedirectResponse(
        url=f"/admin/landing-pages/?success=Title+reset+to+default+for+{module_key}",
        status_code=302,
    )
