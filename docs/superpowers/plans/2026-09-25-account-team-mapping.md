# Account Team Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let admins/CRM users map a company (Account) to a team of internal people across 4 seniority buckets (VP/AVP, Manager, AM/DM/GM, Executive/Sr Executive), filter Accounts by mapped person, edit the mapping per-account or in bulk via a shared modal, and bulk-apply mappings via CSV keyed on GSTIN.

**Architecture:** One new table (`crm_contact_team_members`, replace-on-save semantics, no soft delete — full history lives in the existing `audit_logs` table via the existing `audit()` helper). A small `services/crm_team.py` module holds bucket constants, eligibility matching, and the shared "replace these buckets" write helper used by both the modal-save route and the CSV-upload route. The Accounts List page (`templates/crm/contacts/list.html`) gets a new "Team" column (count badge → read-only modal), 4 new filter dropdowns, a per-row "Map Team" button, row checkboxes + a "Bulk Team Mapping" toolbar button, and one shared edit modal (`_map_team_modal.html`) reused for both single and bulk mode — following the exact per-row `data-*` JSON attribute pattern this template already uses for its Locations/Contacts count columns (no extra AJAX round trip for modal content).

**Tech Stack:** FastAPI + Jinja2 + SQLAlchemy async ORM (existing app conventions) + Bootstrap 5 modals + this app's existing `_multiselect_filter.html` checkbox-dropdown macro (not Tom Select — confirmed during research that Tom Select is not actually used for list-page filter bars in this codebase, only for single-value dropdowns elsewhere).

**Deployment note (per project convention — commit-deploy-gate skill):** No `git add`/`commit`/`push` happens during or after this plan's tasks. Every task's "Commit" step is replaced with "mark task complete, do not commit" — this whole feature is demoed live in the browser preview first, and only committed/pushed/deployed after the user explicitly approves following that demo.

---

## File Structure

**Create:**
- `models/crm_team.py` — `CRMContactTeamMember` model
- `services/crm_team.py` — `ROLE_BUCKETS`, `BUCKET_LABELS`, `eligible_users_for_bucket()`, `replace_team_buckets()`
- `alembic/versions/20260925_1400_add_crm_contact_team_members.py` — migration (history only; the live schema is actually provisioned by `db_validator.fix_missing_tables()` on next server startup, same as every other table in this app — confirmed in research)
- `templates/crm/contacts/_map_team_modal.html` — shared single/bulk edit modal partial
- `templates/crm/contacts/team_mapping_upload.html` — CSV bulk-upload page (mirrors `templates/crm/contacts/upload.html`)
- `tests/test_crm_team_mapping.py` — new test file, built up task by task

**Modify:**
- `models/__init__.py` — register new model (Alembic autogenerate + `db_validator` both need every model imported here)
- `routers/crm_contacts.py` — extend `list_contacts()`; add `save_team_mapping()`, `team_mapping_sample_csv()`, `team_mapping_upload_page()`, `team_mapping_upload_apply()`
- `templates/crm/contacts/list.html` — Team column, filters, checkboxes, buttons, read-view modal, JS wiring

---

## Task 1: `CRMContactTeamMember` model

**Files:**
- Create: `models/crm_team.py`
- Modify: `models/__init__.py:37-42`
- Test: `tests/test_crm_team_mapping.py` (new file)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_crm_team_mapping.py
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.crm_team import CRMContactTeamMember


