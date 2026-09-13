from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.maintenance_part import MaintenancePart


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    manufacturer: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    part_number: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    maintenance_parts: Mapped[list["MaintenancePart"]] = relationship(
    back_populates="part"
)
    __table_args__ = (
        UniqueConstraint(
            "manufacturer",
            "part_number",
        ),
    )
