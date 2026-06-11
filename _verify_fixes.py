import asyncio, traceback, sys
sys.path.insert(0, ".")
from datetime import datetime
from sqlalchemy import select, func, or_
from sqlalchemy import case as sa_case
from sqlalchemy.orm import selectinload
from database import AsyncSessionLocal
from models.dealers import Dealer, DealerCall, DealerOrder
from models.user import User, UserRole

async def test():
    print("=== Verifying both fixes ===")
    async with AsyncSessionLocal() as db:
        # FIX 1: telecalling date_from as date object
        try:
            today = datetime.utcnow().date()
            date_from = today.isoformat()
            date_to = today.isoformat()
            recent_stmt = (
                select(DealerCall)
                .options(selectinload(DealerCall.dealer))
                .join(Dealer, DealerCall.dealer_id == Dealer.id)
                .where(
                    func.date(DealerCall.call_date) >= datetime.strptime(date_from, "%Y-%m-%d").date(),
                    func.date(DealerCall.call_date) <= datetime.strptime(date_to, "%Y-%m-%d").date(),
                )
                .order_by(DealerCall.call_date.desc()).limit(50)
            )
            recent_calls = (await db.execute(recent_stmt)).scalars().all()
            print(f"FIX 1 OK: telecalling recent_calls={len(recent_calls)}")
        except Exception as e:
            print(f"FIX 1 STILL FAILING: {e}")
            traceback.print_exc()

        # FIX 2: dealers recent_call_map with items_text key
        try:
            base_query = select(Dealer)
            dealers = (await db.execute(base_query.limit(50))).scalars().all()
            dealer_ids = [d.id for d in dealers]
            if dealer_ids:
                rn_col = func.row_number().over(
                    partition_by=DealerCall.dealer_id,
                    order_by=DealerCall.call_date.desc()
                ).label("rn")
                inner = select(
                    DealerCall.dealer_id, DealerCall.call_outcome, DealerCall.items_discussed, rn_col,
                ).where(DealerCall.dealer_id.in_(dealer_ids)).subquery()
                rc_rows = (await db.execute(
                    select(inner.c.dealer_id, inner.c.call_outcome, inner.c.items_discussed)
                    .where(inner.c.rn == 1)
                )).all()
                recent_call_map = {
                    str(r.dealer_id): {
                        "outcome": r.call_outcome,
                        "items_text": r.items_discussed or "",  # renamed key
                    }
                    for r in rc_rows
                }
                # Simulate what the template does with items_text
                for dealer_id, rc in recent_call_map.items():
                    _ = rc.get("items_text", "")[:40]  # same access pattern as template
                print(f"FIX 2 OK: recent_call_map={len(recent_call_map)} entries, items_text accessible")
        except Exception as e:
            print(f"FIX 2 STILL FAILING: {e}")
            traceback.print_exc()

asyncio.run(test())
