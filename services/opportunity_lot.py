"""Resolve the Lot behind a Buyer Deal.

A sales opportunity has no lot foreign key — it is created by Marking Won a
partner bid, and the bid is what carries the lot. Both the Buyer Deal detail
page (which shows the Lot Number) and the quote builder (which fills line items
from that lot's stock) need the same lookup, so it lives here rather than being
written twice and drifting apart.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def lot_for_opportunity(db: AsyncSession, opp_id):
    """The Lot this opportunity came from, or None if it was created by hand.

    Where several bids point at one opportunity, the highest is the winning one.
    """
    from models.partner import PartnerBid
    from models.lot import Lot

    bid = (await db.execute(
        select(PartnerBid)
        .where(PartnerBid.opportunity_id == opp_id, PartnerBid.lot_id.isnot(None))
        .order_by(PartnerBid.bid_amount.desc())
    )).scalars().first()
    if not bid:
        return None
    return (await db.execute(select(Lot).where(Lot.id == bid.lot_id))).scalar_one_or_none()
