import csv
import io
from templates_config import templates
from fastapi import APIRouter, Depends, Form, Request, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from database import get_db
from models.user import User, UserRole
from models.master import MasterData
from models.role_permissions import (
    RoleModulePermission, CustomRole,
    get_cached_perms, set_cached_perms, _PERM_CACHE,
)
from auth.dependencies import get_current_user, require_roles, verify_csrf

router = APIRouter(prefix="/admin/master", tags=["master"], dependencies=[Depends(verify_csrf)])
admin_only = require_roles(UserRole.admin)

# ── Accordion groupings for Tab 1 (Dropdown Configuration) ──────────────────
ACCORDION_SECTIONS = [
    {
        "id": "device", "label": "Device & Laptop", "icon": "bi-laptop",
        "cat_keys": [
            "brand", "sub_category", "device_type", "processor_brand", "processor_series",
            "generation", "storage_type", "ram_type", "screen_size", "grade",
            "battery_health", "os_version", "color", "port_type", "cosmetic_issue", "cosmetic_grade",
        ],
    },
    {
        "id": "repair", "label": "Repair & QC", "icon": "bi-tools",
        "cat_keys": [
            "l1_issue", "l2_issue", "l3_issue", "repair_issue",
            "repair_resolution", "part_category", "qc_check_item",
        ],
    },
    {
        "id": "inventory", "label": "Inventory & Logistics", "icon": "bi-box-seam",
        "cat_keys": ["floor", "warehouse", "supplier", "data_destruction_method"],
    },
    {
        "id": "sales", "label": "Sales & Returns", "icon": "bi-receipt",
        "cat_keys": ["payment_mode", "return_reason", "condition_on_return"],
    },
]

# ── Module list for Tab 2 (Permission Matrix) ─────────────────────────────────
# Keys MUST match the has_perm(role, '<key>', ...) checks used in templates/base.html
# so that enabling/disabling here actually shows/hides the nav item.
PERM_MODULES = [
    ("dashboard",       "Dashboard"),
    ("devices",         "Inventory Search"),
    ("attendance",      "Attendance"),
    # INTAKE
    ("grn",             "GRN Generation"),
    ("lots",            "Lot Items"),
    ("iqc",             "IQC"),
    # INVENTORY
    ("stock",           "Stock Inwards"),
    ("transfers",       "Stock Transfers"),
    ("move_device",     "Move Device Internal"),
    ("dispatch",        "Ready to Dispatch"),
    # REPAIR
    ("repair_l1",       "L1 Repair"),
    ("repair_l2",       "L2 Repair"),
    ("repair_l3",       "L3 Repair"),
    ("qc_check",        "QC Check"),
    # COSMETIC
    ("cosmetic",        "Cosmetic Refurb"),
    # PARTS
    ("spare_parts",     "Spare Parts"),
    # CRM
    ("crm_contacts",    "CRM Contacts"),
    ("crm_sourcing",    "CRM Sourcing"),
    ("crm_sales_opp",   "CRM Sales Opportunities"),
    # SALES & CRM
    ("sales",           "Sales / Ready to Sale"),
    ("returns",         "Returns"),
    ("dealers",         "Dealers"),
    ("telecalling",     "Telecalling"),
    ("whatsapp",        "WhatsApp"),
    # FINANCE / LOCATIONS / REPORTS
    ("finance",         "Finance"),
    ("locations",       "Inventory Locations"),
    ("reports",         "Reports"),
]

PERM_ACTIONS = [
    ("can_enable", "Enable"),
    ("can_add",    "Add"),
    ("can_edit",   "Edit"),
    ("can_upload", "Upload"),
]

