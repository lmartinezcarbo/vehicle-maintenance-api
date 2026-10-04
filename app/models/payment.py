from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.maintenance_record import MaintenanceRecord


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)

    maintenance_record_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_records.id", ondelete="RESTRICT"),
        nullable=False,
    )

    amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
    )

    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="usd",
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="pending",
    )

    stripe_checkout_session_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    stripe_payment_intent_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    maintenance_record: Mapped["MaintenanceRecord"] = relationship(
        back_populates="payments"
    )

    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="check_payment_amount_non_negative",
        ),
        CheckConstraint(
            "status IN ('pending', 'paid', 'failed', 'expired')",
            name="check_payment_status",
        ),
        Index(
            "ix_payments_maintenance_record_id",
            "maintenance_record_id",
        ),
        Index(
            "ix_payments_stripe_checkout_session_id",
            "stripe_checkout_session_id",
        ),
        Index(
            "ix_payments_stripe_payment_intent_id",
            "stripe_payment_intent_id",
        ),
    )