"""add defaults to created_at columns

Revision ID: 97f6ebfd81fb
Revises: 2c444de4b6f7
Create Date: 2026-09-16 18:24:11.960942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97f6ebfd81fb'
down_revision: Union[str, Sequence[str], None] = '2c444de4b6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "maintenance_records",
        "created_at",
        server_default=sa.text("now()"),
    )

    op.alter_column(
        "expenses",
        "created_at",
        server_default=sa.text("now()"),
    )

def downgrade() -> None:
    """Downgrade schema."""
    pass