CATEGORIES = [
    # ── Device Identity ───────────────────────────────────────────
    ("brand",               "Device Brands",                "laptop"),
    ("sub_category",        "Device Sub-Categories",        "laptop"),
    ("device_type",         "Device Form Factors",          "laptop"),
    ("processor_brand",     "Processor Brands",             "laptop"),
    ("processor_series",    "Processor Series",             "laptop"),
    ("generation",          "CPU Generations",              "laptop"),
    ("storage_type",        "Storage Types",                "laptop"),
    ("ram_type",            "RAM Types",                    "laptop"),
    ("screen_size",         "Screen Sizes",                 "laptop"),
    ("grade",               "Device Grades",                "laptop"),
    ("battery_health",      "Battery Health Levels",        "laptop"),
    ("os_version",          "OS Versions",                  "laptop"),
    ("color",               "Colors",                       "laptop"),
    ("port_type",           "Port Types",                   "laptop"),
    ("cosmetic_issue",      "Cosmetic Issues",              "laptop"),
    ("cosmetic_grade",      "Cosmetic Grade Descriptions",  "laptop"),
    # ── Repair ───────────────────────────────────────────────────
    ("l1_issue",            "L1 Repair Issues",             "repair"),
    ("l2_issue",            "L2 Repair Issues",             "repair"),
    ("l3_issue",            "L3 Repair Issues",             "repair"),
    ("repair_issue",        "General Repair Issues",        "repair"),
    ("repair_resolution",   "Repair Resolutions",           "repair"),
    ("part_category",       "Spare Parts Categories",       "repair"),
    ("qc_check_item",       "QC Check Items",               "repair"),
    # ── Inventory / Logistics ─────────────────────────────────────
    ("floor",               "Floors / Locations",           "inventory"),
    ("warehouse",           "Warehouses / Zones",           "inventory"),
    ("supplier",            "Suppliers",                    "inventory"),
    ("data_destruction_method", "Data Destruction Methods", "inventory"),
    # ── Sales / Returns ──────────────────────────────────────────
    ("payment_mode",        "Payment Modes",                "sales"),
    ("return_reason",       "Return Reasons",               "sales"),
    ("condition_on_return", "Condition on Return",          "sales"),
]

# Group by tab
TABS = [
    ("laptop",    "Device / Laptop",  "bi-laptop"),
    ("repair",    "Repair & QC",      "bi-tools"),
    ("inventory", "Inventory",        "bi-box-seam"),
    ("sales",     "Sales & Returns",  "bi-receipt"),
]


