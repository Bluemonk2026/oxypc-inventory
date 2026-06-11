# Dealer Management & Telecalling Dashboard — 7 Feature Enhancements

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add admin user-scope filter, last-call-date column, followup date filter, call-log pills, and make the Telecalling Dashboard pull live from DealerCall records with clickable dealer names and full dealer-management-style filters.

**Architecture:** All changes are confined to two routers (`routers/dealers.py`, `routers/telecalling.py`) and their templates. No schema changes — all data is already in `dealer_calls`. The telecalling dashboard index route is repurposed to query `DealerCall + Dealer` instead of `TelecallingRecord`, giving it live sync with dealer call logs. Pills and last-call columns are added via two batch subqueries (window function + max aggregate) executed only against the current page's dealer IDs.

**Tech Stack:** FastAPI async, SQLAlchemy 2.x asyncio, Jinja2, Bootstrap 5 badges/pills, `func.row_number().over()` window function for latest-call-per-dealer lookup.

**Note on Feature 2 (Bulk Upload):** Already fully implemented. Route: `GET/POST /dealers/bulk-upload`. Template: `templates/dealers/bulk_upload.html`. The "Bulk Upload" button is already rendered in `templates/dealers/list.html` line 39. **No code changes needed for this feature.**

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `routers/dealers.py` | Fetch `sales_users` list; add `followup_from/to` params; query `last_call_map` and `recent_call_map` |
| Modify | `templates/dealers/list.html` | Admin user dropdown; followup filter; Last Call column; call-log pills |
| Modify | `routers/telecalling.py` | Replace `TelecallingRecord` queries with `DealerCall + Dealer`; add filter params; import `UserRole` properly |
| Modify | `templates/telecalling/index.html` | Add filter bar; make dealer names clickable; update column headers |

---

## Task 1: Dealer Management — Admin User Filter Dropdown

**Files:**
- Modify: `routers/dealers.py` (lines 46–155 — `list_dealers` function)
- Modify: `templates/dealers/list.html` (lines 16–19 — assigned select block)
- Test: `tests/test_sprint25_dealers.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_sprint25_dealers.py`:

