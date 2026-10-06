"""Seed the database with the demo data documented in the README.

    python scripts/seed.py            # run from the repo root (.env is read)

Design:
  * **Insert-only**: existing rows are never updated or deleted.
  * **Idempotent by natural keys** — email for users, the customer's own
    vehicle for the car, `Oil change` for the record — so running it
    twice on the same database changes nothing.
  * Built for a fresh database (local compose or a clean Neon branch).
    Production already carries its own demo data: against it, the users
    match and are skipped, but the vehicle/record chain may still be
    added, so prefer the seeded database you already have there.

Creates the three public demo accounts (README §Demo data), a verified
Toyota Corolla, one `completed` record and its `paid` payment of $89.99.
The vehicle photo is the only piece left out: it lives on Cloudinary and
is uploaded once through the UI.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

# `python scripts/seed.py` puts scripts/ on sys.path, not the repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.maintenance_record import MaintenanceRecord  # noqa: E402
from app.models.payment import Payment  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.vehicle import Vehicle  # noqa: E402

# Public by design: these are demo credentials for the live portfolio.
DEMO_USERS = (
    ("Demo Customer", "lmartinezcarbo1994@gmail.com", "ProdDemo-2026-vmapi", "customer"),
    ("Demo Mechanic", "lmartinezcarbo@gmail.com", "MechDemo-2026-vmapi", "mechanic"),
    ("Demo Admin", "lmartinezcarbo+admin@gmail.com", "AdminDemo-2026-vmapi", "admin"),
)

DEMO_DATE = datetime(2026, 9, 15, tzinfo=timezone.utc)
DEMO_LABOR = Decimal("89.99")


def main() -> None:
    db = SessionLocal()
    created: list[str] = []
    try:
        # --- users -----------------------------------------------------
        users: dict[str, User] = {}
        for name, email, password, role in DEMO_USERS:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(
                    name=name,
                    email=email,
                    password_hash=hash_password(password),
                    role=role,
                    email_verified=True,
                )
                db.add(user)
                created.append(f"user {email} ({role})")
            users[email] = user
        db.flush()

        # --- vehicle ---------------------------------------------------
        customer = users[DEMO_USERS[0][1]]
        vehicle = (
            db.query(Vehicle).filter(Vehicle.user_id == customer.id).first()
        )
        if vehicle is None:
            vehicle = Vehicle(
                user_id=customer.id,
                make="Toyota",
                model="Corolla",
                year=2020,
                vin="DEM0SEEDVEHICLE001",
                mileage=45000,
                verified=True,
            )
            db.add(vehicle)
            created.append("vehicle Toyota Corolla 2020 (verified)")
        db.flush()

        # --- record ----------------------------------------------------
        record = (
            db.query(MaintenanceRecord)
            .filter(
                MaintenanceRecord.vehicle_id == vehicle.id,
                MaintenanceRecord.service_type == "Oil change",
            )
            .first()
        )
        if record is None:
            record = MaintenanceRecord(
                vehicle_id=vehicle.id,
                service_type="Oil change",
                description="Full synthetic oil and filter replacement",
                mileage=45000,
                service_date=DEMO_DATE,
                labor_cost=DEMO_LABOR,
                status="completed",
                notes="Seeded demo record.",
            )
            db.add(record)
            created.append("record 'Oil change' (completed)")
        db.flush()

        # --- payment ---------------------------------------------------
        payment = (
            db.query(Payment)
            .filter(Payment.maintenance_record_id == record.id)
            .first()
        )
        if payment is None:
            payment = Payment(
                maintenance_record_id=record.id,
                amount=DEMO_LABOR,
                currency="usd",
                status="paid",
                stripe_checkout_session_id="cs_test_seed_demo",
                paid_at=DEMO_DATE,
            )
            db.add(payment)
            created.append("payment $89.99 (paid)")

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if created:
        print("Seeded:")
        for line in created:
            print(f"  - {line}")
    else:
        print("Nothing to do: the demo data is already there.")


if __name__ == "__main__":
    main()