@pytest.mark.asyncio
async def test_crm_contact_team_member_table_exists(db: AsyncSession):
    # If the model isn't registered (models/__init__.py) or the table hasn't
    # been created yet, this raises "relation does not exist" instead of
    # returning an empty list — that's the failure this step proves.
    result = await db.execute(select(CRMContactTeamMember).limit(1))
    assert result.scalars().all() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crm_team_mapping.py::test_crm_contact_team_member_table_exists -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'models.crm_team'`

- [ ] **Step 3: Write the model**

```python
# models/crm_team.py
"""
Account Team Mapping — CRM Module Extension
Table: crm_contact_team_members

Rows are fully replaced (deleted + re-inserted) on every save rather than
edited in place — see services/crm_team.py:replace_team_buckets(). History
lives in the existing audit_logs table via services/audit_engine.audit(),
same convention as every other write in this app, so there is no soft-delete
column here.
"""
import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class CRMContactTeamMember(Base):
    __tablename__ = "crm_contact_team_members"
    __table_args__ = (
        UniqueConstraint("contact_id", "user_id", "role_bucket", name="uq_crm_team_member_bucket"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    contact_id = Column(UUID(as_uuid=True), ForeignKey("crm_contacts.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role_bucket = Column(String(20), nullable=False)
    created_at = Column(DateTime, default=app_now)
    created_by = Column(String(50), ForeignKey("users.username"), nullable=True)
```

- [ ] **Step 4: Register the model**

In `models/__init__.py`, immediately after the existing CRM import block (after line 42, `)`):

```python
from .crm_team import CRMContactTeamMember
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_crm_team_mapping.py::test_crm_contact_team_member_table_exists -v`

If it still fails with "relation does not exist", the table hasn't been auto-provisioned yet — restart the local dev server once (`db_validator.fix_missing_tables()` runs on startup and calls `Base.metadata.create_all`, which picks up the newly-registered model) and re-run the test.

Expected: PASS

- [ ] **Step 6: Mark task complete (no git commit — see deployment note above)**

---

## Task 2: `services/crm_team.py` — bucket constants, eligibility, replace helper

**Files:**
- Create: `services/crm_team.py`
- Test: `tests/test_crm_team_mapping.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_crm_team_mapping.py`:

```python
from types import SimpleNamespace
from services.crm_team import ROLE_BUCKETS, BUCKET_LABELS, eligible_users_for_bucket, replace_team_buckets


def _u(designation=None, role="sales"):
    return SimpleNamespace(designation=designation, role=role)


def test_role_buckets_and_labels_cover_the_same_four_keys():
    assert set(ROLE_BUCKETS) == set(BUCKET_LABELS.keys())
    assert ROLE_BUCKETS == ["vp_avp", "manager", "am_dm_gm", "executive"]


def test_eligible_users_matches_whole_word_designation():
    users = [_u(designation="Regional AVP"), _u(designation="Sales Executive"), _u(designation=None)]
    assert eligible_users_for_bucket(users, "vp_avp") == [users[0]]


def test_eligible_users_does_not_false_positive_on_substring():
    # "TEAM" and "SAM" both contain the letters "AM" but must not match the
    # am_dm_gm bucket — this is the exact bug the spec calls out.
    users = [_u(designation="Team Lead"), _u(designation="Samir's Assistant"), _u(designation="AM - North")]
    assert eligible_users_for_bucket(users, "am_dm_gm") == [users[2]]


def test_eligible_users_can_match_multiple_buckets():
    u = _u(designation="Sr Executive / AM")
    assert eligible_users_for_bucket([u], "executive") == [u]
    assert eligible_users_for_bucket([u], "am_dm_gm") == [u]


def test_eligible_users_also_checks_role():
    u = _u(designation=None, role="manager")
    assert eligible_users_for_bucket([u], "manager") == [u]


def test_eligible_users_unknown_bucket_raises():
    with pytest.raises(ValueError):
        eligible_users_for_bucket([], "not_a_bucket")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_crm_team_mapping.py -v -k "bucket or eligible"`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.crm_team'`

- [ ] **Step 3: Write the service module**

```python
# services/crm_team.py
"""
Account Team Mapping — shared logic used by both the Map Team modal's save
route and the CSV bulk-upload route in routers/crm_contacts.py.
"""
import re
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from models.crm_team import CRMContactTeamMember

ROLE_BUCKETS = ["vp_avp", "manager", "am_dm_gm", "executive"]

BUCKET_LABELS = {
    "vp_avp": "VP/AVP",
    "manager": "Manager",
    "am_dm_gm": "AM/DM/GM",
    "executive": "Executive/Sr Executive",
}

BUCKET_KEYWORDS = {
    "vp_avp": ["VP", "AVP"],
    "manager": ["Manager"],
    "am_dm_gm": ["AM", "DM", "GM"],
    "executive": ["Executive"],
}


def _matches_bucket(text, bucket: str) -> bool:
    if not text:
        return False
    for kw in BUCKET_KEYWORDS[bucket]:
        if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE):
            return True
    return False


def eligible_users_for_bucket(users, bucket: str) -> list:
    """Users whose designation or role name contains a whole-word match for
    this bucket's keywords — never a raw substring match, so 'TEAM' or
    'Samir' doesn't false-positive on the 'AM' keyword."""
    if bucket not in ROLE_BUCKETS:
        raise ValueError(f"Unknown role bucket: {bucket}")
    result = []
    for u in users:
        role_val = u.role.value if hasattr(u.role, "value") else str(u.role)
        if _matches_bucket(u.designation, bucket) or _matches_bucket(role_val, bucket):
            result.append(u)
    return result


async def replace_team_buckets(
    db: AsyncSession,
    *,
    contact_id: uuid.UUID,
    bucket_user_ids: dict,
    created_by: str,
) -> None:
    """Replace mapping rows for the given (contact, bucket) pairs.

    Only buckets present as a key in bucket_user_ids are touched — a bucket
    left out of the dict entirely is left alone (this is what makes bulk
    mode's "only replace buckets the admin actually selected someone in"
    semantics work: the caller builds the dict with only the touched keys).
    A bucket present with an empty list clears that bucket — this is what
    makes single-company mode's "blank means clear" semantics work: the
    caller always includes all 4 keys.
    """
    for bucket, user_ids in bucket_user_ids.items():
        await db.execute(
            delete(CRMContactTeamMember).where(
                CRMContactTeamMember.contact_id == contact_id,
                CRMContactTeamMember.role_bucket == bucket,
            )
        )
        for uid in user_ids:
            db.add(CRMContactTeamMember(
                contact_id=contact_id, user_id=uid, role_bucket=bucket,
                created_by=created_by,
            ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_crm_team_mapping.py -v -k "bucket or eligible"`
Expected: PASS (7 tests)

- [ ] **Step 5: Write and run the `replace_team_buckets` DB round-trip test**

Append to `tests/test_crm_team_mapping.py`:

```python
@pytest.mark.asyncio
async def test_replace_team_buckets_round_trip(db: AsyncSession):
    from sqlalchemy import select
    from models.crm import CRMContact
    from models.user import User

    contact = (await db.execute(select(CRMContact).limit(1))).scalars().first()
    users = (await db.execute(select(User).limit(2))).scalars().all()
    assert contact and len(users) >= 2, "Need at least 1 CRMContact and 2 Users seeded in the dev DB"

    try:
        # First save: put user[0] in vp_avp only.
        await replace_team_buckets(
            db, contact_id=contact.id,
            bucket_user_ids={"vp_avp": [users[0].id]},
            created_by="pytest",
        )
        await db.commit()
        rows = (await db.execute(
            select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id)
        )).scalars().all()
        assert {r.user_id for r in rows} == {users[0].id}
        assert rows[0].role_bucket == "vp_avp"

        # Second save: replace vp_avp with user[1], leave nothing else touched.
        await replace_team_buckets(
            db, contact_id=contact.id,
            bucket_user_ids={"vp_avp": [users[1].id]},
            created_by="pytest",
        )
        await db.commit()
        rows = (await db.execute(
            select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id)
        )).scalars().all()
        assert {r.user_id for r in rows} == {users[1].id}

        # Third save: empty list clears the bucket.
        await replace_team_buckets(
            db, contact_id=contact.id,
            bucket_user_ids={"vp_avp": []},
            created_by="pytest",
        )
        await db.commit()
        rows = (await db.execute(
            select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id)
        )).scalars().all()
        assert rows == []
    finally:
        await db.execute(delete(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id))
        await db.commit()
```

Run: `pytest tests/test_crm_team_mapping.py::test_replace_team_buckets_round_trip -v`
Expected: PASS. If it fails with "Need at least 1 CRMContact and 2 Users seeded", check the local dev DB has at least one Account and two Users (it does — this app has been in active use all session).

- [ ] **Step 6: Mark task complete (no git commit)**

---

## Task 3: Migration file (history only)

**Files:**
- Create: `alembic/versions/20260925_1400_add_crm_contact_team_members.py`

No test — this project's migrations aren't unit-tested (confirmed convention: `alembic/versions/*.py` has no corresponding `tests/` entries), and per the spec's own caveat this table will actually be created by `db_validator.fix_missing_tables()` on next server restart (same mechanism already proven for every other table added this way in this project), not by running `alembic upgrade` — this migration exists only to keep migration history honest for anyone who does run `alembic upgrade` on a fresh environment.

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/20260925_1400_add_crm_contact_team_members.py
"""add_crm_contact_team_members

Revision ID: 20260925_1400
Revises: 20260925_1200
Create Date: 2026-09-25 14:00:00

Adds crm_contact_team_members — Account Team Mapping feature. Row-replace
semantics (no soft delete); history lives in audit_logs. In practice this
table gets auto-created by db_validator.fix_missing_tables() on the next
server restart, same as every other table in this app's history — this
migration exists to keep Alembic history accurate for a fresh environment
that runs `alembic upgrade` directly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '20260925_1400'
down_revision: Union[str, None] = '20260925_1200'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    def table_exists(name: str) -> bool:
        result = conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
            {"n": name},
        )
        return result.fetchone() is not None

    if not table_exists("crm_contact_team_members"):
        op.create_table(
            'crm_contact_team_members',
            sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text('gen_random_uuid()')),
            sa.Column('contact_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('crm_contacts.id'), nullable=False),
            sa.Column('user_id', postgresql.UUID(as_uuid=True),
                      sa.ForeignKey('users.id'), nullable=False),
            sa.Column('role_bucket', sa.String(20), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False,
                      server_default=sa.text('NOW()')),
            sa.Column('created_by', sa.String(50),
                      sa.ForeignKey('users.username'), nullable=True),
            sa.UniqueConstraint('contact_id', 'user_id', 'role_bucket',
                                 name='uq_crm_team_member_bucket'),
        )
        op.create_index('ix_crm_contact_team_members_contact_id',
                         'crm_contact_team_members', ['contact_id'])
        op.create_index('ix_crm_contact_team_members_user_id',
                         'crm_contact_team_members', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_crm_contact_team_members_user_id', table_name='crm_contact_team_members')
    op.drop_index('ix_crm_contact_team_members_contact_id', table_name='crm_contact_team_members')
    op.drop_table('crm_contact_team_members')
```

- [ ] **Step 2: Mark task complete (no git commit)**

---

## Task 4: `list_contacts()` — team data + bucket filters

**Files:**
- Modify: `routers/crm_contacts.py:14-24` (imports), `:107-255` (`list_contacts`)
- Test: `tests/test_crm_team_mapping.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_crm_team_mapping.py`:

```python
from httpx import AsyncClient, ASGITransport

from main import app
from database import get_db, AsyncSessionLocal
from auth.dependencies import get_current_user
from models.user import UserRole


class _FakeAdmin:
    id = None
    username = "verify_admin"
    role = UserRole.admin
    status = True
    full_name = "Verify Admin"


_CURRENT_USER = {"user": None}


async def _override_user():
    return _CURRENT_USER["user"]


async def _override_db():
    async with AsyncSessionLocal() as db:
        yield db


@pytest.mark.asyncio
async def test_list_contacts_renders_team_column_and_filters():
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    _CURRENT_USER["user"] = _FakeAdmin()

    transport = ASGITransport(app=app, raise_app_exceptions=True)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/crm/contacts")
            assert r.status_code == 200, r.text[:500]
            # Team column header must be present.
            assert "Team</th>" in r.text or ">Team<" in r.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crm_team_mapping.py::test_list_contacts_renders_team_column_and_filters -v`
Expected: FAIL — no "Team" column exists in the template yet (this will keep failing until Task 8 adds the column; that's expected — leave it red and move on, it becomes the acceptance test for Task 8's template work, not this task's).

Since this task only touches the Python side (no template changes yet), do not chase this test green here — confirm instead with a narrower assertion that only depends on this task's own change:

Replace the test body's final assertion with:

```python
            assert r.status_code == 200, r.text[:500]
```

Run again: `pytest tests/test_crm_team_mapping.py::test_list_contacts_renders_team_column_and_filters -v`
Expected: still FAIL right now — because `list_contacts()` doesn't accept the new `f_vp_avp` etc. query params or compute `team_map`/`bucket_options` yet, but those are *added* by this task, so this specific run should actually already PASS against the unmodified route (a plain 200). This step is here to lock in a baseline before editing; if it doesn't already pass, stop and investigate before continuing (means something else broke `GET /crm/contacts`).

- [ ] **Step 3: Update imports**

In `routers/crm_contacts.py`, after line 24 (`)`, closing the existing `from models.crm import (...)` block), add:

```python
from models.crm_team import CRMContactTeamMember
from services.crm_team import ROLE_BUCKETS, BUCKET_LABELS, eligible_users_for_bucket
```

- [ ] **Step 4: Extend `list_contacts()`**

In `routers/crm_contacts.py`, add 4 new query params to the `list_contacts` signature (after `created_by_filter`, before `db: AsyncSession = Depends(get_db)`):

```python
    f_vp_avp: str = Query(default=""),
    f_manager: str = Query(default=""),
    f_am_dm_gm: str = Query(default=""),
    f_executive: str = Query(default=""),
```

Immediately after the existing `# Admin-only: filter by the user who created the contact` block (after line 158, before `result = await db.execute(query.order_by(CRMContact.company_name))`), add the bucket filters:

```python
    _bucket_filter_params = {
        "vp_avp": f_vp_avp, "manager": f_manager,
        "am_dm_gm": f_am_dm_gm, "executive": f_executive,
    }
    for _bucket, _raw in _bucket_filter_params.items():
        _ids = []
        for _v in _raw.split(","):
            _v = _v.strip()
            if not _v:
                continue
            try:
                _ids.append(_uuid.UUID(_v))
            except ValueError:
                continue
        if _ids:
            _subq = select(CRMContactTeamMember.contact_id).where(
                CRMContactTeamMember.role_bucket == _bucket,
                CRMContactTeamMember.user_id.in_(_ids),
            )
            query = query.where(CRMContact.id.in_(_subq))
```

After `contacts = result.scalars().all()` (line 161), add the team-data block:

```python
    # Team mapping — bucket dropdown options (all active users, once) and the
    # current mapping per contact (one JOIN, no N+1), same pattern as the
    # existing locations_map/numbers_map above.
    users_result = await db.execute(select(User).where(User.status == True).order_by(User.full_name))
    all_users = users_result.scalars().all()
    bucket_options = {b: [(str(u.id), u.full_name) for u in eligible_users_for_bucket(all_users, b)]
                       for b in ROLE_BUCKETS}

    team_map: dict = {}
    _contact_ids_scope = [c.id for c in contacts]
    if _contact_ids_scope:
        team_rows = (await db.execute(
            select(CRMContactTeamMember, User.full_name)
            .join(User, CRMContactTeamMember.user_id == User.id)
            .where(CRMContactTeamMember.contact_id.in_(_contact_ids_scope))
        )).all()
        for member, full_name in team_rows:
            _cid = str(member.contact_id)
            team_map.setdefault(_cid, {b: [] for b in ROLE_BUCKETS})
            team_map[_cid][member.role_bucket].append({"id": str(member.user_id), "name": full_name})
```

In the `return templates.TemplateResponse(...)` call at the end of `list_contacts`, add these keys to the context dict (alongside the existing `"locations_map": locations_map,` line):

```python
        "team_map": team_map,
        "bucket_options": bucket_options,
        "bucket_labels": BUCKET_LABELS,
        "f_vp_avp": f_vp_avp, "f_manager": f_manager,
        "f_am_dm_gm": f_am_dm_gm, "f_executive": f_executive,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_crm_team_mapping.py::test_list_contacts_renders_team_column_and_filters -v`
Expected: PASS (still just the baseline 200 assertion from Step 2 — the "Team</th>" assertion is added back in Task 8)

Restore the fuller assertion now for Task 8 to turn green later:

```python
            assert r.status_code == 200, r.text[:500]
            assert "Team</th>" in r.text or ">Team<" in r.text
```

This will go red again until Task 8 — that's expected and fine; leave it in place as the acceptance test for that task.

- [ ] **Step 6: Mark task complete (no git commit)**

---

## Task 5: `POST /crm/contacts/team-mapping` — save (single + bulk)

**Files:**
- Modify: `routers/crm_contacts.py` (add route near the end of the CRM-contacts-specific routes, e.g. after `upload_contacts_csv`)
- Test: `tests/test_crm_team_mapping.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_crm_team_mapping.py`:

```python
@pytest.mark.asyncio
async def test_save_team_mapping_single_and_bulk_modes():
    from sqlalchemy import select, delete as sa_delete
    from models.crm import CRMContact
    from models.user import User

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    _CURRENT_USER["user"] = _FakeAdmin()

    async with AsyncSessionLocal() as db:
        contacts = (await db.execute(select(CRMContact).limit(2))).scalars().all()
        users = (await db.execute(select(User).limit(2))).scalars().all()
        assert len(contacts) >= 2 and len(users) >= 2, "Need 2 CRMContacts and 2 Users seeded"
        c1, c2 = contacts[0], contacts[1]
        u1, u2 = users[0], users[1]

    transport = ASGITransport(app=app, raise_app_exceptions=True)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            c.cookies.set("csrf_token", "smoketest-csrf")

            # Single mode: map u1 into vp_avp for c1, leave other 3 buckets
            # blank — blank means "clear" in single mode, so this is a no-op
            # for those buckets (they were already empty).
            r = await c.post(
                "/crm/contacts/team-mapping",
                data={
                    "contact_ids": [str(c1.id)],
                    "mode": "single",
                    "bucket_vp_avp": str(u1.id),
                    "bucket_manager": "", "bucket_am_dm_gm": "", "bucket_executive": "",
                    "csrf_token": "smoketest-csrf",
                },
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307), f"single save returned {r.status_code}: {r.text[:300]}"

            async with AsyncSessionLocal() as db:
                rows = (await db.execute(
                    select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == c1.id)
                )).scalars().all()
                assert {(r.user_id, r.role_bucket) for r in rows} == {(u1.id, "vp_avp")}

            # Bulk mode: map u2 into manager for BOTH c1 and c2, leave vp_avp
            # untouched (empty string in bulk mode = skip, not clear) — c1's
            # existing vp_avp=u1 mapping from above must survive.
            r = await c.post(
                "/crm/contacts/team-mapping",
                data={
                    "contact_ids": [str(c1.id), str(c2.id)],
                    "mode": "bulk",
                    "bucket_vp_avp": "",
                    "bucket_manager": str(u2.id),
                    "bucket_am_dm_gm": "", "bucket_executive": "",
                    "csrf_token": "smoketest-csrf",
                },
                follow_redirects=False,
            )
            assert r.status_code in (302, 303, 307), f"bulk save returned {r.status_code}: {r.text[:300]}"

            async with AsyncSessionLocal() as db:
                rows1 = (await db.execute(
                    select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == c1.id)
                )).scalars().all()
                rows2 = (await db.execute(
                    select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == c2.id)
                )).scalars().all()
                assert {(r.user_id, r.role_bucket) for r in rows1} == {(u1.id, "vp_avp"), (u2.id, "manager")}
                assert {(r.user_id, r.role_bucket) for r in rows2} == {(u2.id, "manager")}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(sa_delete(CRMContactTeamMember).where(
                CRMContactTeamMember.contact_id.in_([c1.id, c2.id])
            ))
            await db.commit()
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_crm_team_mapping.py::test_save_team_mapping_single_and_bulk_modes -v`
Expected: FAIL with 404 (route doesn't exist yet)

- [ ] **Step 3: Write the route**

In `routers/crm_contacts.py`, add after `upload_contacts_csv` (after its closing, around line 519+):

```python
@router.post("/team-mapping")
async def save_team_mapping(
    request: Request,
    contact_ids: list[str] = Form(...),
    mode: str = Form(...),
    bucket_vp_avp: str = Form(default=""),
    bucket_manager: str = Form(default=""),
    bucket_am_dm_gm: str = Form(default=""),
    bucket_executive: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("crm_contacts", "edit")),
):
    from services.crm_team import replace_team_buckets

    def _parse_ids(s: str) -> list:
        out = []
        for part in s.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(_uuid.UUID(part))
            except ValueError:
                continue
        return out

    raw_buckets = {
        "vp_avp": bucket_vp_avp, "manager": bucket_manager,
        "am_dm_gm": bucket_am_dm_gm, "executive": bucket_executive,
    }
    if mode == "single":
        bucket_user_ids = {b: _parse_ids(v) for b, v in raw_buckets.items()}
    else:
        bucket_user_ids = {b: _parse_ids(v) for b, v in raw_buckets.items() if v.strip()}

    cids = []
    for c in contact_ids:
        try:
            cids.append(_uuid.UUID(c))
        except ValueError:
            continue
    if not cids:
        return RedirectResponse(url="/crm/contacts?error=No+accounts+selected", status_code=302)

    contacts = (await db.execute(select(CRMContact).where(CRMContact.id.in_(cids)))).scalars().all()

    for contact in contacts:
        old_rows = (await db.execute(
            select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id)
        )).scalars().all()
        old_value: dict = {}
        for r in old_rows:
            old_value.setdefault(r.role_bucket, []).append(str(r.user_id))

        await replace_team_buckets(
            db, contact_id=contact.id, bucket_user_ids=bucket_user_ids,
            created_by=current_user.username,
        )

        new_value = {b: [str(u) for u in ids] for b, ids in bucket_user_ids.items()}
        await audit(db, user=current_user, action="TEAM_MAPPING_UPDATED",
                    table_name="crm_contact_team_members", record_id=str(contact.id),
                    old_value=old_value, new_value=new_value, request=request)

    await db.commit()
    return RedirectResponse(url="/crm/contacts?success=Team+mapping+updated", status_code=302)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_crm_team_mapping.py::test_save_team_mapping_single_and_bulk_modes -v`
Expected: PASS

- [ ] **Step 5: Mark task complete (no git commit)**

---

## Task 6: CSV bulk-upload (sample export, upload page, apply)

**Files:**
- Create: `templates/crm/contacts/team_mapping_upload.html`
- Modify: `routers/crm_contacts.py` (3 new routes, after the Task 5 route)
- Test: `tests/test_crm_team_mapping.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_crm_team_mapping.py`:

```python
@pytest.mark.asyncio
async def test_team_mapping_sample_csv_lists_accounts():
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    _CURRENT_USER["user"] = _FakeAdmin()

    transport = ASGITransport(app=app, raise_app_exceptions=True)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/crm/contacts/team-mapping/sample-csv")
            assert r.status_code == 200, r.text[:300]
            body = r.content.decode("utf-8-sig")
            assert body.splitlines()[0] == "gstin,company_name,vp_avp,manager,am_dm_gm,executive"
            assert len(body.splitlines()) > 1, "expected at least one account row"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_team_mapping_upload_page_loads():
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    _CURRENT_USER["user"] = _FakeAdmin()

    transport = ASGITransport(app=app, raise_app_exceptions=True)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.get("/crm/contacts/team-mapping/upload")
            assert r.status_code == 200, r.text[:300]
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_team_mapping_upload_apply_matches_by_gstin_and_reports_errors():
    from sqlalchemy import select, delete as sa_delete
    from models.crm import CRMContact
    from models.user import User

    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[get_db] = _override_db
    _CURRENT_USER["user"] = _FakeAdmin()

    async with AsyncSessionLocal() as db:
        contact = (await db.execute(
            select(CRMContact).where(CRMContact.gstin.isnot(None)).limit(1)
        )).scalars().first()
        assert contact, "Need at least one CRMContact with a GSTIN seeded"
        user = (await db.execute(select(User).limit(1))).scalars().first()
        assert user

    csv_body = (
        "gstin,company_name,vp_avp,manager,am_dm_gm,executive\n"
        f"{contact.gstin},{contact.company_name},{user.full_name},,,\n"
        ",Missing GSTIN Row,SomeoneNotReal,,,\n"
        f"{contact.gstin.lower()},dup case,,NoSuchPerson,,\n"
    ).encode("utf-8")

    transport = ASGITransport(app=app, raise_app_exceptions=True)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            c.cookies.set("csrf_token", "smoketest-csrf")
            r = await c.post(
                "/crm/contacts/team-mapping/upload",
                data={"csrf_token": "smoketest-csrf"},
                files={"file": ("team_mapping.csv", csv_body, "text/csv")},
            )
            assert r.status_code == 200, r.text[:500]
            assert "1" in r.text  # applied count rendered somewhere in the result summary
            assert "missing GSTIN" in r.text.lower() or "no gstin" in r.text.lower()
            assert "NoSuchPerson" in r.text

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id)
            )).scalars().all()
            assert {(r.user_id, r.role_bucket) for r in rows} == {(user.id, "vp_avp")}
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(sa_delete(CRMContactTeamMember).where(
                CRMContactTeamMember.contact_id == contact.id
            ))
            await db.commit()
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_crm_team_mapping.py -v -k "team_mapping_sample_csv or team_mapping_upload"`
Expected: FAIL (404s — routes and template don't exist yet)

- [ ] **Step 3: Write the 3 routes**

In `routers/crm_contacts.py`, add after the `save_team_mapping` route from Task 5:

```python
@router.get("/team-mapping/sample-csv")
async def team_mapping_sample_csv(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import csv
    import io

    contacts = (await db.execute(
        select(CRMContact).where(CRMContact.is_trashed == False).order_by(CRMContact.company_name)
    )).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["gstin", "company_name", "vp_avp", "manager", "am_dm_gm", "executive"])
    for c in contacts:
        writer.writerow([c.gstin or "", c.company_name, "", "", "", ""])

    return StreamingResponse(
        iter([buf.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": "attachment; filename=team_mapping_sample.csv"},
    )


async def _team_mapping_reference_rows(db: AsyncSession) -> list:
    users = (await db.execute(select(User).where(User.status == True).order_by(User.full_name))).scalars().all()
    reference = []
    seen = set()
    for bucket in ROLE_BUCKETS:
        for u in eligible_users_for_bucket(users, bucket):
            if u.id in seen:
                continue
            seen.add(u.id)
            role_val = u.role.value if hasattr(u.role, "value") else str(u.role)
            reference.append({"full_name": u.full_name, "role": role_val, "designation": u.designation or ""})
    return reference


@router.get("/team-mapping/upload", response_class=HTMLResponse)
async def team_mapping_upload_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reference = await _team_mapping_reference_rows(db)
    return templates.TemplateResponse("crm/contacts/team_mapping_upload.html", {
        "request": request, "current_user": current_user,
        "reference": reference, "result": None,
    })


@router.post("/team-mapping/upload", response_class=HTMLResponse)
async def team_mapping_upload_apply(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_module_perm("crm_contacts", "edit")),
):
    import csv
    import io
    from services.crm_team import replace_team_buckets

    raw = decode_csv_bytes(await file.read())
    reader = csv.DictReader(io.StringIO(raw))

    all_users = (await db.execute(select(User).where(User.status == True))).scalars().all()
    by_name: dict = {}
    for u in all_users:
        by_name.setdefault(u.full_name, []).append(u)

    applied = 0
    skipped = 0
    errors: list = []

    for i, row in enumerate(reader, start=2):
        gstin = (row.get("gstin") or "").strip().upper()
        if not gstin:
            skipped += 1
            errors.append(f"Row {i}: missing GSTIN, skipped")
            continue

        contact = (await db.execute(
            select(CRMContact).where(func.upper(CRMContact.gstin) == gstin)
        )).scalars().first()
        if not contact:
            skipped += 1
            errors.append(f"Row {i}: no account found for GSTIN {gstin}, skipped")
            continue

        bucket_user_ids: dict = {}
        for bucket in ROLE_BUCKETS:
            cell = (row.get(bucket) or "").strip()
            if not cell:
                continue
            resolved = []
            for name in [n.strip() for n in cell.split(",") if n.strip()]:
                matches = by_name.get(name, [])
                if len(matches) != 1:
                    reason = "not found" if not matches else "matches multiple users"
                    errors.append(f"Row {i}: '{name}' in {bucket} {reason}, skipped")
                    continue
                resolved.append(matches[0].id)
            bucket_user_ids[bucket] = resolved

        if not bucket_user_ids:
            skipped += 1
            continue

        old_rows = (await db.execute(
            select(CRMContactTeamMember).where(CRMContactTeamMember.contact_id == contact.id)
        )).scalars().all()
        old_value: dict = {}
        for r in old_rows:
            old_value.setdefault(r.role_bucket, []).append(str(r.user_id))

        await replace_team_buckets(
            db, contact_id=contact.id, bucket_user_ids=bucket_user_ids,
            created_by=current_user.username,
        )
        new_value = {b: [str(u) for u in ids] for b, ids in bucket_user_ids.items()}
        await audit(db, user=current_user, action="TEAM_MAPPING_UPDATED",
                    table_name="crm_contact_team_members", record_id=str(contact.id),
                    old_value=old_value, new_value=new_value, request=request)
        applied += 1

    await db.commit()

    reference = await _team_mapping_reference_rows(db)
    return templates.TemplateResponse("crm/contacts/team_mapping_upload.html", {
        "request": request, "current_user": current_user,
        "reference": reference,
        "result": {"applied": applied, "skipped": skipped, "errors": errors},
    })
```

- [ ] **Step 4: Write the upload page template**

```html
{# templates/crm/contacts/team_mapping_upload.html #}
{% extends "base.html" %}
{% block title %}Team Mapping Upload — OxyPC{% endblock %}
{% block page_title %}Account Team Mapping — Bulk Upload{% endblock %}
{% block content %}

{% if result %}
<div class="row g-3 mb-4">
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-3">
      <div class="fs-4 fw-bold text-success">{{ result.applied }}</div>
      <div class="small text-muted">Rows Applied</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-3">
      <div class="fs-4 fw-bold text-warning">{{ result.skipped }}</div>
      <div class="small text-muted">Rows Skipped</div>
    </div>
  </div>
  <div class="col-6 col-md-3">
    <div class="card border-0 shadow-sm text-center py-3">
      <div class="fs-4 fw-bold text-danger">{{ result.errors | length }}</div>
      <div class="small text-muted">Row Errors</div>
    </div>
  </div>
</div>
{% if result.errors %}
<div class="alert alert-warning py-2 small mb-3">
  <strong>Row errors:</strong>
  <ul class="mb-0 mt-1">
    {% for e in result.errors %}<li>{{ e }}</li>{% endfor %}
  </ul>
</div>
{% endif %}
{% endif %}

<div class="row g-3">
  <div class="col-lg-7">
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-header bg-transparent fw-semibold">Upload CSV</div>
      <div class="card-body">
        <p class="small text-muted">
          Match key is <code>gstin</code> — rows without a GSTIN are skipped.
          Each role column accepts one or more names, comma-separated,
          matched exactly against the Reference panel on the right. A blank
          role column leaves that bucket unchanged for the matched account.
        </p>
        <a href="/crm/contacts/team-mapping/sample-csv" class="btn btn-sm btn-outline-secondary mb-3">
          <i class="bi bi-download me-1"></i>Download Sample CSV (all accounts)
        </a>
        <form action="/crm/contacts/team-mapping/upload" method="post" enctype="multipart/form-data">
          <input type="hidden" name="csrf_token" value="{{ request.cookies.get('csrf_token', '') }}">
          <div class="mb-3">
            <input type="file" name="file" class="form-control form-control-sm" accept=".csv" required>
          </div>
          <div class="d-flex gap-2">
            <button type="submit" class="btn btn-primary"><i class="bi bi-upload me-1"></i>Upload &amp; Apply</button>
            <a href="/crm/contacts" class="btn btn-outline-secondary">Back to Accounts</a>
          </div>
        </form>
      </div>
    </div>
  </div>
  <div class="col-lg-5">
    <div class="card border-0 shadow-sm mb-4">
      <div class="card-header bg-transparent fw-semibold">Reference — Eligible Users</div>
      <div class="card-body p-0" style="max-height:420px; overflow-y:auto;">
        <table class="table table-sm mb-0">
          <thead class="table-light"><tr><th>Name</th><th>Role</th><th>Designation</th></tr></thead>
          <tbody>
            {% for u in reference %}
            <tr><td>{{ u.full_name }}</td><td>{{ u.role }}</td><td>{{ u.designation or '—' }}</td></tr>
            {% else %}
            <tr><td colspan="3" class="text-muted text-center py-3">
              No users currently match a role bucket. Set a sales-style
              designation (containing VP, AVP, Manager, AM, DM, GM, or
              Executive) via Admin &gt; User Management.
            </td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_crm_team_mapping.py -v -k "team_mapping_sample_csv or team_mapping_upload"`
Expected: PASS (3 tests)

- [ ] **Step 6: Mark task complete (no git commit)**

---

## Task 7: Map Team modal partial

**Files:**
- Create: `templates/crm/contacts/_map_team_modal.html`

No isolated test — this partial only renders inside `list.html`, exercised by Task 8's manual browser verification.

- [ ] **Step 1: Write the modal partial**

```html
{# templates/crm/contacts/_map_team_modal.html
   Shared single/bulk edit modal for Account Team Mapping. Included once
   from list.html; scope (single company vs bulk) is switched by JS before
   opening — same convention as other shared modals in this codebase.
   Field names (bucket_vp_avp etc.) are distinct from the filter bar's
   f_vp_avp etc. so the two sets of checkbox-dropdown macro instances don't
   collide on element id. #}
{% import "_multiselect_filter.html" as ms %}
<div class="modal fade" id="mapTeamModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-lg">
    <form method="post" action="/crm/contacts/team-mapping" class="modal-content" id="mapTeamForm">
      <input type="hidden" name="csrf_token" value="{{ request.cookies.get('csrf_token', '') }}">
      <input type="hidden" name="mode" id="mapTeamMode" value="single">
      <div id="mapTeamContactIds"></div>
      <div class="modal-header py-2">
        <h5 class="modal-title"><i class="bi bi-people-fill me-2"></i><span id="mapTeamHeader">Map Team</span></h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body">
        <div class="row g-3">
          <div class="col-md-6">{{ ms.multiselect('bucket_vp_avp', 'VP/AVP', bucket_options['vp_avp'], '', width='') }}</div>
          <div class="col-md-6">{{ ms.multiselect('bucket_manager', 'Manager', bucket_options['manager'], '', width='') }}</div>
          <div class="col-md-6">{{ ms.multiselect('bucket_am_dm_gm', 'AM/DM/GM', bucket_options['am_dm_gm'], '', width='') }}</div>
          <div class="col-md-6">{{ ms.multiselect('bucket_executive', 'Executive/Sr Executive', bucket_options['executive'], '', width='') }}</div>
        </div>
        <p class="small text-muted mt-3 mb-0" id="mapTeamHint">
          Leaving a bucket blank clears it for this account.
        </p>
      </div>
      <div class="modal-footer py-2">
        <button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
        <button type="submit" class="btn btn-sm btn-primary"><i class="bi bi-check2 me-1"></i>Save Team Mapping</button>
      </div>
    </form>
  </div>
</div>
```

Note: `width=''` passed to the macro overrides its `col-md-2` default with an empty class on the wrapping `<div class="{{ width }}">` — combined with the surrounding `<div class="col-md-6">` this gives each bucket dropdown a predictable half-width in the modal, avoiding double-applying grid classes.

- [ ] **Step 2: Mark task complete (no git commit)**

---

## Task 8: `list.html` — column, filters, checkboxes, buttons, read-view modal, JS

**Files:**
- Modify: `templates/crm/contacts/list.html`

Test: the acceptance test written in Task 4 Step 5 (`test_list_contacts_renders_team_column_and_filters`) turns green at the end of this task. This task is otherwise verified by hand in the browser (per the user's request to demo before commit) — end with Task 10's manual walkthrough.

- [ ] **Step 1: Add the multiselect macro import**

At the very top of `templates/crm/contacts/list.html`, after `{% block content %}` (line 4), add:

```jinja
{% import "_multiselect_filter.html" as ms %}
```

- [ ] **Step 2: Add the 4 bucket filter dropdowns**

In the filter `<form>` (inside `<div class="mb-3">`), immediately before the `<button class="btn btn-sm btn-outline-primary">Filter</button>` line (line 44), add:

```jinja
    {{ ms.multiselect('f_vp_avp', 'VP/AVP', bucket_options['vp_avp'], f_vp_avp, width='col-auto') }}
    {{ ms.multiselect('f_manager', 'Manager', bucket_options['manager'], f_manager, width='col-auto') }}
    {{ ms.multiselect('f_am_dm_gm', 'AM/DM/GM', bucket_options['am_dm_gm'], f_am_dm_gm, width='col-auto') }}
    {{ ms.multiselect('f_executive', 'Executive/Sr Exec', bucket_options['executive'], f_executive, width='col-auto') }}
```

Also update the existing "Clear" link condition (line 45) to account for the new filters:

Change:
```jinja
    {% if q or contact_type or source_type or buyer_type or contacted or created_by_filter %}
```
to:
```jinja
    {% if q or contact_type or source_type or buyer_type or contacted or created_by_filter or f_vp_avp or f_manager or f_am_dm_gm or f_executive %}
```

- [ ] **Step 3: Add the "Bulk Team Mapping" toolbar button and CSV upload link**

In the card header's button group (inside `<div class="d-flex gap-2 flex-wrap">`, after the existing `Bulk Upload CSV` link, before the `{% if current_user.role.value == 'admin' %}` Export CSV block — i.e. after line 71), add:

```html
      <a href="/crm/contacts/team-mapping/upload" class="btn btn-sm btn-outline-secondary">
        <i class="bi bi-people me-1"></i>Team Mapping CSV
      </a>
      {% if has_perm(current_user.role.value, 'crm_contacts', 'edit') %}
      <button type="button" id="bulkTeamMappingBtn" class="btn btn-sm btn-outline-dark" disabled>
        <i class="bi bi-person-badge me-1"></i>Bulk Team Mapping (<span id="teamSelCount">0</span>)
      </button>
      {% endif %}
```

- [ ] **Step 4: Add the checkbox column**

Change the table header (lines 104-115) from:

```html
          <tr>
            <th>Company</th>
            <th>Type</th>
            <th>Category</th>
            <th>Locations</th>
            <th>Contacts</th>
            <th>KYC</th>
            <th class="d-none">Notes</th>
            <th>Created By</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
```

to:

```html
          <tr>
            {% if has_perm(current_user.role.value, 'crm_contacts', 'edit') %}
            <th class="ps-3"><input type="checkbox" id="teamSelectAll" class="form-check-input"></th>
            {% endif %}
            <th>Company</th>
            <th>Type</th>
            <th>Category</th>
            <th>Locations</th>
            <th>Contacts</th>
            <th>KYC</th>
            <th>Team</th>
            <th class="d-none">Notes</th>
            <th>Created By</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
```

Update the column-order comment above the table (line 101) from:

```jinja
      {# Column order: Company | Type | Category | Locations | Contacts | KYC | Notes (hidden) | Created By | Status | Actions #}
```

to:

```jinja
      {# Column order (when edit perm grants the checkbox column): Checkbox | Company | Type | Category | Locations | Contacts | KYC | Team | Notes (hidden) | Created By | Status | Actions #}
```

- [ ] **Step 5: Add the row checkbox and Team column cell**

Immediately after `<tr>` (line 124, inside the `{% for c in contacts %}` loop), add:

```html
            {% if has_perm(current_user.role.value, 'crm_contacts', 'edit') %}
            <td class="ps-3"><input type="checkbox" class="form-check-input team-row-chk" value="{{ c.id }}"></td>
            {% endif %}
```

After the existing KYC `<td>` block (after line 204, before the `{# 10. Notes (hidden) #}` comment on line 205), add:

```html
            {# 5b. Team — mapped account team by seniority bucket #}
            <td>
              {% set tm = team_map.get(cid, {}) %}
              {% set team_total = (tm.get('vp_avp', []) | length) + (tm.get('manager', []) | length) + (tm.get('am_dm_gm', []) | length) + (tm.get('executive', []) | length) %}
              {% if team_total %}
              <button type="button" class="btn btn-sm btn-outline-dark py-0 px-2 team-view-btn"
                      data-company="{{ c.company_name }}"
                      data-team='{{ tm|tojson }}'>
                <i class="bi bi-person-badge me-1"></i>{{ team_total }}
              </button>
              {% else %}
              <span class="text-muted">0</span>
              {% endif %}
            </td>
```

- [ ] **Step 6: Add the "Map Team" button to the Actions cell**

In the Actions `<td>` (lines 236-251), inside the `<div class="d-flex gap-1 flex-wrap">`, after the existing `Edit` link (`/crm/contacts/{{ c.id }}/edit`) and before the trash `<form>`, add:

```html
      {% if has_perm(current_user.role.value, 'crm_contacts', 'edit') %}
      <button type="button" class="btn btn-sm btn-outline-dark map-team-btn" title="Map Team"
              data-contact-id="{{ c.id }}" data-company="{{ c.company_name }}"
              data-team='{{ team_map.get(cid, {})|tojson }}'>
        <i class="bi bi-person-badge"></i>
      </button>
      {% endif %}
```

- [ ] **Step 7: Include the read-view modal and the Map Team modal**

After the existing `<!-- Locations detail modal -->` block (after line 356), add:

```html
<!-- Team View modal (read-only — opened from the Team column badge) -->
<div class="modal fade" id="teamViewModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog modal-dialog-centered">
    <div class="modal-content">
      <div class="modal-header py-2">
        <h6 class="modal-title"><i class="bi bi-person-badge me-2"></i><span id="teamViewCompany"></span> — Team</h6>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
      </div>
      <div class="modal-body p-0">
        <table class="table table-sm mb-0">
          <thead class="table-light"><tr><th>Name</th><th>Bucket</th></tr></thead>
          <tbody id="teamViewBody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

{% include "crm/contacts/_map_team_modal.html" %}
```

- [ ] **Step 8: Update DataTables column indices**

In `{% block scripts %}`, change the leading comment and `columnDefs` (lines 399, 410):

From:
```javascript
// col index: 0=Company,1=Type,2=Category,3=Locations,4=Contacts,5=KYC,6=Notes(hidden),7=Created By,8=Status,9=Actions
$(document).ready(function(){
  initGlobalTable('#contactsTable', {
    order: [[0, 'asc']],  // default sort by Company
    columnDefs: [{ orderable: false, targets: [3, 4, 9] }],  // Locations + Contacts + Actions not sortable
    language: { emptyTable: 'No contacts found. Use the Add Account button above to create one.' }
  });
});
```

To (accounts for the checkbox column only existing when the edit-perm block rendered it — this app's DataTables columnDefs targets must match the actual rendered `<thead>`, so branch the JS the same way the Jinja branched the column):

```javascript
// col index (edit perm): 0=Checkbox,1=Company,2=Type,3=Category,4=Locations,5=Contacts,6=KYC,7=Team,8=Notes(hidden),9=Created By,10=Status,11=Actions
// col index (no edit perm, no checkbox column): 0=Company,1=Type,2=Category,3=Locations,4=Contacts,5=KYC,6=Team,7=Notes(hidden),8=Created By,9=Status,10=Actions
$(document).ready(function(){
  var hasCheckboxCol = !!document.getElementById('teamSelectAll');
  var off = hasCheckboxCol ? 1 : 0;
  initGlobalTable('#contactsTable', {
    order: [[0 + off, 'asc']],  // default sort by Company
    columnDefs: [{ orderable: false, targets: hasCheckboxCol ? [0, 4, 5, 7, 11] : [3, 4, 6, 10] }],
    language: { emptyTable: 'No contacts found. Use the Add Account button above to create one.' }
  });
});
```

- [ ] **Step 9: Add the Team View / Map Team / Bulk Team Mapping JS**

At the end of the existing `(function () { ... })();` IIFE in `{% block scripts %}` (immediately before its closing `})();` on the line following the Locations-modal block, i.e. right before line 467's `})();`), add:

```javascript
  var BUCKET_LABELS = {
    vp_avp: 'VP/AVP', manager: 'Manager', am_dm_gm: 'AM/DM/GM', executive: 'Executive/Sr Executive'
  };

  // Team column badge → read-only Team View modal
  var teamViewModalEl = document.getElementById('teamViewModal');
  if (teamViewModalEl) {
    var teamViewModal = new bootstrap.Modal(teamViewModalEl);
    document.querySelectorAll('.team-view-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var company = this.getAttribute('data-company') || '';
        var tm = {};
        try { tm = JSON.parse(this.getAttribute('data-team') || '{}'); } catch (e) {}
        document.getElementById('teamViewCompany').textContent = company;
        var rows = [];
        Object.keys(BUCKET_LABELS).forEach(function (bucket) {
          (tm[bucket] || []).forEach(function (m) {
            rows.push('<tr><td>' + esc(m.name) + '</td><td>' + esc(BUCKET_LABELS[bucket]) + '</td></tr>');
          });
        });
        document.getElementById('teamViewBody').innerHTML = rows.join('') ||
          '<tr><td colspan="2" class="text-muted text-center py-3">No team mapped.</td></tr>';
        teamViewModal.show();
      });
    });
  }

  // Map Team modal — shared between the per-row "Map Team" button (single
  // mode, pre-filled) and the toolbar "Bulk Team Mapping" button (bulk mode,
  // starts empty). setBucketSelection() dispatches a native 'change' event
  // on a checkbox after setting it, so it reuses the existing sync() logic
  // in static/js/multiselect-filter.js (hidden-input + label text) instead
  // of duplicating it.
  var mapTeamModalEl = document.getElementById('mapTeamModal');
  if (mapTeamModalEl) {
    var mapTeamModal = new bootstrap.Modal(mapTeamModalEl);

    function setBucketSelection(fieldName, ids) {
      var wrap = document.querySelector('.ms-filter[data-ms="' + fieldName + '"]');
      if (!wrap) return;
      var menu = wrap.querySelector('.dropdown-menu');
      var boxes = menu.querySelectorAll('.ms-opt');
      boxes.forEach(function (cb) { cb.checked = ids.indexOf(cb.value) !== -1; });
      if (boxes.length) {
        boxes[0].dispatchEvent(new Event('change', { bubbles: true }));
      } else {
        var hidden = document.getElementById('ms_val_' + fieldName);
        if (hidden) hidden.value = '';
      }
    }

    function fillContactIds(ids) {
      var container = document.getElementById('mapTeamContactIds');
      container.innerHTML = '';
      ids.forEach(function (id) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'contact_ids';
        input.value = id;
        container.appendChild(input);
      });
    }

    function openMapTeamModal(mode, ids, headerText, teamData) {
      document.getElementById('mapTeamMode').value = mode;
      fillContactIds(ids);
      document.getElementById('mapTeamHeader').textContent = headerText;
      document.getElementById('mapTeamHint').textContent = mode === 'single'
        ? 'Leaving a bucket blank clears it for this account.'
        : 'Only buckets where you select at least one person are changed — untouched buckets are left as-is for every selected account.';
      var td = teamData || {};
      setBucketSelection('bucket_vp_avp', (td.vp_avp || []).map(function (m) { return m.id; }));
      setBucketSelection('bucket_manager', (td.manager || []).map(function (m) { return m.id; }));
      setBucketSelection('bucket_am_dm_gm', (td.am_dm_gm || []).map(function (m) { return m.id; }));
      setBucketSelection('bucket_executive', (td.executive || []).map(function (m) { return m.id; }));
      mapTeamModal.show();
    }

    document.querySelectorAll('.map-team-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var contactId = this.getAttribute('data-contact-id');
        var company = this.getAttribute('data-company') || '';
        var teamData = {};
        try { teamData = JSON.parse(this.getAttribute('data-team') || '{}'); } catch (e) {}
        openMapTeamModal('single', [contactId], company, teamData);
      });
    });

    var bulkBtn = document.getElementById('bulkTeamMappingBtn');
    if (bulkBtn) {
      bulkBtn.addEventListener('click', function () {
        var ids = [];
        document.querySelectorAll('.team-row-chk:checked').forEach(function (cb) { ids.push(cb.value); });
        if (!ids.length) return;
        openMapTeamModal('bulk', ids, ids.length + ' companies selected', {});
      });
    }
  }

  // Row checkbox select-all + toolbar button enable/disable + count
  var selectAllChk = document.getElementById('teamSelectAll');
  var bulkTeamBtn = document.getElementById('bulkTeamMappingBtn');
  var teamSelCountEl = document.getElementById('teamSelCount');
  function updateTeamSelUI() {
    var checked = document.querySelectorAll('.team-row-chk:checked').length;
    if (teamSelCountEl) teamSelCountEl.textContent = String(checked);
    if (bulkTeamBtn) bulkTeamBtn.disabled = checked === 0;
  }
  if (selectAllChk) {
    selectAllChk.addEventListener('change', function () {
      document.querySelectorAll('.team-row-chk').forEach(function (cb) { cb.checked = selectAllChk.checked; });
      updateTeamSelUI();
    });
  }
  document.querySelectorAll('.team-row-chk').forEach(function (cb) {
    cb.addEventListener('change', updateTeamSelUI);
  });
```

- [ ] **Step 10: Run the Task 4 acceptance test**

Run: `pytest tests/test_crm_team_mapping.py::test_list_contacts_renders_team_column_and_filters -v`
Expected: PASS

- [ ] **Step 11: Run the full test file**

Run: `pytest tests/test_crm_team_mapping.py -v`
Expected: PASS (all tests from Tasks 1, 2, 4, 5, 6, 8)

- [ ] **Step 12: Mark task complete (no git commit)**

---

## Task 9: Restart local server, seed a demo mapping, live browser walkthrough

**Files:** none (verification only)

- [ ] **Step 1: Restart the local dev server** so `db_validator.fix_missing_tables()` picks up the new `CRMContactTeamMember` model and creates `crm_contact_team_members` if the test run in Task 1 hasn't already triggered it.

- [ ] **Step 2: Set at least one user's `designation`** via Admin > User Management to something containing one of the bucket keywords (e.g. "Regional AVP", "Ops Manager") — per the spec's own note, no seeded user currently has a sales-style designation, so all 4 bucket dropdowns will be empty until this is done. Pick 2-3 users across different buckets so the demo can show a non-trivial mapping.

- [ ] **Step 3: In the browser preview, open `/crm/contacts`** and verify:
  - Team column renders with "0" badges initially
  - The 4 new filter dropdowns appear and are populated with the users set up in Step 2
  - Row checkboxes appear (if the logged-in user has `crm_contacts`/`edit` permission) and "Bulk Team Mapping" is disabled until one is checked

- [ ] **Step 4: Click "Map Team" on one account row**, select a person in 2 of the 4 buckets, save, and confirm the redirect back to the list shows an updated Team badge count for that row, and that clicking the badge opens the read-only view showing the right name/bucket pairs.

- [ ] **Step 5: Check 2+ row checkboxes, click "Bulk Team Mapping"**, select one person in only the Manager bucket, save, and confirm both selected accounts now show that person under Manager in their read-view modal — and that any bucket the first account already had mapped (from Step 4) was left untouched.

- [ ] **Step 6: Open "Team Mapping CSV"**, download the sample, confirm it lists real account GSTINs/names with blank role columns, then upload a small edited copy mapping one more account and confirm the result summary + row-by-row report render correctly.

- [ ] **Step 7: Report the walkthrough results back to the user** (screenshots via the browser tool) and wait for explicit approval before any commit/push, per the deployment note at the top of this plan.

- [ ] **Step 8: Mark task complete (no git commit — wait for user go-ahead)**

---

## Self-Review Notes (from the writing-plans skill's own review pass)

- **Spec coverage:** Data model (Task 1), eligibility rule + whole-word matching (Task 2), filters + Team column + read-view + Map Team button + Bulk Team Mapping (Tasks 4, 8), single vs bulk replace semantics (Tasks 2, 5), CSV sample/upload/apply/reference panel (Task 6), permissions (`has_perm`/`require_module_perm` gating on every write path and every write-capable button — Tasks 5, 6, 8), migration + `db_validator` auto-provisioning caveat (Task 3). All 8 spec sections have a corresponding task.
- **Deviation from spec section 3's literal wording:** the spec describes the read-only Team-column modal as "GET a small partial." Research showed this codebase's actual established convention for the two structurally identical existing columns on this exact page (Locations count, Contacts count) is to embed the data as a per-row `data-*` JSON attribute and populate the modal client-side with zero extra requests — Task 8 follows that proven, simpler, already-in-production pattern instead, per writing-plans' own "follow established patterns" guidance. Same reasoning applied to the Map Team modal's pre-fill (also data-attribute-driven, no fetch route needed) — this removed 2 GET-partial routes and 2 templates from the original spec's implied file list without losing any spec-described capability.
- **Type/name consistency check:** `ROLE_BUCKETS` / `BUCKET_LABELS` / `BUCKET_KEYWORDS` keys (`vp_avp`, `manager`, `am_dm_gm`, `executive`) are used identically across `models/crm_team.py` (column values), `services/crm_team.py` (dict keys), `routers/crm_contacts.py` (Form field names `bucket_vp_avp` etc. and Query field names `f_vp_avp` etc.), and both templates (`bucket_options['vp_avp']`, `tm.get('vp_avp', [])`) — verified no drift.
- **No placeholders:** every step above contains complete, runnable code — confirmed via a fresh read-through immediately after writing this document.
