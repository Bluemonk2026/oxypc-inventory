from templates_config import templates
import math
import subprocess
import sys
from datetime import datetime
from utils.timezone import app_now
from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, Depends, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from database import get_db
from models.user import User, UserRole, LoginLog, UserPermission, ROLE_LABELS
from models.engines import AuditLog
from models.cost_config import CostConfig
from auth.dependencies import get_current_user, require_roles, hash_password, verify_csrf
from services.audit_engine import audit

PERMISSION_GROUPS = {
    "Inventory & Lots": {
        "can_add_lot": "Add / Create Lots",
        "can_edit_lot": "Edit Lots",
        "can_delete_lot": "Delete Lots",
        "can_stock_in": "Register Devices (Stock In)",
        "can_bulk_upload": "Bulk Upload (CSV)",
        "can_view_all_devices": "View All Devices",
        "can_transfer_stock": "Transfer Stock Between Locations",
        "can_manage_locations": "Manage Inventory Locations",
        "can_manage_grn": "Record / Manage GRN",
    },
    "IQC & Repair": {
        "can_do_iqc": "IQC Inspection",
        "can_do_l1": "L1 Repair",
        "can_do_l2": "L2 Repair",
        "can_do_l3": "L3 Repair",
        "can_do_qc": "QC Check",
        "can_do_cosmetic": "Cosmetic / Cleaning Stage",
        "can_move_device": "Move Device Between Stages",
        "can_view_repair_history": "View Full Repair History",
    },
    "Sales & Invoices": {
        "can_create_sale": "Create Sales",
        "can_view_all_sales": "View All Sales (not just own)",
        "can_apply_discount": "Apply Discounts",
        "can_process_return": "Process Returns",
        "can_view_invoices": "View Invoices",
        "can_create_invoice": "Create / Print Invoices",
        "can_view_cost_data": "View Device Buying / Cost Data",
    },
    "CRM — Contacts & Deals": {
        "can_view_crm_contacts": "View CRM Contacts",
        "can_add_crm_contact": "Add / Edit CRM Contacts",
        "can_delete_crm_contact": "Delete / Trash CRM Contacts",
        "can_view_crm_sourcing": "View Sourcing Deals",
        "can_manage_crm_sourcing": "Create / Edit Sourcing Deals",
        "can_view_crm_sales_opp": "View CRM Sales Opportunities",
        "can_manage_crm_sales_opp": "Create / Edit Sales Opportunities",
        "can_view_crm_quotes": "View Quotes / Proformas",
        "can_create_crm_quotes": "Create / Edit Quotes",
        "can_view_purchase_orders": "View Purchase Orders",
        "can_create_purchase_orders": "Create / Edit Purchase Orders",
    },
    "Telecalling & Dealers": {
        "can_use_telecalling": "Use Telecalling Module",
        "can_view_all_calls": "View All Agent Calls (not just own)",
        "can_manage_dealers": "Manage Dealers / CRM Contacts",
        "can_send_whatsapp": "Send WhatsApp Messages",
        "can_view_crm_dashboard": "View CRM Dashboard",
        "can_view_crm_reports": "View CRM / Telecalling Reports",
    },
    "Spare Parts": {
        "can_add_spare_parts": "Add / Edit Spare Parts Stock",
        "can_consume_parts": "Record Parts Consumption",
        "can_manage_ram_tracking": "RAM Swap Tracking",
        "can_view_parts_report": "View Parts Usage Reports",
    },
    "Reports & Market": {
        "can_view_reports": "View Operational Reports",
        "can_export_data": "Export Data (CSV / Excel)",
        "can_view_market_prices": "View Market Price Reference",
        "can_view_financial_reports": "View Financial / P&L Reports",
    },
    "Attendance": {
        "can_mark_own_attendance": "Mark Own Attendance",
        "can_mark_attendance": "Mark Attendance for Others",
        "can_view_attendance_all": "View All Staff Attendance",
        "can_view_attendance_reports": "View Attendance Reports",
    },
    "System & Settings": {
        "can_access_settings": "Access System Settings",
        "can_manage_master_data": "Manage Master / Reference Data",
        "can_view_audit_log": "View Audit Log",
        "can_run_backup": "Trigger Manual DB Backup",
    },
}

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(verify_csrf)])
require_admin = require_roles(UserRole.admin)


