"""
OxyPC Inventory — Dummy Data Seeder
Inserts ~100 records across all tables for UAT/testing.
Usage: python seed_dummy_data.py
WARNING: Run only on a test/dev database. This ADDS to existing data.
"""
import asyncio
import random
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from config import DATABASE_URL
from models.user import User, UserRole
from models.lot import Lot
from models.device import Device, DeviceStage, StageMovement
from models.repair import RepairJob, RepairStatus
from models.qc import QCCheck
from models.sales import Sale, Return
from models.spare_parts import SparePart, SparePartPurchase, SparePartConsumption, RAMTracking
from auth.dependencies import hash_password

random.seed(42)

# ── Helpers ──────────────────────────────────────────────────────────────────

def rdate(days_ago_max=180):
    return datetime.utcnow() - timedelta(days=random.randint(0, days_ago_max))

def pick(*items):
    return random.choice(items)

BRANDS_MODELS = [
    ("HP", ["EliteBook 840 G6", "ProBook 450 G7", "Pavilion 15", "EliteBook 830 G8", "ZBook 15"]),
    ("Dell", ["Latitude 5420", "Inspiron 15 3000", "XPS 13", "Vostro 3500", "Precision 3550"]),
    ("Lenovo", ["ThinkPad T480", "IdeaPad 330", "ThinkPad X1 Carbon", "Legion 5", "ThinkBook 14"]),
    ("Asus", ["VivoBook 15", "ZenBook 14", "ROG Strix G15", "ExpertBook B1"]),
    ("Acer", ["Aspire 5", "Swift 3", "Nitro 5", "TravelMate P2"]),
]
GRADES = ["A", "B", "B", "C", "C", "D"]
STAGES_ALL = [
    DeviceStage.iqc, DeviceStage.stock_in, DeviceStage.l1, DeviceStage.l2,
    DeviceStage.qc_check, DeviceStage.ready_to_sale, DeviceStage.sold,
]
PAYMENT_MODES = ["cash", "upi", "card", "credit"]
REPAIR_ISSUES = ["Screen crack", "Battery drain", "Keyboard malfunction", "No POST",
                 "Fan noise", "Charging port loose", "RAM slot failure", "HDD bad sectors",
                 "Wi-Fi not working", "Touchpad unresponsive"]
PART_NAMES = [
    ("RAM", "DDR4 8GB RAM"), ("RAM", "DDR4 4GB RAM"), ("RAM", "DDR3 4GB RAM"),
    ("SSD", "256GB SSD"), ("SSD", "512GB NVMe SSD"), ("HDD", "500GB HDD"),
    ("Battery", "HP Battery 45W"), ("Battery", "Dell Battery 65W"),
    ("Screen", "14-inch FHD IPS Panel"), ("Screen", "15.6-inch HD Panel"),
    ("Keyboard", "HP UK Keyboard"), ("Keyboard", "Dell US Keyboard"),
    ("Charger", "HP 65W Charger"), ("Charger", "Dell 65W Charger"),
    ("Cable", "USB-C Cable"), ("Other", "Thermal Paste"), ("Other", "Screws Set"),
]
CUSTOMER_NAMES = [
    "Rahul Sharma", "Priya Patel", "Amit Verma", "Neha Gupta", "Sanjay Kumar",
    "Pooja Singh", "Rajesh Mehta", "Kavita Rao", "Vikram Nair", "Anita Joshi",
]


# ── Seeders ──────────────────────────────────────────────────────────────────

async def seed_users(session: AsyncSession):
    users = [
        ("iqc1", "IQC Inspector 1", UserRole.iqc_inspector),
        ("l1eng", "L1 Engineer Rohit", UserRole.l1_engineer),
        ("l2eng", "L2 Engineer Suresh", UserRole.l2_engineer),
        ("qcinsp", "QC Inspector Meena", UserRole.qc_inspector),
        ("salesexec", "Sales Executive Arjun", UserRole.sales),
        ("invmgr", "Inventory Manager Deepak", UserRole.inventory_manager),
        ("spares1", "Spare Parts Manager Ritu", UserRole.spare_parts_manager),
    ]
    created = []
    for uname, fname, role in users:
        existing = await session.execute(select(User).where(User.username == uname))
        if not existing.scalar_one_or_none():
            u = User(username=uname, full_name=fname, password_hash=hash_password("Test@1234"),
                     role=role, status=True, created_by="seed")
            session.add(u)
            created.append(uname)
    await session.flush()
    print(f"  Users: {len(created)} created (password: Test@1234)")
    return created


