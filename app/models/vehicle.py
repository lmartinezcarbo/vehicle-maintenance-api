from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.maintenance_record import MaintenanceRecord
    from app.models.expense import Expense


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )

    make: Mapped[str] = mapped_column(String, nullable=False)

    model: Mapped[str] = mapped_column(String, nullable=False)

    year: Mapped[int] = mapped_column(nullable=False)

    vin: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    mileage: Mapped[int] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        back_populates="vehicles"
    )

    maintenance_records: Mapped[list["MaintenanceRecord"]] = relationship(
        back_populates="vehicle"
    )

    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="vehicle"
    )

    __table_args__ = (
    CheckConstraint(
        "mileage >= 0",
        name="check_vehicle_mileage_non_negative",
        ),
        Index("ix_vehicles_user_id", "user_id"),
    )