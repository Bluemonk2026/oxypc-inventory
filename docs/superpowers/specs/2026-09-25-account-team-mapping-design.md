# Account Team Mapping — Design Spec

**Date:** 2026-09-25
**Status:** Approved by Pankaj, ready for implementation plan.

## 1. Problem / Goal

The Accounts (CRM Contacts) List page has no way to record which internal
people (by seniority tier) are responsible for a given account. This adds:

- A per-company "team" of mapped users, grouped into 4 fixed seniority
  buckets: **VP/AVP**, **Manager**, **AM/DM/GM**, **Executive/Sr Executive**.
- Filters on the Accounts List to slice accounts by mapped team member.
- A modal to assign/replace a company's (or several companies') team, either
  one row at a time or via checkbox multi-select ("Bulk Team Mapping").
- An optional CSV bulk-upload path for the same mapping, keyed on GSTIN.

## 2. Data Model

### New table: `crm_contact_team_members`

| Column | Type | Notes |
|---|---|---|
| `id` | UUID, PK | `default=uuid.uuid4` |
| `contact_id` | UUID, FK → `crm_contacts.id`, NOT NULL, indexed | the Account |
| `user_id` | UUID, FK → `users.id`, NOT NULL, indexed | the mapped team member |
| `role_bucket` | String(20), NOT NULL | one of `vp_avp`, `manager`, `am_dm_gm`, `executive` |
| `created_at` | DateTime, `default=app_now` | |
| `created_by` | String(50), FK → `users.username`, nullable | who made this mapping (audit) |

- Unique constraint on `(contact_id, user_id, role_bucket)` — the same
  person can't be double-mapped into the same bucket for the same company,
  but *can* appear in different buckets for the same company, or in
  different buckets across different companies.
- No soft-delete column: mapping rows are fully replaced (deleted +
  re-inserted) on every save, per the "replace" semantics below — not edited
  in place. `audit_logs` (existing central table) captures the before/after
  for compliance, same convention as every other write in this app.
- New model file: `models/crm_team.py` (small, single-purpose, following the
  file-per-concern convention already used for `models/crm.py` vs.
  `models/dealers.py` etc.).

### Bucket eligibility (who can appear in a bucket's dropdown)

A helper function `eligible_users_for_bucket(users, bucket) -> list[User]`
in a new `services/crm_team.py` (or alongside the router — decided at plan
time) computes eligibility by checking **both** `User.designation` and
`User.role.value`, case-insensitive, **whole-word** match (regex word
boundary, not raw substring — `ILIKE '%AM%'` would false-positive on "TEAM"
or "SAM"):

| Bucket | Matches whole word(s) |
|---|---|
| `vp_avp` | "VP" or "AVP" |
| `manager` | "Manager" |
| `am_dm_gm` | "AM", "DM", or "GM" |
| `executive` | "Executive" (covers "Sr Executive" too, since it contains the word) |

A user can be eligible for more than one bucket if their designation
contains multiple keywords. As of this session, no user has a sales-style
`designation` set (production only has shop-floor values like "Masking",
"Repair Engineer") — all 4 buckets will be empty until designations are
populated via User Management. This is expected, not a bug to fix here.

## 3. Accounts List page (`templates/crm/contacts/list.html`, `routers/crm_contacts.py`)

### Filters
4 new multiselect filter dropdowns (Tom Select, matching the existing
pattern in `templates/devices/list.html`), placed in the filter bar:
"VP/AVP", "Manager", "AM/DM/GM", "Executive/Sr Executive" — each populated
via `eligible_users_for_bucket`. Selecting one or more users in a dropdown
filters the list to accounts where that user is mapped in that bucket
(`EXISTS` subquery against `crm_contact_team_members`, `user_id IN (...)
AND role_bucket = '<bucket>'`).

### New "Team" column
Inserted before "Created By" (column order doc comment + DataTables
`columnDefs` `orderable:false` targets both need updating, same care taken
earlier this session for the Status-column move). Shows a badge with the
mapped-member count for that row (0 renders as a muted "—" or "0", not a
broken link). Click → GET a small partial into a **read-only Bootstrap
modal** listing name + bucket label per mapped member for that one company.

### "Map Team" button (per row)
Added to the Actions cell. Opens the **Map Team modal** (section 4) scoped
to that single company, pre-filled with its current mapping.

### "Bulk Team Mapping" button
Row checkboxes already exist for other bulk actions elsewhere in this app's
list pages — reuse the same convention. When 1+ rows are checked, a
"Bulk Team Mapping" button appears in the toolbar. Opens the **same** Map
Team modal, scoped to all checked companies, dropdowns starting empty.

## 4. Map Team modal (shared component)

Single Jinja partial (`templates/crm/contacts/_map_team_modal.html`),
included once in `list.html`, driven by a small amount of JS to swap its
scope (single company vs. bulk) before opening — same pattern as other
modals in this codebase that are shared across trigger points.

- **Header**: single-company mode shows the company name; bulk mode shows
  "**N companies selected**".
