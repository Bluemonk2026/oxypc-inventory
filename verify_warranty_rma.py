"""
Throwaway verification script for Warranty + RMA feature.
Creates test Sale/Return/Device rows, verifies logic, then cleans up.
Run: python verify_warranty_rma.py
"""
import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select

from database import AsyncSessionLocal
from models.device import Device, DeviceStage
from models.lot import Lot
from models.sales import Sale, Return
from utils.timezone import app_now
from utils.warranty import compute_warranty_expiry, warranty_status_for_sale


async def main():
    async with AsyncSessionLocal() as db:
        # ── Setup: minimal Lot + Device to hang sales off ──────────────────
        lot = Lot(lot_number=f"TESTLOT-{uuid.uuid4().hex[:6]}", supplier_name="TestSupplier",
                  buying_price=1000, qty=4, purchase_date=app_now())
        db.add(lot)
        await db.flush()

        devices = []
        for i in range(4):
            d = Device(
                barcode=f"TESTDEV-{uuid.uuid4().hex[:8]}",
                lot_id=lot.id,
                current_stage=DeviceStage.ready_to_sale,
                brand="TestBrand", model="TestModel",
            )
            db.add(d)
            devices.append(d)
        await db.flush()

        now = app_now()

        # ── Check 3: warranty_expires_at computed correctly per type ───────
        print("=== Check 3: warranty_expires_at computation ===")
        expected_deltas = {
            "none": None,
            "30_days": timedelta(days=30),
            "6_months": timedelta(days=182),
            "1_year": timedelta(days=365),
        }
        sales = {}
        all_pass_3 = True
        for i, (wtype, delta) in enumerate(expected_deltas.items()):
            expires = compute_warranty_expiry(now, wtype)
            expected = (now + delta) if delta else None
            ok = (expires == expected)
            all_pass_3 = all_pass_3 and ok
            print(f"  warranty_type={wtype!r}: expires_at={expires} expected={expected} -> {'PASS' if ok else 'FAIL'}")
            s = Sale(
                sale_number=f"TESTSALE-{uuid.uuid4().hex[:8]}",
                device_id=devices[i].id, sale_price=1500,
                sold_by="verify_script", sold_at=now,
                warranty_type=wtype, warranty_expires_at=expires,
            )
            db.add(s)
            sales[wtype] = s
        await db.flush()
        print(f"Check 3 overall: {'PASS' if all_pass_3 else 'FAIL'}")

        # ── Check 4: warranty_status_for_sale for various scenarios ────────
        print("\n=== Check 4: RMA warranty_status computation ===")
        # (a) within warranty window (30_days sale, just made -> in_warranty)
        status_a = warranty_status_for_sale(sales["30_days"])
        ok_a = status_a == "in_warranty"
        print(f"  (a) 30_days sale just now -> {status_a} (expect in_warranty) -> {'PASS' if ok_a else 'FAIL'}")

        # (b) past warranty_expires_at -> out_of_warranty
        past_sale = Sale(
            sale_number=f"TESTSALE-{uuid.uuid4().hex[:8]}",
            device_id=devices[0].id, sale_price=1500,
            sold_by="verify_script",
            sold_at=now - timedelta(days=400),
            warranty_type="1_year",
            warranty_expires_at=compute_warranty_expiry(now - timedelta(days=400), "1_year"),
        )
        db.add(past_sale)
        await db.flush()
        status_b = warranty_status_for_sale(past_sale)
        ok_b = status_b == "out_of_warranty"
        print(f"  (b) 1_year sale from 400 days ago -> {status_b} (expect out_of_warranty) -> {'PASS' if ok_b else 'FAIL'}")

        # (c) warranty_type = none -> no_warranty
        status_c = warranty_status_for_sale(sales["none"])
        ok_c = status_c == "no_warranty"
        print(f"  (c) none warranty_type -> {status_c} (expect no_warranty) -> {'PASS' if ok_c else 'FAIL'}")

        check4_pass = ok_a and ok_b and ok_c
        print(f"Check 4 overall: {'PASS' if check4_pass else 'FAIL'}")

        # ── Simulate return_type persistence for customer/dealer ───────────
        print("\n=== Simulating Return rows: return_type customer/dealer ===")
        ret_customer = Return(
            sale_id=sales["30_days"].id, device_id=devices[1].id,
            reason="Not working", condition_on_return="As sold",
            action_taken="restock", reentered_stage="iqc",
            processed_by="verify_script",
            return_type="customer", serial_captured=devices[1].barcode,
            warranty_status=warranty_status_for_sale(sales["30_days"]),
            complaint_text="Screen flickers intermittently",
            approval_status="pending",
        )
        ret_dealer = Return(
            sale_id=past_sale.id, device_id=devices[0].id,
            reason="Wrong item", condition_on_return="Minor damage",
            action_taken="restock", reentered_stage="iqc",
            processed_by="verify_script",
            return_type="dealer", serial_captured=devices[0].barcode,
            warranty_status=warranty_status_for_sale(past_sale),
            complaint_text="Dealer bulk return - wrong spec shipped",
            approval_status="pending",
        )
        db.add(ret_customer)
        db.add(ret_dealer)
        await db.flush()

        ok_ret_c = ret_customer.return_type == "customer" and ret_customer.warranty_status == "in_warranty"
        ok_ret_d = ret_dealer.return_type == "dealer" and ret_dealer.warranty_status == "out_of_warranty"
        print(f"  customer return: return_type={ret_customer.return_type} warranty_status={ret_customer.warranty_status} -> {'PASS' if ok_ret_c else 'FAIL'}")
        print(f"  dealer return:    return_type={ret_dealer.return_type} warranty_status={ret_dealer.warranty_status} -> {'PASS' if ok_ret_d else 'FAIL'}")

        overall = all_pass_3 and check4_pass and ok_ret_c and ok_ret_d
        print(f"\n=== OVERALL: {'ALL CHECKS PASS' if overall else 'SOME CHECKS FAILED'} ===")

        # ── Cleanup: delete all test rows created in this script ───────────
        print("\nCleaning up test data...")
        await db.delete(ret_customer)
        await db.delete(ret_dealer)
        for s in sales.values():
            await db.delete(s)
        await db.delete(past_sale)
        for d in devices:
            await db.delete(d)
        await db.delete(lot)
        await db.commit()
        print("Cleanup done — no test rows remain.")


if __name__ == "__main__":
    asyncio.run(main())
