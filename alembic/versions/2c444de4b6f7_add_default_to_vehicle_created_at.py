"""add default to vehicle created_at

Revision ID: 2c444de4b6f7
Revises: 64c77cf67aaa
Create Date: 2026-09-16 17:00:15.116342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c444de4b6f7'
down_revision: Union[str, Sequence[str], None] = '64c77cf67aaa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "vehicles",
        "created_at",
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    pass