- **Body**: 4 Tom Select multiselects, one per bucket, each populated from
  `eligible_users_for_bucket`.
  - Single-company mode: each multiselect pre-selected with that company's
    current mapping for that bucket (fetched on modal open).
  - Bulk mode: all four start empty.
- **Save** (`POST /crm/contacts/team-mapping`, form fields: `contact_ids[]`,
  and one multi-value field per bucket, plus a hidden `mode` field —
  `single` or `bulk`): for every contact_id in scope, each bucket is
  replaced with whatever was submitted for it (delete existing rows for
  that `(contact_id, bucket)` pair, insert the new selection).
  - **Single-company mode**: since the modal pre-fills current state, a
    bucket left empty is a deliberate "clear this bucket" — replaced with
    nothing.
  - **Bulk mode**: since the modal starts every bucket empty regardless of
    each company's actual current state, an empty bucket here is
    ambiguous ("clear everyone" vs. "I didn't mean to touch this bucket")
    — treated as **leave unchanged**, not clear. Only buckets where the
    admin actually selected at least one person get replaced (across all
    companies in scope); untouched buckets are skipped entirely. This
    avoids bulk-mapping one bucket accidentally wiping the other three
    across every selected company.

  Wrapped in one DB transaction per submit. Audit-logged per contact
  touched.

## 5. Bulk CSV upload (optional path)

New sub-route under the existing Accounts bulk-upload area (alongside the
existing `/crm/contacts/upload`), e.g. `/crm/contacts/team-mapping/upload`,
following the exact structure of the existing bulk-upload page
(`templates/crm/contacts/upload.html`, `routers/crm_contacts.py`
`upload_contacts_csv`) rather than inventing a new pattern.

- **"Download Sample"**: exports every existing Account (not a blank
  template) with columns `gstin, company_name, vp_avp, manager, am_dm_gm,
  executive` — GSTIN/company name pre-filled, role columns blank. Company
  name is for the uploader's reference only; GSTIN is the actual match key.
- **Reference panel**: alongside the upload form, a read-only table of
  every eligible user across all 4 buckets — display name, role, and
  designation — so the uploader can copy-paste an exact name rather than
  guess spelling.
- **Upload/apply** (`POST /crm/contacts/team-mapping/upload`): for each row —
  1. Reject rows with no GSTIN (per your confirmation: companies must have
     GSTIN for this path).
  2. Match GSTIN → `CRMContact` (case-normalized, same `.strip().upper()`
     convention already used for the Accounts dedupe key). No match →
     row-level error in the result report, skipped.
  3. For each of the 4 role columns with a non-empty cell: split on comma
     (multiple names per cell, matching the multiselect semantics), look up
     each name against `User.full_name` (or whichever exact display-name
     field the User model exposes — confirmed at plan time), case-sensitive
     exact match.
     - Zero matches or 2+ matches for a name → that cell flagged as an
       error in the result report; that name is skipped (doesn't block the
       rest of the row).
  4. Apply the same **replace** semantics as the modal: for each
     `(contact, bucket)` pair present in the row (i.e. the cell wasn't
     blank), replace that bucket's mapping with the resolved user list.
     A blank cell for a bucket leaves that bucket **untouched** (bulk CSV
     doesn't get a way to explicitly "clear" a bucket to empty — only the
     modal does, since a blank spreadsheet cell is ambiguous between "no
     change" and "clear," whereas an empty multiselect in the modal is
     unambiguous).
  5. Result report (same pattern as the existing bulk-upload's summary):
     rows applied / rows skipped with reasons, shown after upload.

## 6. Permissions

Map Team / Bulk Team Mapping / bulk-upload-apply follow the same permission
gate as editing an Account (existing CRM contacts edit permission) — no new
permission node. Viewing the Team column / read-only modal follows the
existing view gate for the Accounts List page. (Confirm at plan time against
`models/role_permissions.py` if a narrower gate is wanted later — not
blocking for this build.)

## 7. Out of scope (explicitly deferred)

- Editing/removing a single mapped person without going through the full
  replace flow (e.g. a per-row "×" in the read-only Team modal) — the
  replace-based Map Team modal already covers removal by unchecking.
- Notifications to a newly-mapped team member.
- Historical "who was mapped when" reporting beyond what `audit_logs`
  already captures generically.
- A dedicated permission node scoped specifically to team mapping.

## 8. Open items for the implementation plan (not blocking spec approval)

- Exact column/index migration details (new table, indexes on
  `contact_id`/`user_id`, unique constraint) — an Alembic migration
  following the project's established `index_exists`-guarded pattern, with
  the same caveat noted earlier this session: this project's live schema
  drifts from Alembic history via `db_validator`'s own auto-provisioning,
  so the plan should apply the table creation directly (verified against
  both databases) rather than assume `alembic upgrade` alone deploys it.
- Confirm exact `User` field name for "display full name" used in bulk
  upload matching (likely `full_name`).
- DataTables column-index bookkeeping for the new "Team" column, mirroring
  the care taken for the Status-column move earlier this session.
