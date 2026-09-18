from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle
    from app.models.maintenance_part import MaintenancePart
    from app.models.expense import Expense


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"

    id: Mapped[int] = mapped_column(primary_key=True)

    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    service_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    mileage: Mapped[int] = mapped_column(nullable=False)

    service_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    labor_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )
    vehicle: Mapped["Vehicle"] = relationship(
        back_populates="maintenance_records"
    )
    parts: Mapped[list["MaintenancePart"]] = relationship(
        back_populates="maintenance_record",
        cascade="all, delete-orphan",
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="maintenance_record"
    )
    __table_args__ = (
    CheckConstraint(
        "mileage >= 0",
        name="check_maintenance_mileage_non_negative",
        ),
    CheckConstraint(
        "labor_cost >= 0",
        name="check_labor_cost_non_negative",
        ),
    UniqueConstraint(
        "vehicle_id",
        "id",
        name="uq_maintenance_records_vehicle_id_id",
        ),
    Index("ix_maintenance_records_vehicle_id", "vehicle_id"),
    )