async def seed_lots(session: AsyncSession) -> list:
    lots = []
    suppliers = ["ABC Traders", "TechRecycle Pvt Ltd", "RefurbHub", "IT Asset Solutions", "GreenPC Wholesale"]
    for i in range(1, 6):
        lot_num = f"LOT-TEST-{i:03d}"
        existing = await session.execute(select(Lot).where(Lot.lot_number == lot_num))
        if existing.scalar_one_or_none():
            r = await session.execute(select(Lot).where(Lot.lot_number == lot_num))
            lots.append(r.scalar_one())
            continue
        qty = random.randint(8, 25)
        lot = Lot(
            lot_number=lot_num,
            supplier_name=pick(*suppliers),
            buying_price=random.randint(30000, 120000),
            qty=qty,
            purchase_date=rdate(180),
            invoice_no=f"INV-2024-{i:04d}",
            notes=f"Test lot {i} for UAT",
            created_by="seed",
        )
        session.add(lot)
        lots.append(lot)
    await session.flush()
    print(f"  Lots: {len(lots)} available")
    return lots


async def seed_devices(session: AsyncSession, lots: list) -> list:
    devices = []
    for idx in range(1, 91):
        barcode = f"OXY-TEST-{idx:05d}"
        existing = await session.execute(select(Device).where(Device.barcode == barcode))
        if existing.scalar_one_or_none():
            r = await session.execute(select(Device).where(Device.barcode == barcode))
            devices.append(r.scalar_one())
            continue
        brand, models = pick(*BRANDS_MODELS)
        model = pick(*models)
        lot = pick(*lots)
        # Distribute stages
        if idx <= 10:
            stage = DeviceStage.iqc
        elif idx <= 20:
            stage = DeviceStage.stock_in
        elif idx <= 30:
            stage = DeviceStage.l1
        elif idx <= 40:
            stage = DeviceStage.l2
        elif idx <= 50:
            stage = DeviceStage.qc_check
        elif idx <= 65:
            stage = DeviceStage.ready_to_sale
        else:
            stage = DeviceStage.sold  # will create sale records later

        device = Device(
            barcode=barcode, lot_id=lot.id,
            brand=brand, model=model,
            device_type="Laptop",
            serial_no=f"SN{random.randint(100000, 999999)}",
            ram_gb=pick(4, 8, 8, 16),
            storage_gb=pick(128, 256, 256, 512),
            storage_type=pick("HDD", "SSD", "SSD", "NVMe SSD"),
            color=pick("Black", "Silver", "Dark Grey"),
            grade=pick(*GRADES),
            current_stage=stage,
            floor=pick("Floor 1", "Floor 2", "Warehouse"),
            notes=None,
        )
        session.add(device)
        await session.flush()

        movement = StageMovement(
            device_id=device.id, from_stage=None, to_stage=DeviceStage.iqc,
            moved_by="seed", notes="Seeded"
        )
        session.add(movement)

        if stage != DeviceStage.iqc:
            mov2 = StageMovement(
                device_id=device.id, from_stage=DeviceStage.iqc, to_stage=stage,
                moved_by="seed", notes="Seeded progression"
            )
            session.add(mov2)

        devices.append(device)

    await session.flush()
    print(f"  Devices: {len(devices)} available")
    return devices


async def seed_repair_jobs(session: AsyncSession, devices: list):
    count = 0
    repair_stages = [DeviceStage.l1, DeviceStage.l2]
    for device in devices:
        if device.current_stage in repair_stages:
            stage_str = device.current_stage.value.upper()
            job = RepairJob(
                device_id=device.id, stage=stage_str,
                engineer_name="Seeded Engineer",
                issue_description=pick(*REPAIR_ISSUES),
                status=RepairStatus.in_progress,
            )
            session.add(job)
            count += 1
    await session.flush()
    print(f"  Repair jobs: {count} created")


async def seed_qc_checks(session: AsyncSession, devices: list):
    count = 0
    for device in devices:
        if device.current_stage in (DeviceStage.qc_check, DeviceStage.ready_to_sale, DeviceStage.sold):
            qc = QCCheck(
                device_id=device.id,
                inspector_name="QC Inspector Meena",
                result="pass",
                grade=device.grade,
                issues_found=None,
                notes="Seeded QC pass",
            )
            session.add(qc)
            count += 1
    await session.flush()
    print(f"  QC checks: {count} created")


