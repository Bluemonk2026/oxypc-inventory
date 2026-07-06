---
name: verify-feature
description: Use after implementing any router/template change in OxyPC Inventory, before reporting it done or asking to commit. Runs the project's standard compile+parse+functional verification sequence.
---

# Verify Feature (OxyPC Inventory)

No feature is "done" here until it passes this exact sequence. Skipping steps has
previously let a real regression (Jinja `self.block()` UndefinedError) slip past —
don't skip.

## Steps

1. **Compile-check every changed Python file:**
   ```bash
   python -m py_compile routers/<file>.py models/<file>.py services/<file>.py
   ```

2. **Jinja2 parse-check every changed template** (and, if `base.html` or a shared
   macro/global changed, ALL templates):
   ```python
   from jinja2 import Environment, FileSystemLoader
   env = Environment(loader=FileSystemLoader('templates'))
   env.globals.update(
       has_perm=lambda *a, **k: True, any_perm=lambda *a, **k: True,
       master_options=lambda *a, **k: [], role_display=lambda r: str(r),
       sidebar_label=lambda k: k, resolve_page_title=lambda p: None,
       ASSET_VERSION='1',
   )
   env.filters.update(ist=lambda d, *a: '', ist_date=lambda d: '',
                       ist_time=lambda d: '', ist_datetime=lambda d: '')
   env.get_template('path/to/changed.html')  # or loop templates/**/*.html for a full sweep
   ```

3. **Schema check** (skip only if you're certain no model changed):
   ```bash
   python db_validator.py
   ```
   Must print "Schema is in sync with ORM models -- no issues found."

4. **Functional verify script** — write a throwaway `verify_<feature>.py` in the
   repo root, following this shape:
   ```python
   import asyncio
   from httpx import AsyncClient, ASGITransport
   from main import app
   from database import get_db, AsyncSessionLocal
   from auth.dependencies import get_current_user
   from models.user import UserRole

   CURRENT_USER = {"user": None}

   class FakeAdmin:
       id = None
       username = "verify_admin"
       role = UserRole.admin
       status = True
       full_name = "Verify Admin"

   async def override_user():
       return CURRENT_USER["user"]

   async def override_db():
       async with AsyncSessionLocal() as db:
           yield db

   app.dependency_overrides[get_current_user] = override_user
   app.dependency_overrides[get_db] = override_db

   async def main():
       CURRENT_USER["user"] = FakeAdmin()
       transport = ASGITransport(app=app, raise_app_exceptions=True)
       async with AsyncClient(transport=transport, base_url="http://test") as c:
           c.cookies.set("csrf_token", "verify-csrf-token")
           # ... assert the actual behavior you changed ...
       # ... clean up any DB rows this script created ...
       print("ALL CHECKS PASSED")

   if __name__ == "__main__":
       asyncio.run(main())
   ```
   - Always create real dependent rows (e.g. a real `Device`/`Lot`) rather than
     omitting NOT NULL FKs like `PartRequest.device_id`.
   - Always clean up test data created (delete + commit) before finishing.
   - Delete the throwaway script once it passes — it's not part of the repo.

5. **Truncate audit `record_id`** — any time a fix/feature writes an `AuditLog`
   row that joins multiple IDs into `record_id` (String(50)), truncate:
   `record_id=",".join(str(x.id) for x in items)[:50]` or
   `record_id=f"bulk:{len(items)}"`. This overflow caused a real 500 in
   Assign Dealer Leads — don't reintroduce it.

6. If the change touches `base.html`, a shared global, or a widely-extended
   block: invoke **regression-sweep** before reporting done.

## When this is NOT enough

If the change has no observable server-side behavior (pure CSS, static copy),
steps 1–2 suffice. Otherwise all steps apply.
