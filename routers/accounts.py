"""Accounts & Payments — supplier payments and customer receipts."""
import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID
from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from templates_config import templates
from database import get_db
from auth.dependencies import get_current_user, verify_csrf
from services.audit_engine import audit
from models.user import User, UserRole
from models.crm import SupplierPayment, CustomerReceipt, CRMContact
from models.dealers import Dealer, DealerOrder
from models.lot import Lot

router = APIRouter(prefix="/accounts", tags=["accounts"])

FINANCE_ROLES = (UserRole.admin, UserRole.inventory_manager, UserRole.sales_manager)
PAYMENT_MODES = ["cash", "upi", "neft", "rtgs", "cheque", "card"]


def _parse_date(v: str) -> date:
    try:
        return date.fromisoformat(v) if v and v.strip() else date.today()
    except ValueError:
        return date.today()


@router.get("", response_class=HTMLResponse)
async def accounts_index(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)
    sp_total = (await db.execute(
        select(func.coalesce(func.sum(SupplierPayment.amount), 0))
    )).scalar()
    cr_total = (await db.execute(
        select(func.coalesce(func.sum(CustomerReceipt.amount), 0))
    )).scalar()
    recent_payments = (await db.execute(
        select(SupplierPayment)
        .options(selectinload(SupplierPayment.contact))
        .order_by(SupplierPayment.created_at.desc()).limit(10)
    )).scalars().all()
    recent_receipts = (await db.execute(
        select(CustomerReceipt)
        .options(selectinload(CustomerReceipt.contact))
        .order_by(CustomerReceipt.created_at.desc()).limit(10)
    )).scalars().all()
    return templates.TemplateResponse("accounts/index.html", {
        "request": request, "current_user": current_user,
        "sp_total": float(sp_total or 0),
        "cr_total": float(cr_total or 0),
        "recent_payments": recent_payments,
        "recent_receipts": recent_receipts,
        "can_edit": current_user.role in FINANCE_ROLES,
    })


@router.get("/supplier-payments", response_class=HTMLResponse)
async def supplier_payments(
    request: Request,
    contact_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)
    q = (select(SupplierPayment)
         .options(selectinload(SupplierPayment.contact), selectinload(SupplierPayment.lot))
         .order_by(SupplierPayment.payment_date.desc()))
    if contact_id:
        q = q.where(SupplierPayment.contact_id == contact_id)
    payments = (await db.execute(q)).scalars().all()
    suppliers = (await db.execute(
        select(CRMContact)
        .where(CRMContact.contact_type.in_(["supplier", "both"]))
        .where(CRMContact.status == "active")
        .order_by(CRMContact.company_name)
    )).scalars().all()
    lots = (await db.execute(
        select(Lot).order_by(Lot.created_at.desc()).limit(50)
    )).scalars().all()
    total = sum(float(p.amount) for p in payments)
    return templates.TemplateResponse("accounts/supplier_payments.html", {
        "request": request, "current_user": current_user,
        "payments": payments, "suppliers": suppliers, "lots": lots,
        "total": total, "sel_contact": contact_id,
        "payment_modes": PAYMENT_MODES,
        "can_edit": current_user.role in FINANCE_ROLES,
    })