async def seed_sales(session: AsyncSession, devices: list):
    count = 0
    sale_num = 1
    for device in devices:
        if device.current_stage == DeviceStage.sold:
            sale = Sale(
                sale_number=f"SALE-SEED-{sale_num:04d}",
                device_id=device.id,
                sale_price=random.randint(8000, 45000),
                customer_name=pick(*CUSTOMER_NAMES),
                customer_phone=f"9{random.randint(100000000, 999999999)}",
                invoice_no=f"SINV-{sale_num:04d}",
                payment_mode=pick(*PAYMENT_MODES),
                sold_by="salesexec",
                notes=None,
            )
            session.add(sale)
            sale_num += 1
            count += 1
    await session.flush()
    print(f"  Sales: {count} created")

    # Add 3 returns
    ret_result = await session.execute(
        select(Sale).order_by(Sale.sold_at).limit(3)
    )
    returns_added = 0
    for sale in ret_result.scalars().all():
        dev_r = await session.execute(select(Device).where(Device.id == sale.device_id))
        device = dev_r.scalar_one_or_none()
        if device:
            ret = Return(
                sale_id=sale.id, device_id=device.id,
                reason=pick("Not working", "Customer changed mind", "Wrong item"),
                condition_on_return=pick("As sold", "Minor damage"),
                processed_by="salesexec",
                refund_amount=float(sale.sale_price),
                notes="Seeded return",
            )
            device.current_stage = DeviceStage.returned
            session.add(ret)
            returns_added += 1
    await session.flush()
    print(f"  Returns: {returns_added} created")


async def seed_spare_parts(session: AsyncSession) -> list:
    parts = []
    for i, (cat, name) in enumerate(PART_NAMES, start=1):
        code = f"PART-SEED-{i:04d}"
        existing = await session.execute(select(SparePart).where(SparePart.part_code == code))
        if existing.scalar_one_or_none():
            r = await session.execute(select(SparePart).where(SparePart.part_code == code))
            parts.append(r.scalar_one())
            continue
        part = SparePart(
            part_code=code, name=name, category=cat,
            unit_price=random.randint(200, 5000),
            qty_in_stock=random.randint(5, 30),
            min_stock_alert=5,
            supplier="ABC Electronics",
        )
        session.add(part)
        parts.append(part)
    await session.flush()
    print(f"  Spare parts: {len(parts)} available")
    return parts


async def seed_part_purchases(session: AsyncSession, parts: list):
    count = 0
    for part in parts[:8]:
        purchase = SparePartPurchase(
            part_id=part.id,
            qty=random.randint(10, 50),
            unit_price=part.unit_price,
            total_price=part.unit_price * 20,
            supplier="ABC Electronics",
            invoice_no=f"PINV-{random.randint(1000, 9999)}",
            purchase_date=rdate(90),
            purchased_by="spares1",
        )
        session.add(purchase)
        count += 1
    await session.flush()
    print(f"  Part purchases: {count} created")


async def seed_consumption(session: AsyncSession, parts: list, devices: list):
    count = 0
    repair_devices = [d for d in devices if d.current_stage in (DeviceStage.l1, DeviceStage.l2, DeviceStage.qc_check)]
    for device in repair_devices[:10]:
        part = pick(*parts[:8])
        cons = SparePartConsumption(
            part_id=part.id, device_id=device.id,
            qty_used=1,
            unit_cost=float(part.unit_price),
            total_cost=float(part.unit_price),
            stage=device.current_stage.value,
            used_by="l1eng",
            notes="Seeded consumption",
        )
        part.qty_in_stock = max(0, part.qty_in_stock - 1)
        session.add(cons)
        count += 1
    await session.flush()
    print(f"  Part consumptions: {count} created")


async def seed_ram_tracking(session: AsyncSession, devices: list):
    count = 0
    for device in devices[:5]:
        entry = RAMTracking(
            action="removed",
            device_id=device.id,
            ram_gb=4,
            ram_type="DDR4",
            by_user="l1eng",
            notes="Seeded RAM removal",
        )
        session.add(entry)
        count += 1
    await session.flush()
    print(f"  RAM tracking: {count} entries created")


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  OxyPC Inventory — Dummy Data Seeder")
    print("=" * 60)
    print(f"\nDatabase: {DATABASE_URL}\n")

    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with SessionLocal() as session:
        await seed_users(session)
        lots = await seed_lots(session)
        devices = await seed_devices(session, lots)
        await seed_repair_jobs(session, devices)
        await seed_qc_checks(session, devices)
        await seed_sales(session, devices)
        parts = await seed_spare_parts(session)
        await seed_part_purchases(session, parts)
        await seed_consumption(session, parts, devices)
        await seed_ram_tracking(session, devices)
        await session.commit()

    await engine.dispose()
    print("\n" + "=" * 60)
    print("  Dummy data seeded successfully!")
    print("  Test users (password: Test@1234):")
    print("    iqc1, l1eng, l2eng, qcinsp, salesexec, invmgr, spares1")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