@router.get("", response_class=HTMLResponse)
async def master_list(
    request: Request,
    main_tab: str = "dropdowns",
    role: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Single entry point for BOTH tabs.

    Always loads the dropdown-config accordion data AND the permission-matrix
    data, so either tab renders correctly regardless of which one is active.
    """
    result = await db.execute(
        select(MasterData).order_by(MasterData.category, MasterData.display_order, MasterData.value)
    )
    items = result.scalars().all()
    grouped = {}
    for cat_key, cat_label, cat_tab in CATEGORIES:
        grouped[cat_key] = {
            "label": cat_label,
            "tab": cat_tab,
            "items": [i for i in items if i.category == cat_key],
        }

    # Build accordion sections with data attached
    accordion_data = []
    for sec in ACCORDION_SECTIONS:
        cats = []
        for ck in sec["cat_keys"]:
            if ck in grouped:
                cats.append({"key": ck, **grouped[ck]})
        accordion_data.append({**sec, "categories": cats})

    # ── Permission-matrix data (always loaded so Tab 2 works) ────────────────
    builtin_roles = [(r.value, r.value.replace("_", " ").title()) for r in UserRole]
    custom_roles_q = await db.execute(select(CustomRole).order_by(CustomRole.display_name))
    custom_roles = [(cr.role_name, cr.display_name) for cr in custom_roles_q.scalars().all()]
    all_roles = builtin_roles + custom_roles

    # Default selected role: requested role, else first non-admin role
    selected_role = role
    if not selected_role and len(all_roles) > 1:
        selected_role = all_roles[1][0]

    perm_rows = {}
    if selected_role:
        rows = (await db.execute(
            select(RoleModulePermission)
            .where(RoleModulePermission.role_name == selected_role)
        )).scalars().all()
        perm_rows = {r.module: r for r in rows}

    return templates.TemplateResponse("admin/master.html", {
        "request": request,
        "grouped": grouped,
        "categories": CATEGORIES,
        "tabs": TABS,
        "accordion_data": accordion_data,
        "current_user": current_user,
        # Permission tab data
        "all_roles": all_roles,
        "selected_role": selected_role,
        "perm_rows": perm_rows,
        "perm_modules": PERM_MODULES,
        "perm_actions": PERM_ACTIONS,
    })


@router.post("/add")
async def add_master_value(
    category: str = Form(...),
    value: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    existing = await db.execute(
        select(MasterData).where(MasterData.category == category, MasterData.value == value)
    )
    if existing.scalar_one_or_none():
        return RedirectResponse(url=f"/admin/master?error=Value+already+exists+in+{category}", status_code=302)
    item = MasterData(category=category, value=value.strip(), description=description.strip() or None)
    db.add(item)
    await db.commit()
    cat_tab = dict((c[0], c[2]) for c in CATEGORIES).get(category, 'laptop')
    return RedirectResponse(url=f"/admin/master?success=Value+added&tab={cat_tab}", status_code=302)


@router.post("/{item_id}/edit")
async def edit_master_value(
    item_id: str,
    value: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(MasterData).where(MasterData.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404)
    item.value = value.strip()
    item.description = description.strip() or None
    await db.commit()
    cat_tab = dict((c[0], c[2]) for c in CATEGORIES).get(item.category, 'laptop')
    return RedirectResponse(url=f"/admin/master?success=Updated&tab={cat_tab}", status_code=302)


@router.post("/{item_id}/toggle")
async def toggle_master_value(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(MasterData).where(MasterData.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404)
    item.is_active = not item.is_active
    await db.commit()
    cat_tab = dict((c[0], c[2]) for c in CATEGORIES).get(item.category, 'laptop')
    return RedirectResponse(url=f"/admin/master?success=Updated&tab={cat_tab}", status_code=302)


@router.post("/{item_id}/delete")
async def delete_master_value(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    result = await db.execute(select(MasterData).where(MasterData.id == item_id))
    item = result.scalar_one_or_none()
    cat_tab = "laptop"
    if item:
        cat_tab = dict((c[0], c[2]) for c in CATEGORIES).get(item.category, 'laptop')
    await db.execute(delete(MasterData).where(MasterData.id == item_id))
    await db.commit()
    return RedirectResponse(url=f"/admin/master?success=Deleted&tab={cat_tab}", status_code=302)


@router.get("/export/{category}")
async def export_category_csv(category: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_only)):
    result = await db.execute(
        select(MasterData)
        .where(MasterData.category == category)
        .order_by(MasterData.display_order, MasterData.value)
    )
    items = result.scalars().all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["value", "description", "is_active", "display_order"])
    for item in items:
        writer.writerow([item.value, item.description or "", "yes" if item.is_active else "no", item.display_order])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=master_{category}.csv"}
    )


@router.get("/template/{category}")
async def download_category_template(category: str, current_user: User = Depends(admin_only)):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["value", "description"])
    writer.writerow(["Example Value", "Optional description"])
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=template_{category}.csv"}
    )


@router.post("/bulk-upload/{category}")
async def bulk_upload_category(
    category: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    # Validate category
    valid_cats = [c[0] for c in CATEGORIES]
    if category not in valid_cats:
        raise HTTPException(400, "Invalid category")

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")
    except Exception:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    added = 0
    skipped = 0

    for row in reader:
        value = (row.get("value") or "").strip()
        if not value:
            continue
        description = (row.get("description") or "").strip() or None

        existing = await db.execute(
            select(MasterData).where(MasterData.category == category, MasterData.value == value)
        )
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        item = MasterData(category=category, value=value, description=description)
        db.add(item)
        added += 1

    await db.commit()
    cat_tab = dict((c[0], c[2]) for c in CATEGORIES).get(category, 'laptop')
    return RedirectResponse(
        url=f"/admin/master?success={added}+values+added,+{skipped}+skipped&tab={cat_tab}",
        status_code=302
    )


@router.get("/api/{category}", response_class=JSONResponse)
async def get_master_values(category: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(
        select(MasterData.value)
        .where(MasterData.category == category, MasterData.is_active == True)
        .order_by(MasterData.display_order, MasterData.value)
    )
    return JSONResponse({"values": [r[0] for r in result.all()]})


# ── Permission Matrix Routes ──────────────────────────────────────────────────

@router.get("/permissions", response_class=HTMLResponse)
async def permissions_matrix(
    request: Request,
    role: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Render the Module Permissions tab (called via HTMX/JS or direct nav)."""
    # Built-in roles + custom roles
    builtin_roles = [(r.value, r.value.replace("_", " ").title()) for r in UserRole]
    custom_roles_q = await db.execute(select(CustomRole).order_by(CustomRole.display_name))
    custom_roles = [(cr.role_name, cr.display_name) for cr in custom_roles_q.scalars().all()]
    all_roles = builtin_roles + custom_roles

    selected_role = role or (all_roles[1][0] if len(all_roles) > 1 else "")

    # Load existing permissions for this role
    perm_rows = {}
    if selected_role:
        rows = (await db.execute(
            select(RoleModulePermission)
            .where(RoleModulePermission.role_name == selected_role)
        )).scalars().all()
        perm_rows = {r.module: r for r in rows}

    return templates.TemplateResponse("admin/master.html", {
        "request": request,
        "current_user": current_user,
        # Dropdown config tab data (needed for base template render)
        "grouped": {},
        "categories": CATEGORIES,
        "tabs": TABS,
        "accordion_data": [],
        # Permission tab data
        "active_main_tab": "permissions",
        "all_roles": all_roles,
        "selected_role": selected_role,
        "perm_rows": perm_rows,
        "perm_modules": PERM_MODULES,
        "perm_actions": PERM_ACTIONS,
    })


@router.get("/permissions/load", response_class=JSONResponse)
async def load_role_permissions(
    role: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Return permission matrix for a role as JSON (used by JS when user changes role dropdown)."""
    rows = (await db.execute(
        select(RoleModulePermission).where(RoleModulePermission.role_name == role)
    )).scalars().all()
    data = {
        r.module: {
            "can_enable": r.can_enable,
            "can_add":    r.can_add,
            "can_edit":   r.can_edit,
            "can_upload": r.can_upload,
        }
        for r in rows
    }
    return JSONResponse({"perms": data})


@router.post("/permissions/save")
async def save_role_permissions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Save the full permission matrix for one role. Replaces existing rows."""
    form = await request.form()
    role_name = (form.get("role_name") or "").strip()
    if not role_name:
        return RedirectResponse(url="/admin/master?main_tab=permissions&error=Role+name+required", status_code=302)

    # Delete existing permissions for this role
    await db.execute(delete(RoleModulePermission).where(RoleModulePermission.role_name == role_name))

    # Re-insert from form — checkboxes only present when checked
    new_perms: dict = {}
    for mod_key, _mod_label in PERM_MODULES:
        can_enable = f"perm_{mod_key}_can_enable" in form
        can_add    = f"perm_{mod_key}_can_add"    in form
        can_edit   = f"perm_{mod_key}_can_edit"   in form
        can_upload = f"perm_{mod_key}_can_upload" in form
        db.add(RoleModulePermission(
            role_name  = role_name,
            module     = mod_key,
            can_enable = can_enable,
            can_add    = can_add,
            can_edit   = can_edit,
            can_upload = can_upload,
            updated_by = current_user.username,
        ))
        new_perms[mod_key] = {
            "enable": can_enable, "add": can_add,
            "edit":   can_edit,   "upload": can_upload,
        }

    await db.commit()

    # Refresh in-memory cache so enforcement takes effect immediately
    set_cached_perms(role_name, new_perms)

    return RedirectResponse(
        url=f"/admin/master?main_tab=permissions&role={role_name}&success=Permissions+saved+for+{role_name}",
        status_code=302,
    )


@router.post("/permissions/add-role")
async def add_custom_role(
    request: Request,
    role_name: str = Form(...),
    display_name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    """Create a new custom role."""
    # Sanitise role_name to snake_case
    import re
    clean = re.sub(r"[^a-z0-9_]", "_", role_name.strip().lower())
    if not clean:
        return RedirectResponse(url="/admin/master?main_tab=permissions&error=Invalid+role+name", status_code=302)

    existing = (await db.execute(select(CustomRole).where(CustomRole.role_name == clean))).scalar_one_or_none()
    if existing:
        return RedirectResponse(url=f"/admin/master?main_tab=permissions&error=Role+{clean}+already+exists", status_code=302)

    db.add(CustomRole(role_name=clean, display_name=display_name.strip(), created_by=current_user.username))
    await db.commit()
    return RedirectResponse(
        url=f"/admin/master?main_tab=permissions&role={clean}&success=Role+{clean}+created",
        status_code=302,
    )


async def load_all_permissions_to_cache(db: AsyncSession) -> None:
    """Called on startup to warm the permission cache from DB."""
    rows = (await db.execute(select(RoleModulePermission))).scalars().all()
    tmp: dict = {}
    for r in rows:
        tmp.setdefault(r.role_name, {})[r.module] = {
            "enable": r.can_enable, "add": r.can_add,
            "edit":   r.can_edit,   "upload": r.can_upload,
        }
    _PERM_CACHE.clear()
    _PERM_CACHE.update(tmp)
