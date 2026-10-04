"""index the three refresh token lookups

Revision ID: b7c41e2ad903
Revises: 3a91f7d20b45
Create Date: 2026-10-04

"""
from alembic import op


revision = "b7c41e2ad903"
down_revision = "3a91f7d20b45"
branch_labels = None
depends_on = None


def upgrade():
    # user_id: prune on login/refresh and revoke on password change.
    # family_id: revoke the whole family when a rotated token is reused.
    # expires_at: the prune itself.
    op.create_index(
        "ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"]
    )
    op.create_index(
        "ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"]
    )
    op.create_index(
        "ix_refresh_tokens_expires_at", "refresh_tokens", ["expires_at"]
    )


def downgrade():
    op.drop_index("ix_refresh_tokens_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
