"""
QA / UAT Tracking Module
========================
Routes:
  GET  /qa/                        — Dashboard (metrics + KPIs)
  GET  /qa/requirements            — Requirements list + RTM link
  POST /qa/requirements/new        — Create requirement
  POST /qa/requirements/{id}/status — Update status
  GET  /qa/test-cases              — Test cases list
  POST /qa/test-cases/new          — Create test case
  POST /qa/test-cases/{id}/execute — Log execution result
  GET  /qa/defects                 — Defect tracker
  POST /qa/defects/new             — Log defect
  POST /qa/defects/{id}/status     — Update defect status
  GET  /qa/uat                     — UAT scenarios list
  POST /qa/uat/new                 — Create UAT scenario
  POST /qa/uat/{id}/execute        — Record UAT result + sign-off
  GET  /qa/releases                — Release list
  POST /qa/releases/new            — Create release
  POST /qa/releases/{id}/status    — Advance release status
  GET  /qa/rtm                     — Requirement Traceability Matrix
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from utils.timezone import app_now
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user, require_roles
from database import get_db
from models.user import User, UserRole
from models.qa_uat import (
    QARequirement, QATestCase, QATestExecution, QADefect,
    QAUATScenario, QARelease,
    RequirementSource, RequirementStatus, RequirementPriority,
    TestCaseType, TestCaseStatus, ExecutionStatus,
    DefectSeverity, DefectPriority, DefectStatus,
    UATStatus, ReleaseStatus,
)
from templates_config import templates

router = APIRouter(prefix="/qa", tags=["qa-uat"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Any logged-in user can view; admin + inventory_manager + qc_inspector can edit
_view  = get_current_user
_edit  = require_roles(UserRole.admin, UserRole.inventory_manager, UserRole.qc_inspector)
_admin = require_roles(UserRole.admin, UserRole.inventory_manager)


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_recent_commits(days: int = 15) -> list[dict]:
    """Return git commits from the last N days, categorised for the QA dashboard."""
    try:
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--pretty=format:%ad|%s", "--date=short"],
            capture_output=True, text=True, timeout=5, cwd=str(_PROJECT_ROOT),
        )
        commits = []
        for line in result.stdout.strip().splitlines():
            if "|" not in line:
                continue
            date, msg = line.split("|", 1)
            ml = msg.lower()
            if ml.startswith("fix"):
                category, badge = "Bug Fix", "danger"
            elif ml.startswith("feat"):
                category, badge = "Enhancement", "success"
            elif ml.startswith("sprint"):
                category, badge = "Sprint Release", "primary"
            else:
                continue  # skip ci/deploy/merge/docs
            clean = msg.split(":", 1)[-1].strip() if ":" in msg else msg
            commits.append({"date": date, "msg": clean, "category": category, "badge": badge})
        return commits
    except Exception:
        return []


def _s(v: Optional[str]) -> Optional[str]:
    """Return None for blank strings."""
    return v.strip() or None if v else None


def _dt(v: Optional[str]) -> Optional[datetime]:
    """Parse YYYY-MM-DD[THH:MM] into datetime, or return None."""
    if not v or not v.strip():
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(v.strip(), fmt)
        except ValueError:
            continue
    return None


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def qa_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    # Quick counts for KPI cards
    async def _count(model, *filters):
        q = select(func.count()).select_from(model)
        for f in filters:
            q = q.where(f)
        return (await db.execute(q)).scalar() or 0

    # Requirements
    total_reqs   = await _count(QARequirement)
    open_reqs    = await _count(QARequirement, QARequirement.status == RequirementStatus.open)

    # Test cases
    total_tcs    = await _count(QATestCase, QATestCase.status == TestCaseStatus.active)
    automated    = await _count(QATestCase, QATestCase.is_automated == True,
                                QATestCase.status == TestCaseStatus.active)

    # Executions (latest cycle — all-time totals)
    exec_pass    = await _count(QATestExecution, QATestExecution.status == ExecutionStatus.pass_)
    exec_fail    = await _count(QATestExecution, QATestExecution.status == ExecutionStatus.fail)
    exec_total   = await _count(QATestExecution)

    # Defects by status
    def_new      = await _count(QADefect, QADefect.status == DefectStatus.new)
    def_open     = await _count(QADefect, QADefect.status.in_([
                       DefectStatus.new, DefectStatus.assigned,
                       DefectStatus.in_progress, DefectStatus.reopened]))
    def_critical = await _count(QADefect,
                                QADefect.severity == DefectSeverity.critical,
                                QADefect.status.notin_([DefectStatus.closed, DefectStatus.wont_fix]))
    def_total    = await _count(QADefect)

    # UAT
    uat_total    = await _count(QAUATScenario)
    uat_pass     = await _count(QAUATScenario, QAUATScenario.status == UATStatus.pass_)
    uat_pending  = await _count(QAUATScenario, QAUATScenario.status == UATStatus.pending)

    # Releases
    active_rel_res = await db.execute(
        select(QARelease)
        .where(QARelease.status.notin_([ReleaseStatus.deployed, ReleaseStatus.rolled_back]))
        .order_by(QARelease.created_at.desc())
        .limit(5)
    )
    active_releases = active_rel_res.scalars().all()

    # Recent defects (critical/high, open)
    recent_def_res = await db.execute(
        select(QADefect)
        .where(QADefect.status.notin_([DefectStatus.closed, DefectStatus.wont_fix]))
        .where(QADefect.severity.in_([DefectSeverity.critical, DefectSeverity.high]))
        .order_by(QADefect.reported_at.desc())
        .limit(8)
    )
    critical_defects = recent_def_res.scalars().all()

    pass_rate = round(exec_pass / exec_total * 100, 1) if exec_total else 0
    recent_commits = _get_recent_commits(days=15)

    return templates.TemplateResponse("qa/dashboard.html", {
        "request": request, "current_user": current_user,
        "total_reqs": total_reqs, "open_reqs": open_reqs,
        "total_tcs": total_tcs, "automated": automated,
        "exec_pass": exec_pass, "exec_fail": exec_fail,
        "exec_total": exec_total, "pass_rate": pass_rate,
        "def_new": def_new, "def_open": def_open,
        "def_critical": def_critical, "def_total": def_total,
        "uat_total": uat_total, "uat_pass": uat_pass, "uat_pending": uat_pending,
        "active_releases": active_releases,
        "critical_defects": critical_defects,
        "recent_commits": recent_commits,
    })


# ── Requirements ──────────────────────────────────────────────────────────────

@router.get("/requirements", response_class=HTMLResponse)
async def req_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
    status: str = "", module: str = "", priority: str = "",
):
    q = select(QARequirement).order_by(QARequirement.created_at.desc())
    if status:
        q = q.where(QARequirement.status == status)
    if module:
        q = q.where(QARequirement.module.ilike(f"%{module}%"))
    if priority:
        q = q.where(QARequirement.priority == priority)
    res = await db.execute(q)
    reqs = res.scalars().all()
    return templates.TemplateResponse("qa/requirements.html", {
        "request": request, "current_user": current_user,
        "reqs": reqs,
        "statuses": list(RequirementStatus),
        "priorities": list(RequirementPriority),
        "sources": list(RequirementSource),
        "f_status": status, "f_module": module, "f_priority": priority,
    })


@router.post("/requirements/new")
async def req_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    title: str = Form(...),
    description: str = Form(""),
    source: str = Form(RequirementSource.prd),
    priority: str = Form(RequirementPriority.medium),
    module: str = Form(""),
    req_code: str = Form(""),
):
    r = QARequirement(
        req_code=_s(req_code),
        title=title.strip(),
        description=_s(description),
        source=source,
        priority=priority,
        module=_s(module),
        created_by=current_user.full_name or current_user.username,
    )
    db.add(r)
    await db.commit()
    return RedirectResponse(f"/qa/requirements?success=Requirement+added", status_code=303)


@router.post("/requirements/{req_id}/status")
async def req_status(
    req_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    status: str = Form(...),
):
    res = await db.execute(select(QARequirement).where(QARequirement.id == req_id))
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(404)
    r.status = status
    await db.commit()
    return RedirectResponse("/qa/requirements?success=Status+updated", status_code=303)


# ── Test Cases ────────────────────────────────────────────────────────────────

@router.get("/test-cases", response_class=HTMLResponse)
async def tc_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
    module: str = "", type_: str = "", status: str = "",
):
    q = select(QATestCase).order_by(QATestCase.created_at.desc())
    if module:
        q = q.where(QATestCase.module.ilike(f"%{module}%"))
    if type_:
        q = q.where(QATestCase.type == type_)
    if status:
        q = q.where(QATestCase.status == status)
    res = await db.execute(q)
    tcs = res.scalars().all()

    # Get last execution per test case (latest pass/fail)
    last_exec: dict[str, QATestExecution] = {}
    if tcs:
        tc_ids = [tc.id for tc in tcs]
        ex_res = await db.execute(
            select(QATestExecution)
            .where(QATestExecution.test_case_id.in_(tc_ids))
            .order_by(QATestExecution.executed_at.desc())
        )
        for ex in ex_res.scalars().all():
            k = str(ex.test_case_id)
            if k not in last_exec:
                last_exec[k] = ex

    # requirements for dropdown
    req_res = await db.execute(select(QARequirement).order_by(QARequirement.req_code))
    reqs = req_res.scalars().all()

    return templates.TemplateResponse("qa/test_cases.html", {
        "request": request, "current_user": current_user,
        "tcs": tcs, "last_exec": last_exec, "reqs": reqs,
        "tc_types": list(TestCaseType),
        "tc_statuses": list(TestCaseStatus),
        "exec_statuses": list(ExecutionStatus),
        "f_module": module, "f_type": type_, "f_status": status,
    })


@router.post("/test-cases/new")
async def tc_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    tc_code: str = Form(""),
    requirement_id: str = Form(""),
    title: str = Form(...),
    scenario: str = Form(""),
    preconditions: str = Form(""),
    steps: str = Form(""),
    expected_result: str = Form(""),
    type_: str = Form(TestCaseType.functional),
    module: str = Form(""),
    is_automated: bool = Form(False),
):
    tc = QATestCase(
        tc_code=_s(tc_code),
        requirement_id=_s(requirement_id) or None,
        title=title.strip(),
        scenario=_s(scenario),
        preconditions=_s(preconditions),
        steps=_s(steps),
        expected_result=_s(expected_result),
        type=type_,
        module=_s(module),
        is_automated=is_automated,
        created_by=current_user.full_name or current_user.username,
    )
    db.add(tc)
    await db.commit()
    return RedirectResponse("/qa/test-cases?success=Test+case+created", status_code=303)


@router.post("/test-cases/{tc_id}/execute")
async def tc_execute(
    tc_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    status: str = Form(...),
    actual_result: str = Form(""),
    notes: str = Form(""),
    build_version: str = Form(""),
    environment: str = Form("QA"),
):
    res = await db.execute(select(QATestCase).where(QATestCase.id == tc_id))
    tc = res.scalar_one_or_none()
    if not tc:
        raise HTTPException(404)

    ex = QATestExecution(
        test_case_id=tc.id,
        status=status,
        actual_result=_s(actual_result),
        notes=_s(notes),
        build_version=_s(build_version),
        environment=environment,
        executed_by=current_user.full_name or current_user.username,
    )
    db.add(ex)
    await db.commit()
    return RedirectResponse(
        f"/qa/test-cases?success=Execution+logged+({status})", status_code=303
    )


# ── Defects ───────────────────────────────────────────────────────────────────

@router.get("/defects", response_class=HTMLResponse)
async def defect_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
    severity: str = "", status: str = "", module: str = "",
):
    q = select(QADefect).order_by(QADefect.reported_at.desc())
    if severity:
        q = q.where(QADefect.severity == severity)
    if status:
        q = q.where(QADefect.status == status)
    if module:
        q = q.where(QADefect.module.ilike(f"%{module}%"))
    res = await db.execute(q)
    defects = res.scalars().all()

    # test cases for dropdown
    tc_res = await db.execute(
        select(QATestCase)
        .where(QATestCase.status == TestCaseStatus.active)
        .order_by(QATestCase.tc_code)
    )
    tcs = tc_res.scalars().all()

    return templates.TemplateResponse("qa/defects.html", {
        "request": request, "current_user": current_user,
        "defects": defects, "tcs": tcs,
        "severities": list(DefectSeverity),
        "priorities": list(DefectPriority),
        "def_statuses": list(DefectStatus),
        "f_severity": severity, "f_status": status, "f_module": module,
    })


@router.post("/defects/new")
async def defect_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    defect_code: str = Form(""),
    test_case_id: str = Form(""),
    title: str = Form(...),
    description: str = Form(""),
    steps_to_reproduce: str = Form(""),
    expected_result: str = Form(""),
    actual_result: str = Form(""),
    severity: str = Form(DefectSeverity.medium),
    priority: str = Form(DefectPriority.p3),
    module: str = Form(""),
    environment: str = Form("QA"),
    build_version: str = Form(""),
    assigned_to: str = Form(""),
):
    d = QADefect(
        defect_code=_s(defect_code),
        test_case_id=_s(test_case_id) or None,
        title=title.strip(),
        description=_s(description),
        steps_to_reproduce=_s(steps_to_reproduce),
        expected_result=_s(expected_result),
        actual_result=_s(actual_result),
        severity=severity,
        priority=priority,
        module=_s(module),
        environment=environment,
        build_version=_s(build_version),
        assigned_to=_s(assigned_to),
        reported_by=current_user.full_name or current_user.username,
    )
    db.add(d)
    await db.commit()
    return RedirectResponse("/qa/defects?success=Defect+logged", status_code=303)


@router.post("/defects/{defect_id}/status")
async def defect_status(
    defect_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    status: str = Form(...),
    root_cause: str = Form(""),
    resolution: str = Form(""),
):
    res = await db.execute(select(QADefect).where(QADefect.id == defect_id))
    d = res.scalar_one_or_none()
    if not d:
        raise HTTPException(404)
    d.status = status
    if _s(root_cause):
        d.root_cause = root_cause
    if _s(resolution):
        d.resolution = resolution
    if status in (DefectStatus.fixed, "Fixed"):
        d.resolved_at = app_now()
    if status in (DefectStatus.closed, "Closed"):
        d.closed_at = app_now()
    await db.commit()
    return RedirectResponse("/qa/defects?success=Defect+updated", status_code=303)


# ── UAT Scenarios ─────────────────────────────────────────────────────────────

@router.get("/uat", response_class=HTMLResponse)
async def uat_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
    status: str = "",
):
    q = select(QAUATScenario).order_by(QAUATScenario.created_at.desc())
    if status:
        q = q.where(QAUATScenario.status == status)
    res = await db.execute(q)
    scenarios = res.scalars().all()

    req_res = await db.execute(select(QARequirement).order_by(QARequirement.req_code))
    reqs = req_res.scalars().all()

    return templates.TemplateResponse("qa/uat.html", {
        "request": request, "current_user": current_user,
        "scenarios": scenarios, "reqs": reqs,
        "uat_statuses": list(UATStatus),
        "f_status": status,
    })


@router.post("/uat/new")
async def uat_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    uat_code: str = Form(""),
    requirement_id: str = Form(""),
    title: str = Form(...),
    scenario: str = Form(""),
    acceptance_criteria: str = Form(""),
    business_owner: str = Form(""),
):
    s = QAUATScenario(
        uat_code=_s(uat_code),
        requirement_id=_s(requirement_id) or None,
        title=title.strip(),
        scenario=_s(scenario),
        acceptance_criteria=_s(acceptance_criteria),
        business_owner=_s(business_owner),
        created_by=current_user.full_name or current_user.username,
    )
    db.add(s)
    await db.commit()
    return RedirectResponse("/qa/uat?success=UAT+scenario+created", status_code=303)


@router.post("/uat/{uat_id}/execute")
async def uat_execute(
    uat_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_edit),
    status: str = Form(...),
    result_notes: str = Form(""),
    feedback: str = Form(""),
    sign_off: bool = Form(False),
):
    res = await db.execute(select(QAUATScenario).where(QAUATScenario.id == uat_id))
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(404)
    s.status = status
    s.result_notes = _s(result_notes)
    s.feedback = _s(feedback)
    s.executed_by = current_user.full_name or current_user.username
    s.executed_at = app_now()
    if sign_off:
        s.sign_off_by = current_user.full_name or current_user.username
        s.sign_off_at = app_now()
    await db.commit()
    return RedirectResponse("/qa/uat?success=UAT+result+recorded", status_code=303)


# ── Releases ──────────────────────────────────────────────────────────────────

@router.get("/releases", response_class=HTMLResponse)
async def release_list(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    res = await db.execute(
        select(QARelease).order_by(QARelease.created_at.desc())
    )
    releases = res.scalars().all()
    return templates.TemplateResponse("qa/releases.html", {
        "request": request, "current_user": current_user,
        "releases": releases,
        "rel_statuses": list(ReleaseStatus),
    })


@router.post("/releases/new")
async def release_create(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
    version: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    planned_date: str = Form(""),
    rollback_plan: str = Form(""),
    notes: str = Form(""),
):
    r = QARelease(
        version=version.strip(),
        title=_s(title),
        description=_s(description),
        planned_date=_dt(planned_date),
        rollback_plan=_s(rollback_plan),
        notes=_s(notes),
        created_by=current_user.full_name or current_user.username,
    )
    db.add(r)
    await db.commit()
    return RedirectResponse("/qa/releases?success=Release+created", status_code=303)


@router.post("/releases/{rel_id}/status")
async def release_status(
    rel_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin),
    status: str = Form(...),
    notes: str = Form(""),
):
    res = await db.execute(select(QARelease).where(QARelease.id == rel_id))
    r = res.scalar_one_or_none()
    if not r:
        raise HTTPException(404)
    r.status = status
    now = app_now()
    actor = current_user.full_name or current_user.username
    if status == ReleaseStatus.qa_done:
        r.qa_sign_off_by = actor
        r.qa_sign_off_at = now
    elif status == ReleaseStatus.uat_done:
        r.uat_sign_off_by = actor
        r.uat_sign_off_at = now
    elif status == ReleaseStatus.deployed:
        r.deployed_by = actor
        r.release_date = now
    if _s(notes):
        r.notes = (r.notes or "") + f"\n[{now.strftime('%d-%m-%Y %H:%M')}] {notes}"
    await db.commit()
    return RedirectResponse("/qa/releases?success=Release+status+updated", status_code=303)


# ── RTM ───────────────────────────────────────────────────────────────────────

@router.get("/rtm", response_class=HTMLResponse)
async def rtm_view(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_view),
):
    req_res = await db.execute(
        select(QARequirement).order_by(QARequirement.req_code, QARequirement.created_at)
    )
    reqs = req_res.scalars().all()

    # For each requirement load test cases with their latest execution
    rtm_rows = []
    for req in reqs:
        tc_res = await db.execute(
            select(QATestCase)
            .where(QATestCase.requirement_id == req.id)
            .where(QATestCase.status == TestCaseStatus.active)
        )
        tcs = tc_res.scalars().all()

        # Last execution per test case
        last_exec: dict[str, QATestExecution] = {}
        if tcs:
            ex_res = await db.execute(
                select(QATestExecution)
                .where(QATestExecution.test_case_id.in_([t.id for t in tcs]))
                .order_by(QATestExecution.executed_at.desc())
            )
            for ex in ex_res.scalars().all():
                k = str(ex.test_case_id)
                if k not in last_exec:
                    last_exec[k] = ex

        # UAT scenarios for this requirement
        uat_res = await db.execute(
            select(QAUATScenario)
            .where(QAUATScenario.requirement_id == req.id)
        )
        uats = uat_res.scalars().all()

        rtm_rows.append({
            "req": req,
            "test_cases": tcs,
            "last_exec": last_exec,
            "uat_scenarios": uats,
        })

    # Uncovered requirements (no test cases at all)
    uncovered = [r for r in rtm_rows if not r["test_cases"]]

    return templates.TemplateResponse("qa/rtm.html", {
        "request": request, "current_user": current_user,
        "rtm_rows": rtm_rows,
        "uncovered": uncovered,
        "total_reqs": len(reqs),
        "covered_reqs": len([r for r in rtm_rows if r["test_cases"]]),
    })
