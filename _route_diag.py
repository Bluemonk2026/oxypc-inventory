import asyncio, traceback, sys
sys.path.insert(0, ".")
from datetime import datetime
from sqlalchemy import select, func, or_
from sqlalchemy import case as sa_case
from sqlalchemy.orm import selectinload
from database import AsyncSessionLocal
from models.dealers import Dealer, DealerCall, DealerOrder
from models.user import User, UserRole

async def test_dealers():
    print("=== Testing dealers list_dealers logic ===")
    async with AsyncSessionLocal() as db:
        try:
            # Simulate what list_dealers does for an admin user
            base_query = select(Dealer)
            count_result = await db.execute(select(func.count()).select_from(base_query.subquery()))
            total_count = count_result.scalar() or 0
            print(f"Total dealers: {total_count}")

            dealers = (await db.execute(base_query.order_by(Dealer.business_name).limit(50))).scalars().all()
            dealer_ids = [d.id for d in dealers]
            print(f"Page dealers: {len(dealers)}")

            # Last call map
            if dealer_ids:
                lc_rows = await db.execute(
                    select(DealerCall.dealer_id, func.max(DealerCall.call_date).label("last_call"))
                    .where(DealerCall.dealer_id.in_(dealer_ids))
                    .group_by(DealerCall.dealer_id)
                )
                last_call_map = {str(r.dealer_id): r.last_call for r in lc_rows}
                print(f"last_call_map: {len(last_call_map)} entries")

            # Window function (most recent call per dealer)
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
                print(f"recent_call_map: {len(rc_rows)} entries")

            # Sales users
            su_result = await db.execute(
                select(User).where(
                    User.role.in_([UserRole.sales, UserRole.sales_manager, UserRole.telecaller]),
                    User.status == True,
                ).order_by(User.full_name)
            )
            sales_users = su_result.scalars().all()
            print(f"sales_users: {len(sales_users)}")

            print("dealers route: ALL OK")
        except Exception as e:
            print(f"dealers route FAILED: {e}")
            traceback.print_exc()

async def test_telecalling():
    print("\n=== Testing telecalling index logic ===")
    async with AsyncSessionLocal() as db:
        try:
            today = datetime.utcnow().date()
            base_stat_filter = [
                func.date(DealerCall.call_date) == today,
            ]
            stat_row = (await db.execute(
                select(
                    func.count(DealerCall.id),
                    func.count(sa_case((DealerCall.call_outcome != "no_answer", 1))),
                    func.count(sa_case((DealerCall.call_outcome == "interested", 1))),
                    func.count(sa_case((DealerCall.call_outcome == "order_placed", 1))),
                ).where(*base_stat_filter)
            )).one()
            print(f"Stats row: {stat_row}")

            fu_stmt = (
                select(DealerCall)
                .options(selectinload(DealerCall.dealer))
                .join(Dealer, DealerCall.dealer_id == Dealer.id)
                .where(
                    func.date(DealerCall.next_followup_date) == today,
                    DealerCall.call_outcome != "not_interested",
                )
                .order_by(DealerCall.next_followup_date)
            )
            followups_due = (await db.execute(fu_stmt)).scalars().all()
            print(f"followups_due: {len(followups_due)}")

            date_from = today.isoformat()
            date_to = today.isoformat()
            recent_stmt = (
                select(DealerCall)
                .options(selectinload(DealerCall.dealer))
                .join(Dealer, DealerCall.dealer_id == Dealer.id)
                .where(
                    func.date(DealerCall.call_date) >= date_from,
                    func.date(DealerCall.call_date) <= date_to,
                )
                .order_by(DealerCall.call_date.desc()).limit(50)
            )
            recent_calls = (await db.execute(recent_stmt)).scalars().all()
            print(f"recent_calls: {len(recent_calls)}")

            print("telecalling route: ALL OK")
        except Exception as e:
            print(f"telecalling route FAILED: {e}")
            traceback.print_exc()

async def main():
    await test_dealers()
    await test_telecalling()

asyncio.run(main())
