---
name: regression-sweep
description: Use before reporting a batch of changes done in OxyPC Inventory when the change touched base.html, a Jinja global/filter, a shared macro, or any file included by many templates/routes. Runs a full-repo parse + route scan to catch regressions across pages you didn't directly test.
---

# Full-Repo Regression Sweep (OxyPC Inventory)

A change to `base.html` or a global once broke 8 unrelated pages
(`self.page_title()` threw `UndefinedError` on every template that never
defines a `page_title` block) and was only caught because this sweep ran
proactively. Run it any time a shared file changes.

## Step 1 — Full template parse (all ~159 templates)

```python
from jinja2 import Environment, FileSystemLoader
import glob, os

env = Environment(loader=FileSystemLoader('templates'))
env.globals.update(
    has_perm=lambda *a, **k: True, any_perm=lambda *a, **k: True,
    master_options=lambda *a, **k: [], role_display=lambda r: str(r),
    sidebar_label=lambda k: k, resolve_page_title=lambda p: None,
    ASSET_VERSION='1',
)
env.filters.update(ist=lambda d, *a: '', ist_date=lambda d: '',
                    ist_time=lambda d: '', ist_datetime=lambda d: '')

errors = []
for path in glob.glob('templates/**/*.html', recursive=True):
    rel = os.path.relpath(path, 'templates').replace(os.sep, '/')
    try:
        env.get_template(rel)
    except Exception as e:
        errors.append((rel, str(e)))

print(f"{len(errors)} template errors" if errors else "0 template errors")
for rel, e in errors:
    print(rel, '->', e)
```
Expected: **0 errors.**

## Step 2 — Route scan (`_scan_routes.py`, repo root)

```bash
python _scan_routes.py
```

**Established baseline: exactly 9 flagged routes.** These are expected
(missing-required-query-param 400s, or legitimate polling 404s), not bugs:
`/admin/master/permissions/load`, `/devices/api/brief`, `/iqc/api/health`,
`/iqc/api/users`, `/iqc/lookup`, `/iqc/usb-import` (404), `/lots/api/exists`,
`/stress/has-results`, `/whatsapp/qr-poll` (404).

**Any run producing MORE than these 9 is a real regression** — read the
traceback, find the shared file/global that broke, fix it, and re-run both
steps until back to 0 template errors / exactly 9 flagged routes.

## Step 3 — Schema check

```bash
python db_validator.py
```
Must report "Schema is in sync with ORM models -- no issues found."

## Jinja block-inheritance gotcha

`self.blockname()` requires `blockname` to be defined as a `{% block %}`
**somewhere in the child's inheritance chain** — if some child template never
defines that block, `self.blockname()` throws
`UndefinedError: 'jinja2.runtime.TemplateReference object' has no attribute`.

Safe pattern for "child's override, or empty string if child never defines
it, without double-rendering":
```jinja
{% set _var %}{% block name %}{% endblock %}{% endset %}
{{ override or _var }}
```
Verify new instances of this pattern with a standalone
`jinja2.Environment(loader=DictLoader(...))` test covering both "child
defines block" and "child omits block" before trusting it.
