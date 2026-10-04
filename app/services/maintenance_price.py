from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.maintenance_part import MaintenancePart


def calculate_maintenance_total(
    db: Session,
    maintenance_record_id: int,
    labor_cost: Decimal,
) -> Decimal:
    parts = (
        db.query(MaintenancePart)
        .filter(
            MaintenancePart.maintenance_record_id == maintenance_record_id
        )
        .all()
    )

    total = labor_cost

    for part in parts:
        total += part.quantity * part.unit_cost

    return total

def calculate_maintenance_totals(
    db: Session,
    maintenance_record_ids: list[int],
) -> dict[int, Decimal]:
    if not maintenance_record_ids:
        return {}

    rows = (
        db.query(
            MaintenancePart.maintenance_record_id,
            func.sum(
                MaintenancePart.quantity * MaintenancePart.unit_cost
            ),
        )
        .filter(
            MaintenancePart.maintenance_record_id.in_(
                maintenance_record_ids
            )
        )
        .group_by(MaintenancePart.maintenance_record_id)
        .all()
    )

    return {
        maintenance_record_id: total
        for maintenance_record_id, total in rows
    }