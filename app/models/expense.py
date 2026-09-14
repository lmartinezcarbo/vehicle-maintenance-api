from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle
    from app.models.maintenance_record import MaintenanceRecord

class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)

    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
    )

    maintenance_record_id: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    category: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    expense_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    vehicle: Mapped["Vehicle"] = relationship(
        back_populates="expenses"
    )
    maintenance_record: Mapped["MaintenanceRecord | None"] = relationship(
        back_populates="expenses"
    )
    __table_args__ = (
    CheckConstraint(
        "amount >= 0",
        name="check_expense_amount_non_negative",
        ),
        ForeignKeyConstraint(
            ["vehicle_id", "maintenance_record_id"],
            ["maintenance_records.vehicle_id", "maintenance_records.id"],
            ondelete="RESTRICT",
        ),
        Index("ix_expenses_vehicle_id", "vehicle_id"),
        Index(
            "ix_expenses_maintenance_record_id",
            "maintenance_record_id",
        ),
    )