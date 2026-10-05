"""add optional vehicle photo

Revision ID: 82cc43f13785
Revises: b7c41e2ad903
Create Date: 2026-10-04

"""
from alembic import op
import sqlalchemy as sa


revision = "82cc43f13785"
down_revision = "b7c41e2ad903"
branch_labels = None
depends_on = None


def upgrade():
    # Generated name inside uploads_dir. NULL = no photo uploaded yet, the
    # photo being optional. The bytes themselves live on disk, not here.
    op.add_column(
        "vehicles",
        sa.Column("photo_file", sa.String(), nullable=True),
    )


def downgrade():
    op.drop_column("vehicles", "photo_file")
