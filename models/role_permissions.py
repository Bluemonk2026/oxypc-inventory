"""Role-based module permission matrix.

Each row stores what a named role can do for a specific module:
  can_enable  — the module is visible / accessible to this role
  can_add     — the role can create new records in this module
  can_edit    — the role can edit existing records
  can_upload  — the role can use bulk-upload / CSV import features

Admin role always bypasses all checks (full access).
Custom roles can be created by admin and assigned here.
"""
import uuid
from utils.timezone import app_now
from sqlalchemy import Column, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from database import Base


class RoleModulePermission(Base):
    __tablename__ = "role_module_permissions"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_name  = Column(String(60),  nullable=False, index=True)  # e.g. "sales", "iqc_inspector"
    module     = Column(String(60),  nullable=False)              # e.g. "lots", "repair_l1"
    can_enable = Column(Boolean, default=True)   # module visible / accessible
    can_add    = Column(Boolean, default=False)  # create records
    can_edit   = Column(Boolean, default=False)  # edit records
    can_upload = Column(Boolean, default=False)  # bulk upload / CSV import
    updated_at = Column(DateTime, default=app_now, onupdate=app_now)
    updated_by = Column(String(50), nullable=True)

    __table_args__ = (
        UniqueConstraint("role_name", "module", name="uq_role_module_perm"),
    )


class CustomRole(Base):
    """Admin-defined role names beyond the built-in UserRole enum."""
    __tablename__ = "custom_roles"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_name    = Column(String(60), unique=True, nullable=False, index=True)
    display_name = Column(String(100), nullable=False)
    created_by   = Column(String(50), nullable=True)
    created_at   = Column(DateTime, default=app_now)


class RoleAdditionalPermission(Base):
    """Cross-cutting, non-module-specific permissions per role — apply app-wide
    rather than to one module (unlike RoleModulePermission above).

      can_upload      — File Upload (any bulk-upload/import control app-wide)
      can_download    — File Download (any file/attachment download control)
      can_export      — File Export (CSV/Excel export buttons)
      can_print       — Print Page
      can_add_new_data — Add New Data (create-record actions app-wide)

    Admin role always bypasses all checks (full access), same as the module matrix.
    """
    __tablename__ = "role_additional_permissions"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_name        = Column(String(60), unique=True, nullable=False, index=True)
    can_upload       = Column(Boolean, default=True)
    can_download     = Column(Boolean, default=True)
    can_export       = Column(Boolean, default=True)
    can_print        = Column(Boolean, default=True)
    can_add_new_data = Column(Boolean, default=True)
    updated_at       = Column(DateTime, default=app_now, onupdate=app_now)
    updated_by       = Column(String(50), nullable=True)


# ── In-memory permissions cache ───────────────────────────────────────────────
# Populated on startup and refreshed whenever admin saves the matrix.
# Structure: {role_name: {module: {"enable": bool, "add": bool, "edit": bool, "upload": bool}}}
_PERM_CACHE: dict = {}

# Structure: {role_name: {"upload": bool, "download": bool, "export": bool, "print": bool, "add_new_data": bool}}
_ADDITIONAL_PERM_CACHE: dict = {}


def get_cached_additional_perms(role_name: str) -> dict:
    return _ADDITIONAL_PERM_CACHE.get(role_name, {})


def set_cached_additional_perms(role_name: str, perms: dict) -> None:
    _ADDITIONAL_PERM_CACHE[role_name] = perms


def has_additional_perm(role_name: str, action: str) -> bool:
    """Check if role_name has the given cross-cutting action allowed.
    Admin always returns True. Unknown roles default to True (permissive) —
    same "opt-in restriction" behavior as has_perm() below."""
    if role_name == "admin":
        return True
    perms = _ADDITIONAL_PERM_CACHE.get(role_name)
    if not perms:
        return True   # no row configured → allow everything
    return bool(perms.get(action, True))


def get_cached_perms(role_name: str) -> dict:
    """Return the cached permission dict for a role. Empty dict = no restrictions loaded."""
    return _PERM_CACHE.get(role_name, {})


def set_cached_perms(role_name: str, perms: dict) -> None:
    _PERM_CACHE[role_name] = perms


def has_perm(role_name: str, module: str, action: str = "enable") -> bool:
    """Check if role_name has the given action on module.
    Admin always returns True. Unknown roles/modules default to True (permissive).

    "enable" is the MASTER SWITCH for a module: if a role has the module enabled,
    it may fully use it (view + add + edit + upload). A disabled module blocks
    everything. The finer Add/Edit/Upload bits do NOT further restrict an enabled
    module — this avoids surprising 403s where an admin enabled a module for a role
    but left the Add/Edit boxes unchecked, then the role got 403 on create/edit.
    """
    if role_name == "admin":
        return True
    role_perms = _PERM_CACHE.get(role_name)
    if not role_perms:
        return True   # no matrix configured → allow everything
    mod_perms = role_perms.get(module)
    if not mod_perms:
        return True   # module not in matrix → allow
    return bool(mod_perms.get("enable", True))
