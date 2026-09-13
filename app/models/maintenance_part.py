from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.maintenance_record import MaintenanceRecord
    from app.models.part import Part


class MaintenancePart(Base):
    __tablename__ = "maintenance_parts"

    id: Mapped[int] = mapped_column(primary_key=True)

    maintenance_record_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_records.id", ondelete="CASCADE"),
        nullable=False,
    )

    part_id: Mapped[int] = mapped_column(
        ForeignKey("parts.id", ondelete="RESTRICT"),
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(
        nullable=False,
    )

    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )
    maintenance_parts: Mapped[list["MaintenancePart"]] = relationship(
        back_populates="part"
    )
    part: Mapped["Part"] = relationship(
        back_populates="maintenance_parts"
    )   
    __table_args__ = (
        UniqueConstraint(
            "maintenance_record_id",
            "part_id",
        ),
    )
    __table_args__ = (
    UniqueConstraint("maintenance_record_id", "part_id"),
    CheckConstraint(
        "quantity >= 1",
        name="check_quantity_positive",
        ),
    CheckConstraint(
        "unit_cost >= 0",
        name="check_unit_cost_non_negative",
        ),
    Index(
        "ix_maintenance_parts_maintenance_record_id",
        "maintenance_record_id",
        ),
    Index(
        "ix_maintenance_parts_part_id",
        "part_id",
        ),
    )