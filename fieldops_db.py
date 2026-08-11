"""Reliance Asset FieldOps — its own database, engine and models.

FieldOps runs standalone: its own login, its own users, its own data. It shares
OxyPC's process and domain, and nothing else. This module keeps that promise in
code — a separate engine on a separate connection string, a separate metadata,
and no foreign key anywhere into OxyPC's tables.

Set FIELDOPS_DATABASE_URL to give it a database of its own. Without that variable
it falls back to OxyPC's Postgres connection but keeps its own tables and its own
metadata — no foreign keys either way, and OxyPC's schema tooling never sees these
tables, so the field project can still be dumped or dropped on its own. Setting the
variable later moves it to a truly separate database with no code change.
"""

import os
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import JSON

from utils.timezone import app_now

# ---------------------------------------------------------------- configuration
FIELDOPS_DATABASE_URL = (
    os.environ.get("FIELDOPS_DATABASE_URL")
    or os.environ.get("OXYPC_FIELDOPS_DATABASE_URL")
    or ""
).strip()

# Password for the bootstrap admin, read once at first start. Never stored in
# the repo, never logged.
FIELDOPS_ADMIN_PASSWORD = os.environ.get("FIELDOPS_ADMIN_PASSWORD", "").strip()
FIELDOPS_ADMIN_USERNAME = os.environ.get("FIELDOPS_ADMIN_USERNAME", "admin").strip() or "admin"

# Optional: gives the seeded demo role accounts a working password. Unset means
# they exist with the right roles but cannot sign in until an admin sets one.
FIELDOPS_DEMO_PASSWORD = os.environ.get("FIELDOPS_DEMO_PASSWORD", "").strip()


# separate-database | shared-database | unavailable
MODE = "unavailable"


def configured() -> bool:
    return engine is not None


def mode() -> str:
    return MODE


class FieldOpsBase(DeclarativeBase):
    """Separate metadata — OxyPC's create_all must never touch these tables."""


_JSON = JSON().with_variant(JSONB, "postgresql")

engine = None
SessionLocal = None

if FIELDOPS_DATABASE_URL:
    engine = create_async_engine(
        FIELDOPS_DATABASE_URL,
        pool_size=int(os.environ.get("FIELDOPS_DB_POOL_SIZE", "5")),
        max_overflow=int(os.environ.get("FIELDOPS_DB_MAX_OVERFLOW", "3")),
        pool_pre_ping=True,
        echo=False,
    )
    MODE = "separate-database"
else:
    # No dedicated connection string: share OxyPC's Postgres, keep our own
    # tables. Still separable — nothing here is in OxyPC's metadata and no
    # foreign key crosses between them.
    try:
        from database import engine as _oxypc_engine

        engine = _oxypc_engine
        MODE = "shared-database"
    except Exception:      # noqa: BLE001 — no database at all; routes report it
        engine = None

if engine is not None:
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_fieldops_db():
    if SessionLocal is None:
        raise RuntimeError("FieldOps database is not configured")
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# --------------------------------------------------------------------- models
class FieldOpsUser(FieldOpsBase):
    """A person who can sign in to FieldOps. Created by an admin, never self-served."""

    __tablename__ = "fieldops_users"

    id = Column(String(24), primary_key=True)                 # U01, U02 …
    username = Column(String(80), nullable=False, unique=True, index=True)
    name = Column(String(120), nullable=False)
    password_hash = Column(String(255), nullable=True)        # null = cannot sign in yet
    role = Column(String(32), nullable=False, default="fe")   # FieldOps role key
    region = Column(String(40), nullable=False, default="All")
    sites = Column(_JSON, nullable=False, default=list)       # assigned site ids
    perms = Column(_JSON, nullable=False, default=dict)       # {allow:[], deny:[]}
    status = Column(String(16), nullable=False, default="active")   # active | inactive

    must_change_password = Column(Boolean, nullable=False, default=False)
    failed_logins = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_login = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=app_now, nullable=False)
    created_by = Column(String(80), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=app_now, onupdate=app_now, nullable=False)

    def to_dict(self) -> dict:
        """Shape the field app expects — never includes the hash."""
        return {
            "id": self.id,
            "emp": self.username,
            "name": self.name,
            "role": self.role,
            "region": self.region,
            "sites": list(self.sites or []),
            "perms": dict(self.perms or {}),
            "status": self.status,
            "has_password": bool(self.password_hash),
            "must_change_password": bool(self.must_change_password),
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


class FieldOpsRecord(FieldOpsBase):
    """One version of one app record — the shared store devices sync against."""

    __tablename__ = "fieldops_records"

    id = Column(String(120), primary_key=True)        # "<kind>:<record id>"
    kind = Column(String(32), nullable=False, index=True)
    rec_id = Column(String(80), nullable=False)
    data = Column(_JSON, nullable=False)

    updated_at = Column(DateTime(timezone=True), default=app_now, nullable=False, index=True)
    updated_by = Column(String(120), nullable=True)
    device_updated_at = Column(String(40), nullable=True)
    deleted = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("kind", "rec_id", name="uq_fieldops_kind_rec"),
        Index("ix_fieldops_updated_kind", "updated_at", "kind"),
    )


class FieldOpsAudit(FieldOpsBase):
    """Server-side audit of account and data administration.

    Distinct from the app's own workflow audit log (which syncs as records):
    this one records what happened to *accounts and the store itself*, and it is
    written only by the server, so it cannot be edited from a device.
    """

    __tablename__ = "fieldops_admin_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime(timezone=True), default=app_now, nullable=False, index=True)
    actor = Column(String(80), nullable=True)
    action = Column(String(60), nullable=False)
    target = Column(String(120), nullable=True)
    detail = Column(Text, nullable=True)
    ip = Column(String(64), nullable=True)


async def init_fieldops_db():
    """Create tables and any bootstrap admin. Safe to call on every start."""
    if not configured():
        return {"configured": False, "mode": MODE}

    async with engine.begin() as conn:
        await conn.run_sync(FieldOpsBase.metadata.create_all)

    from fieldops_seed import seed_accounts

    async with SessionLocal() as session:
        result = await seed_accounts(session)
        await session.commit()
    result["configured"] = True
    result["mode"] = MODE
    return result
