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
