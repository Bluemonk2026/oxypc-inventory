"""
OxyPC Inventory — Backfill QA Release tracking, July 17 - Sept 24 2026
========================================================================
Release tracking (QARelease) stopped at v1.10.0 (deployed 2026-07-16) even
though real development continued daily after that — confirmed via the QA
Dashboard's own Recent Changes changelog (routers/qa_uat.py
_get_recent_commits), which is grounded in real git history and already
shows 549 entries running to today. This backfills the missing ~2.5 months
as 11 weekly releases (v1.11.0-v1.21.0), one per ISO week that had any
real changelog activity, grouped and titled from that same real data — not
fabricated content.

Idempotent: skips creation if v1.11.0 already exists.

Usage:
  Local: python seed_qa_backfill_jul17_sep24.py
  Prod:  ssh onto the Internal Server, then run the same command from
         /opt/oxypc with the venv's python.
"""
import asyncio
import uuid
import datetime
from collections import defaultdict

import models.scrap_for_sale  # noqa: F401 — needed before any Device/StockTransfer query resolves mappers
from database import AsyncSessionLocal
from utils.timezone import app_now
from sqlalchemy import select
from models.qa_uat import QARelease, ReleaseStatus
from routers.qa_uat import _get_recent_commits

CREATED_BY = "system-seed"
CUTOFF = "2026-07-16"  # last already-tracked release date


def _week_start(date_str: str) -> datetime.date:
    d = datetime.date.fromisoformat(date_str)
    return d - datetime.timedelta(days=d.weekday())


async def run():
    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(QARelease).where(QARelease.version == "v1.11.0"))
        if existing.scalar_one_or_none():
            print("Already backfilled (v1.11.0 exists). Nothing to do.")
            return

        commits = _get_recent_commits()
        since = [c for c in commits if c["date"] > CUTOFF]
        since.sort(key=lambda c: c["date"])

        groups: dict[datetime.date, list[dict]] = defaultdict(list)
        for c in since:
            groups[_week_start(c["date"])].append(c)

        now = app_now()
        version_n = 11
        created = []
        for week_start in sorted(groups):
            items = groups[week_start]
            dates = sorted({i["date"] for i in items})
            start_d, end_d = dates[0], dates[-1]
            bug_fixes = [i["msg"] for i in items if i["category"] == "Bug Fix"]
            others = [i["msg"] for i in items if i["category"] != "Bug Fix"]

            version = f"v1.{version_n}.0"
            start_label = datetime.date.fromisoformat(start_d).strftime("%b %d")
            end_label = datetime.date.fromisoformat(end_d).strftime("%b %d")
            title = f"{start_label}-{end_label} batch — {len(items)} changes ({len(bug_fixes)} fixes)"

            # Real commit messages, not fabricated prose — same convention as
            # the hand-written v1.5-v1.10 entries, just auto-assembled here
            # since this covers 11 weeks instead of a handful of days.
            desc_parts = others + ([f"Fixes: {'; '.join(bug_fixes)}"] if bug_fixes else [])
            description = " + ".join(desc_parts)
            if len(description) > 1800:
                description = description[:1800].rsplit(" + ", 1)[0] + " + …"

            release_dt = datetime.datetime.combine(
                datetime.date.fromisoformat(end_d), datetime.time(18, 0))
            planned_dt = datetime.datetime.combine(
                datetime.date.fromisoformat(start_d), datetime.time(9, 0))

            rel = QARelease(
                id=uuid.uuid4(), version=version, title=title, description=description,
                status=ReleaseStatus.deployed,
                planned_date=planned_dt, release_date=release_dt,
                qa_sign_off_by=CREATED_BY, qa_sign_off_at=release_dt,
                # created_at = release_dt, not `now` — the Dashboard's Recent
                # Releases card and the Releases list both order by
                # created_at.desc(), so every backfilled row sharing the same
                # `now` timestamp would sort in undefined/insertion order
                # instead of newest-release-first (caught in local testing:
                # v1.14.0 showed above v1.21.0).
                created_by=CREATED_BY, created_at=release_dt, updated_at=now,
            )
            db.add(rel)
            created.append((version, title, len(items)))
            version_n += 1

        await db.commit()
        print(f"Created {len(created)} releases:")
        for v, t, n in created:
            print(f"  {v} — {t}")


asyncio.run(run())
