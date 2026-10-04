"""cascade refresh tokens to their user

Revision ID: 3a91f7d20b45
Revises: 214fb3b098ed
Create Date: 2026-10-04

"""
from alembic import op
import sqlalchemy as sa


revision = "3a91f7d20b45"
down_revision = "214fb3b098ed"
branch_labels = None
depends_on = None


def upgrade():
    # Deleting a user has to take their sessions with them. With the plain
    # foreign key, any user who ever logged in could not be deleted: the
    # ORM nulled user_id and hit 23502 (reported as 422), and letting the
    # database answer would have raised 23503 forever.
    op.drop_constraint(
        "refresh_tokens_user_id_fkey",
        "refresh_tokens",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "refresh_tokens_user_id_fkey",
        "refresh_tokens",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint(
        "refresh_tokens_user_id_fkey",
        "refresh_tokens",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "refresh_tokens_user_id_fkey",
        "refresh_tokens",
        "users",
        ["user_id"],
        ["id"],
    )