@router.get("/users", response_class=HTMLResponse)
async def list_users(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return templates.TemplateResponse("admin/users.html", {
        "request": request, "users": users, "current_user": current_user,
        "role_labels": ROLE_LABELS, "roles": [r for r in UserRole]
    })


@router.get("/users/new", response_class=HTMLResponse)
async def new_user_form(request: Request, current_user: User = Depends(require_admin)):
    return templates.TemplateResponse("admin/user_form.html", {
        "request": request, "current_user": current_user,
        "roles": [r for r in UserRole], "role_labels": ROLE_LABELS, "edit_user": None
    })


@router.post("/users/new")
async def create_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(...),
    role: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        return templates.TemplateResponse("admin/user_form.html", {
            "request": request, "current_user": current_user,
            "roles": [r for r in UserRole], "role_labels": ROLE_LABELS,
            "edit_user": None, "error": "Username already exists"
        })
    user = User(
        username=username, full_name=full_name,
        role=UserRole(role), password_hash=hash_password(password),
        created_by=current_user.username, status=True,
    )
    db.add(user)
    await db.flush()   # get user.id before audit
    await audit(db, action="USER_CREATED", user=current_user,
                table_name="users", record_id=str(user.id),
                new_value={"username": username, "role": role, "full_name": full_name},
                request=request)
    await db.commit()
    return RedirectResponse(url="/admin/users?success=User+created", status_code=302)


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_form(user_id: str, request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    result = await db.execute(select(User).where(User.id == user_id))
    edit_user = result.scalar_one_or_none()
    if not edit_user:
        raise HTTPException(404)
    return templates.TemplateResponse("admin/user_form.html", {
        "request": request, "current_user": current_user,
        "roles": [r for r in UserRole], "role_labels": ROLE_LABELS, "edit_user": edit_user
    })


@router.post("/users/{user_id}/edit")
async def update_user(
    user_id: str,
    full_name: str = Form(...),
    role: str = Form(...),
    status: str = Form("on"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)
    old_vals = {"full_name": user.full_name, "role": user.role.value, "status": user.status}
    user.full_name = full_name
    user.role = UserRole(role)
    new_status = (status == "on")
    user.status = new_status
    action = "USER_DISABLED" if not new_status and old_vals["status"] else "USER_UPDATED"
    await audit(db, action=action, user=current_user,
                table_name="users", record_id=str(user.id),
                old_value=old_vals,
                new_value={"full_name": full_name, "role": role, "status": new_status})
    await db.commit()
    return RedirectResponse(url="/admin/users?success=User+updated", status_code=302)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404)
    user.password_hash = hash_password(new_password)
    await db.commit()
    return RedirectResponse(url="/admin/users?success=Password+reset", status_code=302)


@router.get("/users/{user_id}/permissions", response_class=HTMLResponse)
async def user_permissions_form(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(404)

    perms_result = await db.execute(
        select(UserPermission).where(UserPermission.user_id == user_id, UserPermission.granted == True)
    )
    granted_permissions = {p.permission for p in perms_result.scalars().all()}

    return templates.TemplateResponse("admin/permissions.html", {
        "request": request,
        "current_user": current_user,
        "target_user": target_user,
        "permission_groups": PERMISSION_GROUPS,
        "granted_permissions": granted_permissions,
    })


@router.post("/users/{user_id}/permissions")
async def save_permissions(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise HTTPException(404)

    form = await request.form()
    selected = set(form.getlist("permissions"))

    # Delete all existing permissions for this user
    await db.execute(delete(UserPermission).where(UserPermission.user_id == user_id))

    # Re-insert selected ones
    for perm in selected:
        db.add(UserPermission(
            user_id=target_user.id,
            permission=perm,
            granted=True,
            granted_by=current_user.username,
        ))
    await db.commit()
    return RedirectResponse(url=f"/admin/users?success=Permissions+saved+for+{target_user.full_name.replace(' ', '+')}", status_code=302)


@router.get("/login-log", response_class=HTMLResponse)
async def login_log(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    result = await db.execute(
        select(LoginLog, User.username, User.full_name)
        .join(User, LoginLog.user_id == User.id)
        .order_by(LoginLog.timestamp.desc())
        .limit(500)
    )
    logs = result.all()
    return templates.TemplateResponse("admin/login_log.html", {
        "request": request, "logs": logs, "current_user": current_user
    })


AUDIT_PER_PAGE = 50


@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_view(
    request: Request,
    username: str = Query(default=""),
    action: str = Query(default=""),
    table_name: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    q = select(AuditLog)
    if username:
        q = q.where(AuditLog.username.ilike(f"%{username}%"))
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action}%"))
    if table_name:
        q = q.where(AuditLog.table_name == table_name)

    # Total count for pagination
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total_count = count_result.scalar() or 0
    total_pages = max(1, math.ceil(total_count / AUDIT_PER_PAGE))
    page = min(page, total_pages)

    logs = (await db.execute(
        q.order_by(AuditLog.timestamp.desc())
         .offset((page - 1) * AUDIT_PER_PAGE)
         .limit(AUDIT_PER_PAGE)
    )).scalars().all()

    # Distinct table names for the filter dropdown
    table_names_result = await db.execute(
        select(AuditLog.table_name).distinct().order_by(AuditLog.table_name)
    )
    table_names = [r[0] for r in table_names_result.all() if r[0]]

    return templates.TemplateResponse("admin/audit_log.html", {
        "request": request,
        "current_user": current_user,
        "logs": logs,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "username": username,
        "action": action,
        "table_name": table_name,
        "table_names": table_names,
        "per_page": AUDIT_PER_PAGE,
    })


# ── Cost Config ────────────────────────────────────────────────────────────

COST_CONFIG_DEFS = [
    ("repair_labour_rate", "Labour Rate per Repair Attempt (Rs)",
     "Used when engineer leaves cost field blank. Default: Rs 150"),
    ("cosmetic_rate", "Cosmetic Rework Rate per Device (Rs)",
     "Applied per device that passed through cleaning/rework stage. Default: Rs 50"),
    ("gst_rate_intra", "GST Rate — Intra-State (% total)",
     "CGST + SGST for same-state sales. Default: 18 (9+9). Enter total %, system splits equally."),
    ("gst_rate_inter", "GST Rate — Inter-State IGST (%)",
     "IGST for out-of-state sales. Default: 18. Typically same as intra total."),
]


@router.get("/cost-config", response_class=HTMLResponse)
async def cost_config_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    result = await db.execute(select(CostConfig))
    rows = {r.key: r for r in result.scalars().all()}
    return templates.TemplateResponse("admin/cost_config.html", {
        "request": request,
        "current_user": current_user,
        "defs": COST_CONFIG_DEFS,
        "rows": rows,
    })


@router.post("/cost-config")
async def cost_config_save(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    form = await request.form()
    for key, _label, _hint in COST_CONFIG_DEFS:
        raw = form.get(key, "").strip()
        try:
            new_val = Decimal(raw)
        except Exception:
            continue
        result = await db.execute(select(CostConfig).where(CostConfig.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = new_val
            row.updated_by = current_user.username
        else:
            db.add(CostConfig(key=key, value=new_val, updated_by=current_user.username))

    await audit(db, action="COST_CONFIG_UPDATE", user=current_user,
                table_name="cost_config",
                new_value={k: form.get(k) for k, _, _ in COST_CONFIG_DEFS},
                request=request)
    await db.commit()
    return RedirectResponse(url="/admin/cost-config?success=Rates+saved", status_code=302)


# ── Backup ────────────────────────────────────────────────────────────────

_BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
_BACKUP_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "backup_db.py"


@router.get("/backup-status")
async def backup_status(current_user: User = Depends(require_admin)):
    """Return info about the most recent backup file."""
    if not _BACKUP_DIR.exists():
        return JSONResponse({"status": "no_backups", "last_backup": None})

    backups = sorted(
        _BACKUP_DIR.glob("oxypc_*.sql.gz"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not backups:
        return JSONResponse({"status": "no_backups", "last_backup": None})

    latest = backups[0]
    mtime   = datetime.utcfromtimestamp(latest.stat().st_mtime)
    age_h   = round((app_now() - mtime).total_seconds() / 3600, 1)
    size_mb = round(latest.stat().st_size / (1024 * 1024), 2)

    return JSONResponse({
        "status": "ok",
        "last_backup": {
            "filename":  latest.name,
            "size_mb":   size_mb,
            "age_hours": age_h,
            "taken_at":  mtime.strftime("%Y-%m-%d %H:%M UTC"),
        },
        "total_backups": len(backups),
    })


@router.post("/backup-now")
async def backup_now(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Trigger an immediate database backup synchronously."""
    python = sys.executable
    result = subprocess.run(
        [python, str(_BACKUP_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    success = result.returncode == 0
    output  = (result.stdout + result.stderr).strip()

    await audit(db, action="MANUAL_BACKUP", user=current_user,
                table_name="system",
                new_value={"success": success, "output": output[:500]},
                request=request)
    await db.commit()

    msg = "Backup+completed" if success else "Backup+failed"
    return RedirectResponse(
        url=f"/admin/users?{'success' if success else 'error'}={msg}",
        status_code=302,
    )
