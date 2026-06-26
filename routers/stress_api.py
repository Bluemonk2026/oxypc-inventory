"""
Stress Test REST API
====================
POST /stress/{barcode}/run       — start stress tests on this server machine
GET  /stress/{barcode}/status    — live results poll (JSON)
POST /stress/{barcode}/stop      — stop running tests
POST /stress/{barcode}/save      — save results + generate PDF to DB
GET  /stress/{barcode}/report    — download latest PDF (or generate on-the-fly)
GET  /stress/results/{barcode}   — list all saved runs (JSON)
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user, verify_csrf
from database import get_db
from models.device import Device
from models.user import User
from models.stress import StressTestResult
import stress_runner as sr
from utils.timezone import app_now

router = APIRouter(prefix="/stress", tags=["stress"], dependencies=[Depends(verify_csrf)])

# ── Reports storage folder ────────────────────────────────────────────────────
_BASE_DIR  = Path(__file__).resolve().parent.parent
REPORTS_DIR = _BASE_DIR / "static" / "stress_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ── Request/response schemas ──────────────────────────────────────────────────

class RunRequest(BaseModel):
    duration: str = "standard"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pdf_filename(barcode: str, run_id: int) -> str:
    return f"stress_{barcode}_{run_id}.pdf"


def _generate_pdf(record: StressTestResult) -> bytes:
    """Generate a PDF stress report.  Uses fpdf2 if available, else plain-text."""
    try:
        from fpdf import FPDF
        return _pdf_fpdf(record)
    except ImportError:
        return _pdf_text(record)


def _pdf_fpdf(record: StressTestResult) -> bytes:
    from fpdf import FPDF

    STATUS_COLORS = {
        "PASS":               (34,  139,  34),
        "FAIL":               (200,  30,  30),
        "WARN":               (200, 150,   0),
        "PASS_WITH_WARNINGS": (200, 150,   0),
        "SKIP":               (100, 100, 100),
        "IN_PROGRESS":        (60,  100, 200),
    }
    BADGE_BG = {
        "PASS":    (209, 231, 221),
        "FAIL":    (248, 215, 218),
        "WARN":    (255, 243, 205),
        "SKIP":    (226, 227, 229),
        "RUNNING": (207, 226, 255),
        "PENDING": (226, 227, 229),
    }

    results = record.results_json or {}
    NAMES = sr.TEST_NAMES

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # ── Header band ───────────────────────────────────────────────────────────
    pdf.set_fill_color(30, 30, 30)
    pdf.rect(0, 0, 210, 28, "F")
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(255, 255, 255)
    pdf.set_y(8)
    pdf.cell(0, 8, "OxyPC — Stress Test Report", align="C")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(180, 180, 180)
    pdf.cell(0, 6, "Automated Hardware Stress Verification", align="C")
    pdf.ln(18)

    # ── Device info table ─────────────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Device Information", ln=True)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(2)

    info_rows = [
        ("Tag Number", record.barcode),
        ("Brand / Model", f"{record.brand or '—'} {record.model_name or ''}".strip()),
        ("Tested By",     record.run_by or "—"),
        ("Run At",        record.run_at.strftime("%d %b %Y  %H:%M:%S") if record.run_at else "—"),
        ("Duration",      (record.duration or "standard").capitalize()),
    ]
    for label, val in info_rows:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(245, 245, 245)
        pdf.cell(45, 7, label, border=0, fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 7, str(val), border=0, ln=True)

    pdf.ln(4)

    # ── Overall verdict ───────────────────────────────────────────────────────
    ov = record.overall_status or "UNKNOWN"
    ov_color = STATUS_COLORS.get(ov, (100, 100, 100))
    pdf.set_fill_color(*ov_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 10, f"  Overall Result: {ov.replace('_', ' ')}", fill=True, ln=True)
    pdf.ln(4)

    # ── Results table ─────────────────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Test Results", ln=True)
    pdf.line(15, pdf.get_y(), 195, pdf.get_y())
    pdf.ln(2)

    # Header row
    pdf.set_fill_color(40, 40, 40)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(25, 7, "Status",  border=0, fill=True)
    pdf.cell(40, 7, "Test",    border=0, fill=True)
    pdf.cell(0,  7, "Summary", border=0, fill=True, ln=True)

    pdf.set_text_color(0, 0, 0)
    for key in sr.ALL_KEYS:
        r = results.get(key, {})
        st  = r.get("status", "PENDING")
        bg  = BADGE_BG.get(st, (240, 240, 240))
        name = NAMES.get(key, key)
        summ = r.get("summary", "—")[:80]

        row_bg = (250, 250, 250) if sr.ALL_KEYS.index(key) % 2 == 0 else (255, 255, 255)
        pdf.set_fill_color(*row_bg)

        # Status badge cell
        pdf.set_fill_color(*bg)
        pdf.set_font("Helvetica", "B", 8)
        pdf.cell(25, 7, st, border=0, fill=True, align="C")

        pdf.set_fill_color(*row_bg)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(40, 7, name, border=0, fill=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 7, summ, border=0, fill=True, ln=True)

    pdf.ln(6)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, f"Generated by OxyPC Inventory System — {datetime.now().strftime('%d %b %Y %H:%M')}", align="C")

    return bytes(pdf.output())


def _pdf_text(record: StressTestResult) -> bytes:
    """Fallback: plain-text 'PDF' (actually a text file) if fpdf2 not installed."""
    results = record.results_json or {}
    lines = [
        "OxyPC — Stress Test Report",
        "=" * 50,
        f"Tag Number  : {record.barcode}",
        f"Brand/Model : {record.brand or '—'} {record.model_name or ''}".strip(),
        f"Tested By   : {record.run_by or '—'}",
        f"Run At      : {record.run_at}",
        f"Duration    : {record.duration}",
        f"Overall     : {record.overall_status}",
        "",
        "Test Results",
        "-" * 50,
    ]
    for key in sr.ALL_KEYS:
        r = results.get(key, {})
        lines.append(f"{sr.TEST_NAMES.get(key, key):20s}  {r.get('status','PENDING'):10s}  {r.get('summary','')}")
    return "\n".join(lines).encode("utf-8")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{barcode}/run")
async def run_stress(
    barcode: str,
    body: RunRequest = Body(default=RunRequest()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = sr.get_session(barcode)
    if existing and existing.running:
        raise HTTPException(409, "Tests already running for this device")

    # Fetch device info for the session
    dev = await db.execute(select(Device).where(Device.barcode == barcode))
    device = dev.scalar_one_or_none()
    brand = device.brand or "" if device else ""
    model = device.model or "" if device else ""

    sr.start_session(
        barcode=barcode,
        duration=body.duration,
        run_by=current_user.username,
        brand=brand,
        model=model,
    )
    return {"status": "started", "barcode": barcode, "duration": body.duration}


@router.get("/{barcode}/status")
async def get_status(barcode: str, current_user: User = Depends(get_current_user)):
    session = sr.get_session(barcode)
    if not session:
        return {"running": False, "overall_status": "NOT_RUN", "results": {}}
    return session.to_status_dict()


@router.post("/{barcode}/stop")
async def stop_stress(barcode: str, current_user: User = Depends(get_current_user)):
    sr.stop_session(barcode)
    return {"status": "stopping"}


@router.post("/{barcode}/save")
async def save_results(
    barcode: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session = sr.get_session(barcode)
    if not session:
        raise HTTPException(404, "No stress test session found for this device")
    if session.running:
        raise HTTPException(409, "Tests still running — wait for completion before saving")

    full = session.to_full_dict()
    run_at = datetime.fromtimestamp(session.finished_at or session.started_at, tz=timezone.utc)

    record = StressTestResult(
        barcode=barcode,
        brand=session.brand,
        model_name=session.model,
        run_at=run_at,
        duration=session.duration,
        overall_status=session.overall_status(),
        results_json=full["results"],
        run_by=session.run_by,
    )
    db.add(record)
    await db.flush()  # get the id

    # Generate PDF
    try:
        pdf_bytes = _generate_pdf(record)
        fname     = _pdf_filename(barcode, record.id)
        fpath     = REPORTS_DIR / fname
        fpath.write_bytes(pdf_bytes)
        record.pdf_path = str(fpath)
    except Exception as e:
        record.pdf_path = None

    await db.commit()
    return {
        "saved": True,
        "result_id": record.id,
        "overall_status": record.overall_status,
        "pdf_available": record.pdf_path is not None,
    }


@router.get("/{barcode}/report")
async def download_report(
    barcode: str,
    result_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if result_id:
        q = select(StressTestResult).where(
            StressTestResult.id == result_id,
            StressTestResult.barcode == barcode,
        )
    else:
        q = (
            select(StressTestResult)
            .where(StressTestResult.barcode == barcode)
            .order_by(desc(StressTestResult.run_at))
            .limit(1)
        )

    res    = await db.execute(q)
    record = res.scalar_one_or_none()
    if not record:
        raise HTTPException(404, "No saved stress report found for this device")

    # Try to serve stored PDF first
    if record.pdf_path and Path(record.pdf_path).exists():
        pdf_bytes = Path(record.pdf_path).read_bytes()
    else:
        # Regenerate on-the-fly
        pdf_bytes = _generate_pdf(record)

    filename = f"stress_report_{barcode}.pdf"
    try:
        from fpdf import FPDF
        media_type = "application/pdf"
        cd_name    = filename
    except ImportError:
        media_type = "text/plain"
        cd_name    = filename.replace(".pdf", ".txt")

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{cd_name}"'},
    )


@router.get("/results/{barcode}")
async def list_results(
    barcode: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(StressTestResult)
        .where(StressTestResult.barcode == barcode)
        .order_by(desc(StressTestResult.run_at))
        .limit(20)
    )
    records = rows.scalars().all()
    return [
        {
            "id":             r.id,
            "run_at":         r.run_at.isoformat() if r.run_at else None,
            "duration":       r.duration,
            "overall_status": r.overall_status,
            "run_by":         r.run_by,
            "has_pdf":        r.pdf_path is not None,
        }
        for r in records
    ]


@router.get("/has-results")
async def bulk_has_results(
    barcodes: str,   # comma-separated
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns set of barcodes that have at least one saved stress result."""
    bc_list = [b.strip() for b in barcodes.split(",") if b.strip()]
    if not bc_list:
        return {}
    rows = await db.execute(
        select(StressTestResult.barcode, StressTestResult.id,
               StressTestResult.overall_status, StressTestResult.run_at)
        .where(StressTestResult.barcode.in_(bc_list))
        .order_by(desc(StressTestResult.run_at))
    )
    seen = {}
    for barcode, rid, status, run_at in rows.all():
        if barcode not in seen:
            seen[barcode] = {
                "result_id":     rid,
                "overall_status": status,
                "run_at":        run_at.isoformat() if run_at else None,
            }
    return seen
