"""First-run accounts for FieldOps.

Creates the admin from FIELDOPS_ADMIN_PASSWORD and the project's role accounts.
Runs on every start but only ever fills in what is missing — it never resets a
password or overwrites a role an administrator has since changed.
"""

from sqlalchemy import select

from auth.dependencies import hash_password
from fieldops_db import (
    FIELDOPS_ADMIN_PASSWORD,
    FIELDOPS_ADMIN_USERNAME,
    FIELDOPS_DEMO_PASSWORD,
    FieldOpsAudit,
    FieldOpsUser,
)

# The project's working roles. Site assignments are left to the admin — they
# depend on which of the 622 locations each engineer is actually covering.
ROLE_ACCOUNTS = [
    ("U01", "qc.eng.04",   "Rahul Verma",  "fe",         "West"),
    ("U02", "qc.eng.11",   "Anita Joshi",  "fe",         "South"),
    ("U03", "coord.west",  "Suresh Nair",  "coord",      "West"),
    ("U04", "pmo.national","Priya Menon",  "pmo",        "All"),
    ("U05", "rel.spoc",    "Ramesh Kadam", "spoc",       "West"),
    ("U06", "rel.qc.appr", "Meera Rao",    "approver",   "All"),
    ("U07", "rel.comm",    "Vikram Shah",  "commercial", "All"),
    ("U08", "pickup.desk", "Sunil Pawar",  "packer",     "All"),
    ("U09", "courier.desk","Deepa Iyer",   "courier",    "All"),
    ("U10", "wh.mumbai01", "Arjun Patel",  "warehouse",  "All"),
]


async def seed_accounts(session) -> dict:
    created, notes = [], []

    existing = (await session.execute(select(FieldOpsUser))).scalars().all()
    by_username = {u.username.lower(): u for u in existing}

    # ---------- administrator ----------
    admin = by_username.get(FIELDOPS_ADMIN_USERNAME.lower())
    if admin is None:
        if not FIELDOPS_ADMIN_PASSWORD:
            notes.append(
                "FIELDOPS_ADMIN_PASSWORD is not set — no administrator was created. "
                "Set it and restart; nobody can sign in until then."
            )
        else:
            admin = FieldOpsUser(
                id="U00",
                username=FIELDOPS_ADMIN_USERNAME,
                name="System Administrator",
                password_hash=hash_password(FIELDOPS_ADMIN_PASSWORD),
                role="admin",
                region="All",
                sites=[],
                perms={"allow": [], "deny": []},
                status="active",
                created_by="bootstrap",
            )
            session.add(admin)
            session.add(FieldOpsAudit(actor="bootstrap", action="admin_created",
                                      target=FIELDOPS_ADMIN_USERNAME,
                                      detail="created from FIELDOPS_ADMIN_PASSWORD"))
            created.append(FIELDOPS_ADMIN_USERNAME)
    elif FIELDOPS_ADMIN_PASSWORD and not admin.password_hash:
        # admin exists but has no usable password (e.g. seeded before the var was set)
        admin.password_hash = hash_password(FIELDOPS_ADMIN_PASSWORD)
        notes.append("Administrator password set from FIELDOPS_ADMIN_PASSWORD.")

    # ---------- project role accounts ----------
    demo_hash = hash_password(FIELDOPS_DEMO_PASSWORD) if FIELDOPS_DEMO_PASSWORD else None
    for uid, username, name, role, region in ROLE_ACCOUNTS:
        if username.lower() in by_username:
            continue
        session.add(
            FieldOpsUser(
                id=uid,
                username=username,
                name=name,
                # No shared password unless one was deliberately configured: this
                # app is reachable by anyone with the URL, so known credentials
                # would be an open door.
                password_hash=demo_hash,
                must_change_password=bool(demo_hash),
                role=role,
                region=region,
                sites=[],
                perms={"allow": [], "deny": []},
                status="active",
                created_by="bootstrap",
            )
        )
        created.append(username)

    if created and not demo_hash:
        notes.append(
            "Role accounts were created without a password — an administrator must "
            "set one for each before they can sign in (or set FIELDOPS_DEMO_PASSWORD)."
        )

    return {"created": created, "notes": notes}
