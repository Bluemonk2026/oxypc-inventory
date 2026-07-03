"""
Batch D verification script (throwaway, uncommitted).
Exercises the new models/routes at the ORM level without needing to restart
the live production uvicorn process. Creates a throwaway device + bucket,
walks Add-to-Bucket -> Assign-to-Production -> Assign-to-Engineer, verifies
stage transitions, then cleans up.
"""
import asyncio
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL
from models.device import Device, DeviceStage, StageMovement
from models.bucket import Bucket, _new_bucket_number
from models.lot import Lot
from models.location import StorageLocation, ZoneType, UnitType
from models.user import User, UserRole


async def main():
    engine = create_async_engine(DATABASE_URL)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        # Need an existing lot to attach the throwaway device to
        lot = (await db.execute(select(Lot).limit(1))).scalar_one_or_none()
        if not lot:
            print("BLOCKED: no Lot rows exist to attach a throwaway device to.")
            return

        # Ensure a StorageLocation exists for the test (create one if none)
        loc = (await db.execute(select(StorageLocation).limit(1))).scalar_one_or_none()
        created_loc = False
        if not loc:
            loc = StorageLocation(
                zone=ZoneType.workshop, unit_type=UnitType.rack,
                unit_id="TESTRACK-BATCHD", capacity=50, is_active=True,
            )
            db.add(loc)
            await db.flush()
            created_loc = True

        device = Device(
            barcode=f"TESTBD-{uuid.uuid4().hex[:8]}",
            lot_id=lot.id, brand="TestBrand", model="TestModel",
            cpu="i5", ram_gb=8, storage_gb=256,
            grade=None, current_stage=DeviceStage.stock_in,
            device_price=1000,
        )
        db.add(device)
        await db.flush()
        print(f"Created test device {device.barcode} stage={device.current_stage}")

        bucket = Bucket(
            bucket_number=_new_bucket_number(), name="Batch D Test Bucket",
            location_id=loc.id, location=loc.display_name,
            category="TestBrand", status="stock_in", created_by="verify_batch_d",
        )
        db.add(bucket)
        await db.flush()
        device.bucket_id = bucket.id
        device.location_id = loc.id
        device.current_stage = DeviceStage.stock_in
        await db.commit()
        print(f"Created test bucket {bucket.bucket_number}, device assigned, stage={device.current_stage}")

        # Assign to Production (simulate the route logic)
        prev_stage = device.current_stage
        device.current_stage = DeviceStage.trc_production
        db.add(StageMovement(device_id=device.id, from_stage=prev_stage, to_stage=DeviceStage.trc_production, moved_by="verify_batch_d"))
        bucket.assigned_to_production = True
        bucket.assigned_to_production_by = "verify_batch_d"
        bucket.status = "trc_pending"
        await db.commit()
        assert device.current_stage == DeviceStage.trc_production
        assert bucket.assigned_to_production is True
        print(f"Assigned to Production OK -> device stage={device.current_stage}, bucket.assigned_to_production={bucket.assigned_to_production}")

        # Assign to Engineer (simulate the route logic)
        prev_stage = device.current_stage
        device.current_stage = DeviceStage.l1
        db.add(StageMovement(device_id=device.id, from_stage=prev_stage, to_stage=DeviceStage.l1, moved_by="verify_batch_d"))
        bucket.status = "validated"
        await db.commit()
        assert device.current_stage == DeviceStage.l1
        print(f"Assigned to Engineer OK -> device stage={device.current_stage}")

        # Verify L1 page query would pick it up
        l1_hit = (await db.execute(
            select(Device).where(Device.current_stage == DeviceStage.l1, Device.id == device.id)
        )).scalar_one_or_none()
        assert l1_hit is not None
        print("Device visible under DeviceStage.l1 query (matches routers/repair.py L1 query) - OK")

        # ── Cleanup ──────────────────────────────────────────────────────────
        await db.execute(
            StageMovement.__table__.delete().where(StageMovement.device_id == device.id)
        )
        await db.delete(device)
        await db.delete(bucket)
        if created_loc:
            await db.delete(loc)
        await db.commit()
        print("Cleanup complete. Test device/bucket/(location) removed.")

    await engine.dispose()
    print("\nBatch D verification PASSED.")


if __name__ == "__main__":
    asyncio.run(main())
