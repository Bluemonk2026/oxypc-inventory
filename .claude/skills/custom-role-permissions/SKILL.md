---
name: custom-role-permissions
description: Use whenever a page conditionally shows/hides a button, section, or action based on current_user.role, or when a user reports "role X can't see/do Y even though it should be allowed". OxyPC supports admin-created custom roles (e.g. trc_manager) not in the UserRole enum, and hardcoded role checks silently break for them.
---

# Custom Role Permission Checks (OxyPC Inventory)

## The bug pattern

`models/user.py`'s `UserRole` enum only lists built-in roles (admin,
inventory_manager, iqc_inspector, l1/l2/l3_engineer, qc_inspector, sales,
spare_parts_manager, telecaller, sales_manager). But `User.role` is stored as
free text via a `RoleType` TypeDecorator, so admins can create custom roles
(e.g. `trc_manager`) that aren't in the enum.

`auth/dependencies.py`'s `require_roles(*roles)` already handles this
correctly on the backend: it lets any non-builtin role through UNLESS the
allow-list is exactly `{UserRole.admin}`. But templates that copy this logic
as a hardcoded check —

```jinja
{% set _appr = current_user.role.value in ['admin','sales_manager'] %}
```

— silently break for custom roles, because the endpoint behind the button
works fine (backend uses `require_roles`) but the button itself never renders.
This is exactly the bug reported for TRC Manager's Approve button
(`dispatch/list.html`).

## The fix — always use `role_allowed()`, never hardcode

`templates_config.py` exposes a Jinja global that mirrors `require_roles()`:

```python
def _role_allowed(role, *allowed_values):
    role_val = getattr(role, "value", None) or str(role)
    if role_val in allowed_values:
        return True
    if role_val not in _BUILTIN_ROLE_VALUES and set(allowed_values) != {"admin"}:
        return True
    return False
templates.env.globals["role_allowed"] = _role_allowed
```

In templates, replace:
```jinja
{% set _appr = current_user.role.value in ['admin','sales_manager'] %}
```
with:
```jinja
{% set _appr = role_allowed(current_user.role, 'admin', 'sales_manager') %}
```

## Known remaining occurrence

`templates/crm/dashboard.html:179` has the same hardcoded-check bug
(`{% set _sm = current_user.role.value in ['admin','sales_manager'] %}`) —
found but deliberately left unfixed (out of scope for the batch that found
it). Fix opportunistically if you're touching that file, using the same
`role_allowed()` pattern.

## How to verify

Write a throwaway `verify_*.py` httpx script that overrides
`get_current_user` with three fake users: a `RoleValue("trc_manager")` (or
whatever custom role is in question), a `UserRole.sales` (should stay
excluded unless explicitly allowed), and `UserRole.admin`/`UserRole.sales_manager`
(should still work). Confirm the button/section renders for the custom role
and admin/sales_manager, and not for sales.
