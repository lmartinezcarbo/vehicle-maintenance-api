from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, Boolean
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

    # Generated name inside settings.uploads_dir - never the filename the
    # client sent, which is how path traversal gets in. None means the
    # (optional) photo has not been uploaded.
    photo_file: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    @property
    def has_photo(self) -> bool:
        return self.photo_file is not None

    user: Mapped["User"] = relationship(
        back_populates="vehicles"
    )

    maintenance_records: Mapped[list["MaintenanceRecord"]] = relationship(
        back_populates="vehicle",
        # ON DELETE RESTRICT lives in the database; the ORM must not turn a
        # "still referenced" refusal into a null write.
        passive_deletes=True,
    )

    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="vehicle",
        passive_deletes=True,
    )

    __table_args__ = (
    CheckConstraint(
        "mileage >= 0",
        name="check_vehicle_mileage_non_negative",
        ),
        Index("ix_vehicles_user_id", "user_id"),
    )