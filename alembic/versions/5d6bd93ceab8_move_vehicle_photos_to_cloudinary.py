"""move vehicle photos to cloudinary

Revision ID: 5d6bd93ceab8
Revises: 82cc43f13785
Create Date: 2026-10-04

"""
from alembic import op
import sqlalchemy as sa


revision = "5d6bd93ceab8"
down_revision = "82cc43f13785"
branch_labels = None
depends_on = None


def upgrade():
    # Photos live on Cloudinary now: public_id is the handle a delete
    # points at, url is what serving goes through. photo_file held a
    # local disk name and goes away - Render free wipes its filesystem
    # on every restart, so nothing may depend on the container's disk.
    op.add_column(
        "vehicles",
        sa.Column("photo_public_id", sa.String(), nullable=True),
    )
    op.add_column(
        "vehicles",
        sa.Column("photo_url", sa.String(), nullable=True),
    )
    op.drop_column("vehicles", "photo_file")


def downgrade():
    # The old column comes back empty: the disk names it held are gone
    # with the volume this migration retires.
    op.add_column(
        "vehicles",
        sa.Column("photo_file", sa.String(), nullable=True),
    )
    op.drop_column("vehicles", "photo_url")
    op.drop_column("vehicles", "photo_public_id")
