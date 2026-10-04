from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.vehicle import Vehicle
    from app.models.refresh_token import RefreshToken
    from app.models.one_time_code import OneTimeCode


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String, nullable=False)

    email: Mapped[str] = mapped_column(
        String,
        unique=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String,
        nullable=False,
    )

    role: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="customer",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    
    vehicles: Mapped[list["Vehicle"]] = relationship(
        back_populates="user",
        # vehicles.user_id is ON DELETE RESTRICT: let the database refuse
        # the delete instead of nulling the foreign key here.
        passive_deletes=True,
    )

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        # ON DELETE CASCADE: a deleted user takes their sessions with them.
        passive_deletes=True,
    )

    one_time_codes: Mapped[list["OneTimeCode"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )