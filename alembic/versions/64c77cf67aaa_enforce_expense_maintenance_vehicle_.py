"""enforce expense maintenance vehicle integrity

Revision ID: 64c77cf67aaa
Revises: 46cb6ea4cf1b
Create Date: 2026-09-13 19:35:33.984411

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64c77cf67aaa'
down_revision: Union[str, Sequence[str], None] = '46cb6ea4cf1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_maintenance_records_vehicle_id_id",
        "maintenance_records",
        ["vehicle_id", "id"],
    )

    op.drop_constraint(
        "expenses_maintenance_record_id_fkey",
        "expenses",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "fk_expenses_vehicle_maintenance",
        "expenses",
        "maintenance_records",
        ["vehicle_id", "maintenance_record_id"],
        ["vehicle_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_expenses_vehicle_maintenance",
        "expenses",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_maintenance_records_vehicle_id_id",
        "maintenance_records",
        type_="unique",
    )