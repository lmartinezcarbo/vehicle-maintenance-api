"""allow completed maintenance status

Autogenerate produced an empty script for this one: Alembic does not compare
check constraints, so a change to a CHECK has to be written by hand and
checked against a database built only from migrations.

Revision ID: 214fb3b098ed
Revises: f0b38cfaaf97
Create Date: 2026-10-04 14:13:47.094967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '214fb3b098ed'
down_revision: Union[str, Sequence[str], None] = 'f0b38cfaaf97'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "check_maintenance_status",
        "maintenance_records",
        type_="check",
    )
    op.create_check_constraint(
        "check_maintenance_status",
        "maintenance_records",
        "status IN ('in_progress', 'ready', 'completed')",
    )


def downgrade() -> None:
    # Rows already in the new state do not fit the narrower constraint.
    op.execute(
        "UPDATE maintenance_records "
        "SET status = 'ready' "
        "WHERE status = 'completed'"
    )
    op.drop_constraint(
        "check_maintenance_status",
        "maintenance_records",
        type_="check",
    )
    op.create_check_constraint(
        "check_maintenance_status",
        "maintenance_records",
        "status IN ('in_progress', 'ready')",
    )
