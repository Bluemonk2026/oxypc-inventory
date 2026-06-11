import asyncio, traceback, sys
sys.path.insert(0, ".")

async def test():
    from database import AsyncSessionLocal
    from models.dealers import Dealer, DealerCall
    from sqlalchemy import select, func
    from sqlalchemy import case as sa_case
    from sqlalchemy.orm import selectinload

    async with AsyncSessionLocal() as db:
        try:
            await db.execute(select(Dealer).limit(1))
            print("Dealer query OK")
        except Exception as e:
            print("Dealer query FAIL:", e)
            traceback.print_exc()

        try:
            await db.execute(
                select(DealerCall).options(selectinload(DealerCall.dealer)).limit(1)
            )
            print("DealerCall+dealer selectinload OK")
        except Exception as e:
            print("DealerCall selectinload FAIL:", e)
            traceback.print_exc()

        try:
            await db.execute(
                select(
                    func.count(DealerCall.id),
                    func.count(sa_case((DealerCall.call_outcome != "no_answer", 1))),
                )
            )
            print("sa_case aggregation OK")
        except Exception as e:
            print("sa_case aggregation FAIL:", e)
            traceback.print_exc()

asyncio.run(test())
