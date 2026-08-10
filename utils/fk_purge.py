"""Delete a parent row along with everything that references it.

Permanent lot deletion used to run a hand-written list of DELETE statements,
one per child table, in FK dependency order. That list fell 19 tables behind
the schema: every FK in this database is ON DELETE NO ACTION, so a single
child row in a table nobody remembered to add raised ForeignKeyViolation and
the page returned 500. On production, 22 of 287 lots could not be deleted.

This reads the foreign keys out of the live catalog instead, so a table added
next month is handled without anyone editing a list.

Rule per referencing column:

  NOT NULL  -> the row cannot exist without its parent, so delete it (after
               recursively clearing whatever references *it*).
  nullable  -> the reference is incidental. Set it to NULL and keep the row.
               A supplier payment, a CRM deal or a telecalling record must
               survive the deletion of a lot it happens to mention.

Two refinements the first version needed, both found by running it against
production data:

  * A nullable column can still be covered by a CHECK constraint that forbids
    NULL (partner_bids is one). The UPDATE is attempted inside a savepoint;
    if a check rejects it, the row genuinely cannot exist without its parent,
    so it is deleted instead.
  * Ids are materialised once and passed as an array rather than re-running
    "IN (SELECT ... WHERE lot_id = ...)" inside every child statement. The
    subquery form re-scanned devices for each of ~35 child tables and pushed a
    single lot delete past a 50-second statement timeout.
"""
import logging
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

HARD_DELETE = {
    "spare_parts_consumption",   # per-device parts usage, feeds COGS
    "spare_parts_ledger",        # per-device stock movements
    "ram_tracking",              # per-device RAM harvest/fit history
    "audit_scan_items",          # scan lines belong to their device
}

# Bounded so a FK cycle cannot recurse forever. The deepest real chain is
# lots -> devices -> sales -> customer_receipts.
_MAX_DEPTH = 8

_FK_CHILDREN = text("""
    SELECT child.relname AS child_tbl,
           a.attname     AS child_col,
           a.attnotnull  AS not_null
    FROM pg_constraint c
    JOIN pg_class child  ON child.oid  = c.conrelid
    JOIN pg_class parent ON parent.oid = c.confrelid
    JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON true
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
    WHERE c.contype = 'f' AND parent.relname = :parent
    ORDER BY 1, 2
""")


async def _children_of(db: AsyncSession, table: str):
    return (await db.execute(_FK_CHILDREN, {"parent": table})).all()


async def purge_references(
    db: AsyncSession,
    parent_table: str,
    parent_ids: list,
    _path: tuple = (),
) -> list[str]:
    """Clear everything referencing `parent_ids` in `parent_table`.

    Table and column names come from the Postgres catalog, never from user
    input; the ids travel as a bound parameter. Returns a log of what it did,
    which the caller records in the audit entry.
    """
    if not parent_ids or len(_path) >= _MAX_DEPTH or parent_table in _path:
        return []

    ids = [str(i) for i in parent_ids]
    done: list[str] = []

    for child_tbl, child_col, not_null in await _children_of(db, parent_table):
        if child_tbl == parent_table:
            continue  # self-reference: the parent delete covers it
        where = f"{child_col} = ANY(:ids)"

        if not_null or child_tbl in HARD_DELETE:
            done += await _delete_rows(db, child_tbl, child_col, where, ids, _path, parent_table)
            continue

        # Nullable — keep the row, drop the link. Guarded because a CHECK
        # constraint may still forbid NULL in that column.
        sp = await db.begin_nested()
        try:
            r = await db.execute(
                text(f"UPDATE {child_tbl} SET {child_col} = NULL WHERE {where}"), {"ids": ids})
            await sp.commit()
            if r.rowcount:
                done.append(f"unlinked {r.rowcount} {child_tbl}.{child_col}")
        except (IntegrityError, DBAPIError):
            await sp.rollback()
            _log.info("%s.%s cannot be NULL (check constraint) — deleting instead",
                      child_tbl, child_col)
            done += await _delete_rows(db, child_tbl, child_col, where, ids, _path, parent_table)

    return done


async def _delete_rows(db, child_tbl, child_col, where, ids, _path, parent_table) -> list[str]:
    """Delete matching rows, clearing whatever references them first."""
    done: list[str] = []

    # Only pay for the id lookup when something can actually reference this
    # table — most leaf tables (stage_movements, iqc_inspections) have none.
    if await _children_of(db, child_tbl):
        child_ids = (await db.execute(
            text(f"SELECT id FROM {child_tbl} WHERE {where}"), {"ids": ids})).scalars().all()
        done += await purge_references(db, child_tbl, child_ids, _path + (parent_table,))

    r = await db.execute(text(f"DELETE FROM {child_tbl} WHERE {where}"), {"ids": ids})
    if r.rowcount:
        done.append(f"deleted {r.rowcount} {child_tbl}")
    return done
