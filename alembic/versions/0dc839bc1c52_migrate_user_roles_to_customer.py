"""migrate user roles to customer

Revision ID: 0dc839bc1c52
Revises: b677b44ab9b4
Create Date: 2026-09-22 22:21:11.568136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0dc839bc1c52'
down_revision: Union[str, Sequence[str], None] = 'b677b44ab9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(
        "UPDATE users SET role = 'customer' WHERE role = 'user'"
    )

    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(),
        server_default="customer",
        existing_nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        "UPDATE users SET role = 'user' WHERE role = 'customer'"
    )

    op.alter_column(
        "users",
        "role",
        existing_type=sa.String(),
        server_default="user",
        existing_nullable=False,
    )
