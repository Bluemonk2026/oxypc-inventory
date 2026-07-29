"""Shared salesperson helpers."""
async def sales_person_options(db) -> list[str]:
    """Distinct salespeople already recorded, for the New Sale datalist.

    A suggestion list, not a constraint: the field stays free text so a new
    starter can be credited immediately. Its job is to stop the same person
    being entered as "Manoj", "manoj" and "Manoj " and fragmenting reports.
    Draws from BOTH sale types so either form suggests the full set.
    """
    from sqlalchemy import select, union
    from models.sales import Sale
    from models.part_sales import PartSale
    a = (await db.execute(select(Sale.sales_person).where(Sale.sales_person.isnot(None)).distinct())).scalars().all()
    b = (await db.execute(select(PartSale.sales_person).where(PartSale.sales_person.isnot(None)).distinct())).scalars().all()
    return sorted({x.strip() for x in list(a) + list(b) if x and x.strip()})
