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


# ── In-memory permissions cache ───────────────────────────────────────────────
# Populated on startup and refreshed whenever admin saves the matrix.
# Structure: {role_name: {module: {"enable": bool, "add": bool, "edit": bool, "upload": bool}}}
_PERM_CACHE: dict = {}


def get_cached_perms(role_name: str) -> dict:
    """Return the cached permission dict for a role. Empty dict = no restrictions loaded."""
    return _PERM_CACHE.get(role_name, {})


def set_cached_perms(role_name: str, perms: dict) -> None:
    _PERM_CACHE[role_name] = perms


def has_perm(role_name: str, module: str, action: str = "enable") -> bool:
    """Check if role_name has the given action on module.
    Admin always returns True. Unknown roles/modules default to True (permissive).
    """
    if role_name == "admin":
        return True
    role_perms = _PERM_CACHE.get(role_name)
    if not role_perms:
        return True   # no matrix configured → allow everything
    mod_perms = role_perms.get(module)
    if not mod_perms:
        return True   # module not in matrix → allow
    return bool(mod_perms.get(action, True))
