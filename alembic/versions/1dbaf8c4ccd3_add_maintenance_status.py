"""add maintenance status

Revision ID: 1dbaf8c4ccd3
Revises: 0dc839bc1c52
Create Date: 2026-09-27 14:56:42.193556

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1dbaf8c4ccd3'
down_revision: Union[str, Sequence[str], None] = '0dc839bc1c52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "maintenance_records",
        sa.Column("status", sa.String(), nullable=True),
    )

    op.execute(
        "UPDATE maintenance_records "
        "SET status = 'in_progress' "
        "WHERE status IS NULL"
    )

    op.alter_column(
        "maintenance_records",
        "status",
        nullable=False,
    )

    op.create_check_constraint(
        "check_maintenance_status",
        "maintenance_records",
        "status IN ('in_progress', 'ready')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "check_maintenance_status",
        "maintenance_records",
        type_="check",
    )

    op.drop_column(
        "maintenance_records",
        "status",
    )