@router.post("/supplier-payments/new")
async def create_supplier_payment(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    contact_id: str = Form(default=""),
    lot_id: str = Form(default=""),
    po_id: str = Form(default=""),
    payment_date: str = Form(...),
    amount: str = Form(...),
    payment_mode: str = Form(default=""),
    reference_no: str = Form(default=""),
    is_advance: str = Form(default="off"),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/accounts/supplier-payments?error=Permission+denied", status_code=302)
    try:
        amt = float(amount)
        if amt <= 0:
            raise ValueError("amount must be positive")
    except (ValueError, TypeError):
        return RedirectResponse(url="/accounts/supplier-payments?error=Invalid+amount", status_code=302)
    if payment_mode and payment_mode not in PAYMENT_MODES:
        return RedirectResponse(url="/accounts/supplier-payments?error=Invalid+payment+mode", status_code=302)
    pay = SupplierPayment(
        contact_id=contact_id or None,
        lot_id=lot_id or None,
        po_id=po_id or None,
        payment_date=_parse_date(payment_date),
        amount=amt,
        payment_mode=payment_mode or None,
        reference_no=reference_no or None,
        is_advance=(is_advance == "on"),
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(pay)
    await audit(
        db, user=current_user, action="SUPPLIER_PAYMENT_RECORDED",
        table_name="supplier_payments", record_id=str(pay.id),
        new_value={
            "amount": amt,
            "payment_mode": payment_mode or None,
            "contact_id": contact_id or None,
            "lot_id": lot_id or None,
            "reference_no": reference_no or None,
            "is_advance": (is_advance == "on"),
        },
        request=request,
    )
    await db.commit()
    return RedirectResponse(url="/accounts/supplier-payments?success=Payment+recorded", status_code=302)


@router.get("/customer-receipts", response_class=HTMLResponse)
async def customer_receipts(
    request: Request,
    dealer_id: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)
    q = (select(CustomerReceipt)
         .options(selectinload(CustomerReceipt.contact), selectinload(CustomerReceipt.dealer))
         .order_by(CustomerReceipt.receipt_date.desc()))
    if dealer_id:
        q = q.where(CustomerReceipt.dealer_id == dealer_id)
    receipts = (await db.execute(q)).scalars().all()
    dealers = (await db.execute(
        select(Dealer).where(Dealer.status == "active").order_by(Dealer.business_name)
    )).scalars().all()
    total = sum(float(r.amount) for r in receipts)
    return templates.TemplateResponse("accounts/customer_receipts.html", {
        "request": request, "current_user": current_user,
        "receipts": receipts, "dealers": dealers,
        "total": total, "sel_dealer": dealer_id,
        "payment_modes": PAYMENT_MODES,
        "can_edit": current_user.role in FINANCE_ROLES,
    })


@router.post("/customer-receipts/new")
async def create_customer_receipt(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    contact_id: str = Form(default=""),
    dealer_id: str = Form(default=""),
    sale_id: str = Form(default=""),
    dealer_order_id: str = Form(default=""),
    receipt_date: str = Form(...),
    amount: str = Form(...),
    payment_mode: str = Form(default=""),
    reference_no: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/accounts/customer-receipts?error=Permission+denied", status_code=302)
    try:
        amt = float(amount)
        if amt <= 0:
            raise ValueError("amount must be positive")
    except (ValueError, TypeError):
        return RedirectResponse(url="/accounts/customer-receipts?error=Invalid+amount", status_code=302)
    if payment_mode and payment_mode not in PAYMENT_MODES:
        return RedirectResponse(url="/accounts/customer-receipts?error=Invalid+payment+mode", status_code=302)
    rec = CustomerReceipt(
        contact_id=contact_id or None,
        dealer_id=dealer_id or None,
        sale_id=sale_id or None,
        dealer_order_id=dealer_order_id or None,
        receipt_date=_parse_date(receipt_date),
        amount=amt,
        payment_mode=payment_mode or None,
        reference_no=reference_no or None,
        notes=notes or None,
        created_by=current_user.username,
    )
    db.add(rec)
    # Auto-reconcile against dealer order if linked
    from decimal import Decimal
    if dealer_order_id:
        ord_result = await db.execute(
            select(DealerOrder).where(DealerOrder.id == dealer_order_id)
        )
        linked_order = ord_result.scalar_one_or_none()
        if linked_order:
            apply_amt = min(Decimal(str(amt)), linked_order.due_amount or Decimal("0"))
            if apply_amt > Decimal("0"):
                linked_order.paid_amount = (linked_order.paid_amount or Decimal("0")) + apply_amt
                linked_order.due_amount = max(Decimal("0"), (linked_order.due_amount or Decimal("0")) - apply_amt)
                if linked_order.due_amount == Decimal("0") and linked_order.status not in ("cancelled", "paid"):
                    linked_order.status = "paid"
    await audit(db, user=current_user, action="RECEIPT_RECORDED",
                table_name="customer_receipts", record_id=str(rec.id),
                new_value={"amount": amt, "payment_mode": payment_mode or None,
                           "dealer_id": dealer_id or None,
                           "reference_no": reference_no or None},
                request=request)
    await db.commit()
    return RedirectResponse(url="/accounts/customer-receipts?success=Receipt+recorded", status_code=302)


# ── CSV Template Download ─────────────────────────────────────────────────────

@router.get("/customer-receipts/bulk-upload-template")
async def download_receipt_csv_template(
    current_user: User = Depends(get_current_user),
):
    """Return a sample CSV template for bulk receipt upload."""
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)
    sample_rows = [
        ["amount", "payment_date", "payment_mode", "reference_no", "notes", "customer_name"],
        ["15000", "2026-05-15", "upi", "UTR123456789", "May payment", "ABC Corp"],
        ["8500", "2026-05-15", "neft", "UTR987654321", "", "XYZ Traders"],
    ]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(sample_rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=receipt_bulk_upload_template.csv"},
    )


# ── Bulk Upload Form ──────────────────────────────────────────────────────────

@router.get("/customer-receipts/bulk-upload", response_class=HTMLResponse)
async def receipt_bulk_upload_form(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)
    return templates.TemplateResponse("accounts/receipts_bulk_upload.html", {
        "request": request, "current_user": current_user,
        "results": None,
    })


@router.post("/customer-receipts/bulk-upload", response_class=HTMLResponse)
async def receipt_bulk_upload(
    request: Request,
    _csrf: None = Depends(verify_csrf),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in FINANCE_ROLES:
        return RedirectResponse(url="/?error=Access+denied", status_code=302)

    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # handle BOM from Excel
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    results = []
    added = 0

    for i, row in enumerate(reader, start=2):  # row 1 is header
        row_num = i
        amount_raw = (row.get("amount") or "").strip()
        payment_date_raw = (row.get("payment_date") or "").strip()
        payment_mode = (row.get("payment_mode") or "").strip().lower()
        reference_no = (row.get("reference_no") or "").strip() or None
        notes = (row.get("notes") or "").strip() or None
        customer_name = (row.get("customer_name") or "").strip() or None

        # Validate amount
        try:
            amt = Decimal(amount_raw)
            if amt <= 0:
                raise ValueError("must be positive")
        except (InvalidOperation, ValueError) as e:
            results.append({
                "row": row_num, "amount": amount_raw, "date": payment_date_raw,
                "mode": payment_mode, "ref": reference_no or "",
                "customer": customer_name or "",
                "status": "error", "message": f"Invalid amount: {e}",
            })
            continue

        # Validate date
        pdate = _parse_date(payment_date_raw)

        # Validate payment mode
        if payment_mode and payment_mode not in PAYMENT_MODES:
            results.append({
                "row": row_num, "amount": str(amt), "date": str(pdate),
                "mode": payment_mode, "ref": reference_no or "",
                "customer": customer_name or "",
                "status": "error", "message": f"Invalid payment_mode '{payment_mode}'",
            })
            continue

        rec = CustomerReceipt(
            receipt_date=pdate,
            amount=amt,
            payment_mode=payment_mode or None,
            reference_no=reference_no,
            notes=notes,
            created_by=current_user.username,
            # contact_id left null for bulk uploads
        )
        db.add(rec)
        results.append({
            "row": row_num, "amount": str(amt), "date": str(pdate),
            "mode": payment_mode or "—", "ref": reference_no or "—",
            "customer": customer_name or "—",
            "status": "added", "message": "OK",
        })
        added += 1

    if added:
        await db.commit()

    return templates.TemplateResponse("accounts/receipts_bulk_upload.html", {
        "request": request, "current_user": current_user,
        "results": results, "added": added,
    })