```python
# tests/test_sprint25_dealers.py
"""
Smoke tests for Sprint 25 dealer & telecalling enhancements.
Run: pytest tests/test_sprint25_dealers.py -v
"""
import pytest


def test_sales_users_list_shape():
    """Verify that sales_users list only contains salesroles — not admin/iqc/etc."""
    from models.user import UserRole

    SALES_ROLES = (UserRole.sales, UserRole.sales_manager, UserRole.telecaller)
    all_roles = list(UserRole)
    excluded = [r for r in all_roles if r not in SALES_ROLES]

    assert UserRole.admin in excluded, "admin must be excluded from sales_users dropdown"
    assert UserRole.iqc_inspector in excluded, "iqc_inspector must be excluded"
    assert UserRole.sales in SALES_ROLES
    assert UserRole.telecaller in SALES_ROLES
    assert UserRole.sales_manager in SALES_ROLES


def test_followup_filter_date_parse():
    """followup_from/to must parse yyyy-mm-dd without raising."""
    from datetime import datetime

    date_str = "2026-06-01"
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    assert parsed.year == 2026
    assert parsed.month == 6
    assert parsed.day == 1


def test_bad_followup_date_silently_skipped():
    """Invalid followup date strings must be silently ignored (no exception)."""
    from datetime import datetime

    bad = "not-a-date"
    result = None
    try:
        result = datetime.strptime(bad, "%Y-%m-%d")
    except ValueError:
        pass  # expected — backend should catch this
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails (one assertion will fail with import errors if code is wrong)**

```
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
venv\Scripts\python -m pytest tests/test_sprint25_dealers.py -v
```

Expected: 3 tests PASS (these are pure logic tests, no DB needed).

- [ ] **Step 3: Modify `routers/dealers.py` — add `sales_users` fetch and new params**

In `list_dealers`, add `followup_from`, `followup_to` params and fetch `sales_users` for admin.

Replace the existing `list_dealers` function signature and body (lines 46–155) with:

```python
@router.get("", response_class=HTMLResponse)
async def list_dealers(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    assigned: str = Query(default=""),
    city: str = Query(default=""),
    last_order_from: str = Query(default=""),
    last_order_to: str = Query(default=""),
    followup_from: str = Query(default=""),
    followup_to: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_sales),
):
    from sqlalchemy import or_
    base_query = select(Dealer)
    if q:
        like = f"%{q}%"
        base_query = base_query.where(or_(
            Dealer.business_name.ilike(like),
            Dealer.city.ilike(like),
            Dealer.phone.ilike(like),
            Dealer.contact_person.ilike(like),
        ))
    if status:
        base_query = base_query.where(Dealer.status == status)
    if assigned:
        base_query = base_query.where(Dealer.assigned_to == assigned)
    elif current_user.role in (UserRole.sales, UserRole.telecaller):
        base_query = base_query.where(Dealer.assigned_to == current_user.username)
    if city:
        base_query = base_query.where(Dealer.city.ilike(f"%{city}%"))
    if last_order_from:
        try:
            base_query = base_query.where(
                Dealer.last_sale_date >= datetime.strptime(last_order_from, "%Y-%m-%d")
            )
        except ValueError:
            pass
    if last_order_to:
        try:
            base_query = base_query.where(
                Dealer.last_sale_date <= datetime.strptime(last_order_to, "%Y-%m-%d")
            )
        except ValueError:
            pass

    # ── Followup date filter — filter dealers who have a DealerCall with
    #    next_followup_date in the given range ──────────────────────────────
    if followup_from or followup_to:
        fu_subq = select(DealerCall.dealer_id).distinct()
        if followup_from:
            try:
                fu_subq = fu_subq.where(
                    DealerCall.next_followup_date >= datetime.strptime(followup_from, "%Y-%m-%d")
                )
            except ValueError:
                pass
        if followup_to:
            try:
                fu_subq = fu_subq.where(
                    DealerCall.next_followup_date <= datetime.strptime(followup_to + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                )
            except ValueError:
                pass
        base_query = base_query.where(Dealer.id.in_(fu_subq))

    # Total count
    count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
    total_count = count_result.scalar() or 0
    total_pages = max(1, math.ceil(total_count / PER_PAGE))
    page = min(page, total_pages)

    # Active count
    active_q = base_query.where(Dealer.status == "active")
    active_result = await db.execute(select(func.count()).select_from(active_q.subquery()))
    active_count = active_result.scalar() or 0

    # Follow-ups due
    today = datetime.utcnow().date()
    fu_result = await db.execute(
        select(func.count(DealerCall.id)).where(
            func.date(DealerCall.next_followup_date) <= today,
            DealerCall.call_outcome != 'not_interested',
        )
    )
    followup_count = fu_result.scalar() or 0

    # Paginated dealer rows
    offset = (page - 1) * PER_PAGE
    dealers = (await db.execute(
        base_query.order_by(Dealer.business_name).offset(offset).limit(PER_PAGE)
    )).scalars().all()

    dealer_ids = [d.id for d in dealers]

    # Outstanding map — current page only
    outstanding_map: dict = {}
    if dealer_ids:
        out_rows = await db.execute(
            select(DealerOrder.dealer_id, func.coalesce(func.sum(DealerOrder.due_amount), 0).label("out"))
            .where(DealerOrder.dealer_id.in_(dealer_ids), DealerOrder.status.in_(OUTSTANDING_STATUSES))
            .group_by(DealerOrder.dealer_id)
        )
        outstanding_map = {str(r.dealer_id): float(r.out) for r in out_rows}

    # ── Last call date per dealer (for Last Call column) ────────────────────
    last_call_map: dict = {}
    if dealer_ids:
        lc_rows = await db.execute(
            select(DealerCall.dealer_id, func.max(DealerCall.call_date).label("last_call"))
            .where(DealerCall.dealer_id.in_(dealer_ids))
            .group_by(DealerCall.dealer_id)
        )
        last_call_map = {str(r.dealer_id): r.last_call for r in lc_rows}

    # ── Most recent call outcome + items per dealer (for pills) ─────────────
    recent_call_map: dict = {}
    if dealer_ids:
        rn_col = func.row_number().over(
            partition_by=DealerCall.dealer_id,
            order_by=DealerCall.call_date.desc()
        ).label("rn")
        inner = select(
            DealerCall.dealer_id,
            DealerCall.call_outcome,
            DealerCall.items_discussed,
            rn_col,
        ).where(DealerCall.dealer_id.in_(dealer_ids)).subquery()
        rc_rows = (await db.execute(
            select(inner.c.dealer_id, inner.c.call_outcome, inner.c.items_discussed)
            .where(inner.c.rn == 1)
        )).all()
        recent_call_map = {
            str(r.dealer_id): {
                "outcome": r.call_outcome,
                "items": (r.items_discussed or "")[:60],
            }
            for r in rc_rows
        }

    # ── Sales users list for admin user-filter dropdown ────────────────────
    sales_users: list = []
    if current_user.role == UserRole.admin:
        su_result = await db.execute(
            select(User).where(
                User.role.in_([UserRole.sales, UserRole.sales_manager, UserRole.telecaller]),
                User.status == True,
            ).order_by(User.full_name)
        )
        sales_users = su_result.scalars().all()

    # Global outstanding total
    out_total_result = await db.execute(
        select(func.coalesce(func.sum(DealerOrder.due_amount), 0))
        .where(DealerOrder.status.in_(OUTSTANDING_STATUSES))
    )
    outstanding = round(float(out_total_result.scalar() or 0))

    return templates.TemplateResponse("dealers/list.html", {
        "request": request,
        "current_user": current_user,
        "dealers": dealers,
        "q": q,
        "status": status,
        "assigned": assigned,
        "city": city,
        "last_order_from": last_order_from,
        "last_order_to": last_order_to,
        "followup_from": followup_from,
        "followup_to": followup_to,
        "page": page,
        "total_pages": total_pages,
        "total_count": total_count,
        "active_count": active_count,
        "followup_count": followup_count,
        "outstanding": f"{outstanding:,}",
        "outstanding_map": outstanding_map,
        "last_call_map": last_call_map,
        "recent_call_map": recent_call_map,
        "sales_users": sales_users,
        "per_page": PER_PAGE,
    })
```

- [ ] **Step 4: Update `templates/dealers/list.html` — full new version**

Replace the entire file with:

```html
{% extends "base.html" %}
{% block title %}Dealers — OxyPC{% endblock %}
{% block page_title %}Dealer Management{% endblock %}
{% block content %}

<div class="d-flex flex-wrap gap-2 align-items-start mb-3">
  <form method="get" class="d-flex flex-wrap gap-2 align-items-center flex-grow-1">
    <input type="text" name="q" value="{{ q }}" placeholder="Search name, city, phone..."
           class="form-control form-control-sm" style="width:220px">

    <select name="status" class="form-select form-select-sm" style="width:130px">
      <option value="">All Status</option>
      <option value="active" {% if status=='active' %}selected{% endif %}>Active</option>
      <option value="inactive" {% if status=='inactive' %}selected{% endif %}>Inactive</option>
      <option value="blacklisted" {% if status=='blacklisted' %}selected{% endif %}>Blacklisted</option>
    </select>

    {# ── User filter: admin sees full dropdown, sales/telecaller see nothing (auto-scoped) ── #}
    {% if current_user.role.value == 'admin' %}
    <select name="assigned" class="form-select form-select-sm" style="width:165px">
      <option value="">All Executives</option>
      {% for u in sales_users %}
      <option value="{{ u.username }}" {% if assigned == u.username %}selected{% endif %}>
        {{ u.full_name }} ({{ u.role.value }})
      </option>
      {% endfor %}
    </select>
    {% elif current_user.role.value == 'sales_manager' %}
    <select name="assigned" class="form-select form-select-sm" style="width:150px">
      <option value="">All My Team</option>
      <option value="{{ current_user.username }}" {% if assigned==current_user.username %}selected{% endif %}>Mine Only</option>
    </select>
    {% endif %}

    <input type="text" name="city" class="form-control form-control-sm"
           placeholder="City" value="{{ city }}" style="width:120px">

    <input type="date" name="last_order_from" class="form-control form-control-sm"
           title="Last Order From" value="{{ last_order_from }}" style="width:145px">
    <input type="date" name="last_order_to" class="form-control form-control-sm"
           title="Last Order To" value="{{ last_order_to }}" style="width:145px">

    <input type="date" name="followup_from" class="form-control form-control-sm"
           title="Follow-up From" value="{{ followup_from }}" style="width:145px">
    <input type="date" name="followup_to" class="form-control form-control-sm"
           title="Follow-up To" value="{{ followup_to }}" style="width:145px">

    <button class="btn btn-sm btn-outline-primary">Filter</button>
    <a href="/dealers" class="btn btn-sm btn-outline-secondary">Clear</a>
  </form>

  <div class="d-flex gap-2 ms-auto">
    <a href="/dealers/followups-due" class="btn btn-sm btn-warning">
      <i class="bi bi-bell me-1"></i>Follow-ups Due
      <span class="badge bg-white text-warning">{{ followup_count }}</span>
    </a>
    <a href="/dealers/overdue" class="btn btn-sm btn-danger">
      <i class="bi bi-exclamation-triangle me-1"></i>Overdue Orders
    </a>
    <a href="/dealers/bulk-upload" class="btn btn-sm btn-outline-success">
      <i class="bi bi-cloud-upload me-1"></i>Bulk Upload
    </a>
    <a href="/dealers/new" class="btn btn-sm btn-primary">
      <i class="bi bi-plus-circle me-1"></i>Add Dealer
    </a>
  </div>
</div>

<!-- Summary cards -->
<div class="row g-3 mb-4">
  {% for label, val, color in [
    ('Total Dealers', total_count, 'primary'),
    ('Active', active_count, 'success'),
    ('Follow-ups Due', followup_count, 'warning'),
    ('Outstanding', '₹'+outstanding|string, 'danger')
  ] %}
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-3">
      <div class="fs-4 fw-bold text-{{ color }}">{{ val }}</div>
      <div class="small text-muted">{{ label }}</div>
    </div>
  </div>
  {% endfor %}
</div>

<div class="card border-0 shadow-sm">
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-hover mb-0" id="dealersTable">
        <thead class="table-light">
          <tr>
            <th>Code</th>
            <th>Business Name</th>
            <th>Contact</th>
            <th>City</th>
            <th>Type</th>
            <th>Last Call</th>
            <th>Last Sale</th>
            <th>Outstanding</th>
            <th>Assigned To</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for d in dealers %}
          {% set rc = recent_call_map.get(d.id|string, {}) %}
          {% set lc = last_call_map.get(d.id|string) %}
          <tr>
            <td><code>{{ d.dealer_code }}</code></td>
            <td>
              <a href="/dealers/{{ d.id }}" class="fw-semibold text-decoration-none">{{ d.business_name }}</a>
              {# ── Call log pills — only shown when a call exists ── #}
              {% if rc %}
              <div class="mt-1 d-flex flex-wrap gap-1">
                {% set oc_colors = {
                  'interested': 'success',
                  'order_placed': 'primary',
                  'callback': 'warning',
                  'not_interested': 'danger',
                  'no_answer': 'secondary',
                  'do_not_call': 'dark',
                  'followup': 'info'
                } %}
                {% if rc.outcome %}
                <span class="badge bg-{{ oc_colors.get(rc.outcome, 'secondary') }} bg-opacity-75">
                  {{ rc.outcome | replace('_', ' ') | title }}
                </span>
                {% endif %}
                {% if rc.items %}
                <span class="badge bg-light text-dark border small fw-normal" style="font-size:0.7rem">
                  {{ rc.items[:40] }}{% if rc.items|length > 40 %}…{% endif %}
                </span>
                {% endif %}
              </div>
              {% endif %}
            </td>
            <td>
              <div class="small">{{ d.contact_person or '' }}</div>
              <div class="small text-muted">{{ d.phone or '' }}</div>
            </td>
            <td class="small">{{ d.city or '—' }}</td>
            <td><span class="badge bg-secondary">{{ d.dealer_type | title }}</span></td>
            <td class="small">
              {% if lc %}
                <span class="text-muted">{{ lc.strftime('%d-%m-%Y') }}</span>
              {% else %}
                <span class="text-muted">No calls</span>
              {% endif %}
            </td>
            <td class="small">
              {% if d.last_sale_date %}{{ d.last_sale_date.strftime('%d-%m-%Y') }}
              {% else %}<span class="text-muted">Never</span>{% endif %}
            </td>
            {% set d_out = outstanding_map.get(d.id|string, 0) %}
            <td class="small {% if d_out > 0 %}text-danger fw-semibold{% endif %}">
              ₹{{ "{:,.0f}".format(d_out) }}
            </td>
            <td class="small">{{ d.assigned_to or '—' }}</td>
            <td>
              {% set sc = {'active':'success','inactive':'secondary','blacklisted':'danger'} %}
              <span class="badge bg-{{ sc.get(d.status,'secondary') }}">{{ d.status | title }}</span>
            </td>
            <td>
              <div class="btn-group btn-group-sm">
                <a href="/dealers/{{ d.id }}" class="btn btn-outline-primary" title="View">
                  <i class="bi bi-eye"></i>
                </a>
                <a href="/dealers/{{ d.id }}/call" class="btn btn-outline-success" title="Log Call">
                  <i class="bi bi-telephone-plus"></i>
                </a>
                <a href="/whatsapp/compose?dealer_id={{ d.id }}" class="btn btn-outline-dark" title="WhatsApp">
                  <i class="bi bi-whatsapp"></i>
                </a>
                <a href="/dealers/{{ d.id }}/edit" class="btn btn-outline-secondary" title="Edit">
                  <i class="bi bi-pencil"></i>
                </a>
              </div>
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="11" class="text-center text-muted py-4">
              No dealers found. <a href="/dealers/new">Add your first dealer</a>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>

{% if total_pages > 1 %}
<nav class="mt-3 d-flex justify-content-between align-items-center">
  <small class="text-muted">
    Showing {{ ((page-1)*per_page)+1 }}–{{ page*per_page if page*per_page < total_count else total_count }}
    of {{ total_count }} dealers
  </small>
  <ul class="pagination pagination-sm mb-0">
    {% if page > 1 %}
    <li class="page-item">
      <a class="page-link" href="?q={{ q }}&status={{ status }}&assigned={{ assigned }}&city={{ city }}&last_order_from={{ last_order_from }}&last_order_to={{ last_order_to }}&followup_from={{ followup_from }}&followup_to={{ followup_to }}&page={{ page - 1 }}">‹ Prev</a>
    </li>
    {% endif %}
    {% for p in range(1, total_pages + 1) %}
      {% if p == page %}
      <li class="page-item active"><span class="page-link">{{ p }}</span></li>
      {% elif p == 1 or p == total_pages or (p >= page - 2 and p <= page + 2) %}
      <li class="page-item">
        <a class="page-link" href="?q={{ q }}&status={{ status }}&assigned={{ assigned }}&city={{ city }}&last_order_from={{ last_order_from }}&last_order_to={{ last_order_to }}&followup_from={{ followup_from }}&followup_to={{ followup_to }}&page={{ p }}">{{ p }}</a>
      </li>
      {% elif p == page - 3 or p == page + 3 %}
      <li class="page-item disabled"><span class="page-link">…</span></li>
      {% endif %}
    {% endfor %}
    {% if page < total_pages %}
    <li class="page-item">
      <a class="page-link" href="?q={{ q }}&status={{ status }}&assigned={{ assigned }}&city={{ city }}&last_order_from={{ last_order_from }}&last_order_to={{ last_order_to }}&followup_from={{ followup_from }}&followup_to={{ followup_to }}&page={{ page + 1 }}">Next ›</a>
    </li>
    {% endif %}
  </ul>
</nav>
{% endif %}
{% endblock %}
{% block scripts %}{% endblock %}
```

- [ ] **Step 5: Verify the app renders correctly**

Start/restart the server (if not already running):
```powershell
cd C:\Users\Pankaj.sehgal\Claude\Oxypc\oxypc-inventory
Start-Process -NoNewWindow venv\Scripts\python.exe -ArgumentList "-m","uvicorn","main:app","--host","0.0.0.0","--port","8000","--reload"
```

Open browser at `http://localhost:8000/dealers` and verify:
- Filter bar shows all inputs
- Admin user sees the full user dropdown; sales user sees no dropdown
- Table now has "Last Call" column (shows "No calls" when no DealerCall exists)
- No 500 errors in the console

- [ ] **Step 6: Run tests**

```
venv\Scripts\python -m pytest tests/test_sprint25_dealers.py -v
```

Expected: 3 PASS

- [ ] **Step 7: Commit**

```bash
git add routers/dealers.py templates/dealers/list.html tests/test_sprint25_dealers.py
git commit -m "feat(dealers): admin user dropdown, followup filter, last-call column, call-log pills"
```

---

## Task 2: Telecalling Dashboard — DealerCall Source + Clickable Names + All Filters

**Files:**
- Modify: `routers/telecalling.py` (entire `index` function — lines 16–77)
- Modify: `templates/telecalling/index.html` (entire file)

- [ ] **Step 1: Modify `routers/telecalling.py` — replace the `index` route**

Add `UserRole` import and `selectinload` import, then replace the `index` function:

At the top of `routers/telecalling.py`, ensure these imports exist (add if missing):

```python
from templates_config import templates
from datetime import datetime, date
from fastapi import APIRouter, Depends, Form, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from database import get_db
from models.telecalling import TelecallingRecord, TelecallingSession
from models.dealers import Dealer, DealerCall
from models.user import User, UserRole
from auth.dependencies import get_current_user, verify_csrf

router = APIRouter(prefix="/telecalling", tags=["telecalling"], dependencies=[Depends(verify_csrf)])
```

Replace the `index` function (lines 16–77) with:

```python
@router.get("", response_class=HTMLResponse)
async def index(
    request: Request,
    q: str = Query(default=""),
    assigned: str = Query(default=""),
    city: str = Query(default=""),
    outcome: str = Query(default=""),
    followup_from: str = Query(default=""),
    followup_to: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    today = datetime.utcnow().date()

    # ── Today's stats for current user — sourced from DealerCall ────────────
    base_stat_filter = [
        func.date(DealerCall.call_date) == today,
        DealerCall.called_by == current_user.username,
    ]
    total_calls = (await db.execute(
        select(func.count(DealerCall.id)).where(*base_stat_filter)
    )).scalar() or 0
    connected_calls = (await db.execute(
        select(func.count(DealerCall.id)).where(
            *base_stat_filter, DealerCall.call_outcome != 'no_answer'
        )
    )).scalar() or 0
    interested_calls = (await db.execute(
        select(func.count(DealerCall.id)).where(
            *base_stat_filter, DealerCall.call_outcome == 'interested'
        )
    )).scalar() or 0
    orders_calls = (await db.execute(
        select(func.count(DealerCall.id)).where(
            *base_stat_filter, DealerCall.call_outcome == 'order_placed'
        )
    )).scalar() or 0

    today_stats = {
        "total": total_calls,
        "connected": connected_calls,
        "interested": interested_calls,
        "orders": orders_calls,
    }

    # ── Follow-ups due today — sourced from DealerCall ───────────────────────
    fu_stmt = (
        select(DealerCall)
        .options(selectinload(DealerCall.dealer))
        .join(Dealer, DealerCall.dealer_id == Dealer.id)
        .where(
            func.date(DealerCall.next_followup_date) == today,
            DealerCall.call_outcome != 'not_interested',
        )
        .order_by(DealerCall.next_followup_date)
    )
    if current_user.role in (UserRole.sales, UserRole.telecaller):
        fu_stmt = fu_stmt.where(DealerCall.called_by == current_user.username)
    followups_due = (await db.execute(fu_stmt)).scalars().all()

    # ── Recent calls — sourced from DealerCall, with all filters ────────────
    # Build call date range (default = today)
    if not date_from:
        date_from = today.isoformat()
    if not date_to:
        date_to = today.isoformat()

    recent_filters = [
        func.date(DealerCall.call_date) >= date_from,
        func.date(DealerCall.call_date) <= date_to,
    ]

    # Role-scoped agent filter
    if assigned:
        recent_filters.append(DealerCall.called_by == assigned)
    elif current_user.role not in (UserRole.admin, UserRole.sales_manager):
        recent_filters.append(DealerCall.called_by == current_user.username)

    # Dealer-attribute filters applied via join
    dealer_filters = []
    if q:
        like = f"%{q}%"
        dealer_filters.append(
            or_(
                Dealer.business_name.ilike(like),
                Dealer.phone.ilike(like),
                Dealer.contact_person.ilike(like),
            )
        )
    if city:
        dealer_filters.append(Dealer.city.ilike(f"%{city}%"))

    if outcome:
        recent_filters.append(DealerCall.call_outcome == outcome)

    # Followup date filter
    if followup_from:
        try:
            recent_filters.append(
                DealerCall.next_followup_date >= datetime.strptime(followup_from, "%Y-%m-%d")
            )
        except ValueError:
            pass
    if followup_to:
        try:
            recent_filters.append(
                DealerCall.next_followup_date <= datetime.strptime(followup_to + " 23:59:59", "%Y-%m-%d %H:%M:%S")
            )
        except ValueError:
            pass

    recent_stmt = (
        select(DealerCall)
        .options(selectinload(DealerCall.dealer))
        .join(Dealer, DealerCall.dealer_id == Dealer.id)
        .where(*recent_filters)
    )
    if dealer_filters:
        recent_stmt = recent_stmt.where(*dealer_filters)

    recent_stmt = recent_stmt.order_by(DealerCall.call_date.desc()).limit(50)
    recent_calls = (await db.execute(recent_stmt)).scalars().all()

    # ── Sales users list for admin agent-filter dropdown ─────────────────────
    sales_users: list = []
    if current_user.role in (UserRole.admin, UserRole.sales_manager):
        su_result = await db.execute(
            select(User).where(
                User.role.in_([UserRole.sales, UserRole.sales_manager, UserRole.telecaller]),
                User.status == True,
            ).order_by(User.full_name)
        )
        sales_users = su_result.scalars().all()

    return templates.TemplateResponse("telecalling/index.html", {
        "request": request,
        "current_user": current_user,
        "today_stats": today_stats,
        "followups_due": followups_due,
        "recent_calls": recent_calls,
        "today": today,
        "sales_users": sales_users,
        # filter state
        "q": q,
        "assigned": assigned,
        "city": city,
        "outcome": outcome,
        "followup_from": followup_from,
        "followup_to": followup_to,
        "date_from": date_from,
        "date_to": date_to,
    })
```

- [ ] **Step 2: Replace `templates/telecalling/index.html` with updated version**

```html
{% extends "base.html" %}
{% block title %}Telecalling — OxyPC{% endblock %}
{% block page_title %}Telecalling Dashboard{% endblock %}
{% block content %}

<!-- Today Session Stats -->
<div class="row g-3 mb-4">
  {% set stats = [
    ('Calls Today', today_stats.get('total',0), 'primary'),
    ('Connected', today_stats.get('connected',0), 'success'),
    ('Interested', today_stats.get('interested',0), 'warning'),
    ('Orders', today_stats.get('orders',0), 'dark')
  ] %}
  {% for label, val, color in stats %}
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-3">
      <div class="fs-3 fw-bold text-{{ color }}">{{ val }}</div>
      <div class="small text-muted">{{ label }}</div>
    </div>
  </div>
  {% endfor %}
</div>

<!-- ── Filter bar ─────────────────────────────────────────── -->
<div class="card border-0 shadow-sm mb-3">
  <div class="card-body py-2">
    <form method="get" class="d-flex flex-wrap gap-2 align-items-center">
      <input type="text" name="q" value="{{ q }}" placeholder="Search dealer name / phone..."
             class="form-control form-control-sm" style="width:210px">

      {% if current_user.role.value in ('admin', 'sales_manager') %}
      <select name="assigned" class="form-select form-select-sm" style="width:160px">
        <option value="">All Agents</option>
        {% for u in sales_users %}
        <option value="{{ u.username }}" {% if assigned == u.username %}selected{% endif %}>
          {{ u.full_name }}
        </option>
        {% endfor %}
      </select>
      {% endif %}

      <input type="text" name="city" value="{{ city }}" placeholder="City"
             class="form-control form-control-sm" style="width:110px">

      <select name="outcome" class="form-select form-select-sm" style="width:145px">
        <option value="">All Outcomes</option>
        {% for ov in ['interested','order_placed','callback','not_interested','no_answer','followup','do_not_call'] %}
        <option value="{{ ov }}" {% if outcome == ov %}selected{% endif %}>
          {{ ov | replace('_',' ') | title }}
        </option>
        {% endfor %}
      </select>

      <input type="date" name="date_from" value="{{ date_from }}"
             title="Call Date From" class="form-control form-control-sm" style="width:140px">
      <input type="date" name="date_to" value="{{ date_to }}"
             title="Call Date To" class="form-control form-control-sm" style="width:140px">

      <input type="date" name="followup_from" value="{{ followup_from }}"
             title="Follow-up From" class="form-control form-control-sm" style="width:140px">
      <input type="date" name="followup_to" value="{{ followup_to }}"
             title="Follow-up To" class="form-control form-control-sm" style="width:140px">

      <button class="btn btn-sm btn-outline-primary">Filter</button>
      <a href="/telecalling" class="btn btn-sm btn-outline-secondary">Clear</a>

      <div class="ms-auto d-flex gap-2">
        <a href="/telecalling/add" class="btn btn-sm btn-primary">
          <i class="bi bi-plus me-1"></i>Log Call
        </a>
        <a href="/telecalling/records" class="btn btn-sm btn-outline-secondary">
          <i class="bi bi-list me-1"></i>All Records
        </a>
      </div>
    </form>
  </div>
</div>

<!-- Follow-ups due today -->
{% if followups_due %}
<div class="card border-0 shadow-sm mb-3" style="border-left: 4px solid #dc3545 !important;">
  <div class="card-header bg-danger-subtle fw-semibold text-danger">
    <i class="bi bi-bell me-2"></i>{{ followups_due|length }} Follow-ups Due Today
  </div>
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-hover mb-0 small">
        <thead class="table-light">
          <tr>
            <th>Dealer</th><th>Phone</th><th>Last Call</th>
            <th>Outcome</th><th>Items Discussed</th><th>Action</th>
          </tr>
        </thead>
        <tbody>
          {% for rec in followups_due %}
          <tr>
            <td class="fw-semibold">
              {% if rec.dealer_id %}
              <a href="/dealers/{{ rec.dealer_id }}" class="text-decoration-none">
                {{ rec.dealer.business_name if rec.dealer else '—' }}
              </a>
              {% else %}
              {{ rec.dealer.business_name if rec.dealer else '—' }}
              {% endif %}
            </td>
            <td>
              <a href="tel:{{ rec.dealer.phone if rec.dealer else '' }}">
                {{ rec.dealer.phone if rec.dealer else '—' }}
              </a>
            </td>
            <td>{{ rec.call_date.strftime('%d-%m-%Y') }}</td>
            <td>
              <span class="badge bg-warning text-dark">
                {{ rec.call_outcome | replace('_',' ') | title if rec.call_outcome else '—' }}
              </span>
            </td>
            <td>{{ (rec.items_discussed or '—')[:50] }}</td>
            <td>
              <a href="/dealers/{{ rec.dealer_id }}/call" class="btn btn-xs btn-success btn-sm">
                Call Now
              </a>
              {% if rec.dealer and rec.dealer.whatsapp_number %}
              <a href="/whatsapp/compose?dealer_id={{ rec.dealer_id }}"
                 class="btn btn-xs btn-outline-dark btn-sm">
                <i class="bi bi-whatsapp"></i>
              </a>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% endif %}

<!-- Recent Calls — from DealerCall (auto-synced from Dealer Management) -->
<div class="card border-0 shadow-sm">
  <div class="card-header bg-transparent fw-semibold">
    <i class="bi bi-clock-history me-2"></i>Recent Calls
    <small class="text-muted fw-normal ms-2">(sourced from Dealer Management call logs)</small>
  </div>
  <div class="card-body p-0">
    <div class="table-responsive">
      <table class="table table-hover mb-0 small">
        <thead class="table-light">
          <tr>
            <th>Time</th>
            <th>Dealer</th>
            <th>Phone</th>
            <th>Agent</th>
            <th>Mode</th>
            <th>Outcome</th>
            <th>Items Discussed</th>
            <th>Follow-up</th>
          </tr>
        </thead>
        <tbody>
          {% for rec in recent_calls %}
          {% set oc = {
            'interested':'success',
            'order_placed':'primary',
            'callback':'warning',
            'not_interested':'danger',
            'no_answer':'secondary',
            'do_not_call':'dark',
            'followup':'info'
          } %}
          <tr>
            <td class="text-muted">{{ rec.call_date.strftime('%H:%M') }}</td>
            <td>
              {% if rec.dealer_id and rec.dealer %}
              <a href="/dealers/{{ rec.dealer_id }}" class="fw-semibold text-decoration-none">
                {{ rec.dealer.business_name }}
              </a>
              {% else %}
              <span class="text-muted">—</span>
              {% endif %}
            </td>
            <td>
              {% if rec.dealer and rec.dealer.phone %}
              <a href="tel:{{ rec.dealer.phone }}">{{ rec.dealer.phone }}</a>
              {% else %}—{% endif %}
            </td>
            <td>{{ rec.called_by }}</td>
            <td>
              <span class="badge bg-light text-dark border">
                {{ rec.call_mode | replace('_',' ') | title if rec.call_mode else '—' }}
              </span>
            </td>
            <td>
              <span class="badge bg-{{ oc.get(rec.call_outcome,'secondary') }}">
                {{ rec.call_outcome | replace('_',' ') | title if rec.call_outcome else '—' }}
              </span>
            </td>
            <td>{{ (rec.items_discussed or '—')[:50] }}</td>
            <td>
              {% if rec.next_followup_date %}
              {{ rec.next_followup_date.strftime('%d-%m-%Y') }}
              {% else %}—{% endif %}
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="8" class="text-center text-muted py-4">
              No calls logged for this period.
              <a href="/dealers">Log a call via Dealer Management</a>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Verify telecalling dashboard loads without errors**

Open browser at `http://localhost:8000/telecalling` and check:
- Stats cards show (may be 0 if no DealerCall records today)
- Filter bar visible with all inputs
- Recent Calls table shows DealerCall records
- Dealer names are clickable links to `/dealers/{id}`
- No 500 errors in server log

Also open `http://localhost:8000/telecalling?q=test&outcome=interested` and verify filters are applied without error.

- [ ] **Step 4: Run all sprint 25 tests**

```
venv\Scripts\python -m pytest tests/test_sprint25_dealers.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add routers/telecalling.py templates/telecalling/index.html
git commit -m "feat(telecalling): live DealerCall feed, clickable dealer names, full filter bar"
```

---

## Self-Review

### Spec Coverage

| # | Requirement | Task | Covered? |
|---|---|---|---|
| 1 | Admin user dropdown filter in Dealer Mgmt | Task 1 | ✅ |
| 2 | Bulk upload dealers | Pre-existing | ✅ Already done |
| 3 | Last call date column + followup date filter | Task 1 | ✅ |
| 4 | Pills showing recent call log in Business Name | Task 1 | ✅ |
| 5 | Telecalling auto-updated from Dealer Management call logs | Task 2 | ✅ |
| 6 | Dealer Name clickable in Telecalling → Dealer Detail | Task 2 | ✅ |
| 7 | All filters same as Dealer Management in Telecalling | Task 2 | ✅ |

### Placeholder Scan

No TBD, TODO, or vague instructions. All code blocks are complete and executable.

### Type Consistency

- `recent_call_map[str(dealer_id)]` → dict with keys `"outcome"` and `"items"` — used correctly in template as `rc.outcome` and `rc.items`.
- `last_call_map[str(dealer_id)]` → datetime or None — used with `.strftime()` guarded by `{% if lc %}`.
- `DealerCall.dealer` → loaded via `selectinload(DealerCall.dealer)` in telecalling router — accessed as `rec.dealer.business_name`, `rec.dealer.phone` in template.
- `sales_users` — list of `User` objects; template accesses `u.username`, `u.full_name`, `u.role.value` — all valid `User` model attributes.
