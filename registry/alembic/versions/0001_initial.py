"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "albums",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("album_name", sa.String(), nullable=True),
        sa.Column("owner_first", sa.String(), nullable=True),
        sa.Column("owner_last", sa.String(), nullable=True),
        sa.Column("photo_count", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_checked", sa.DateTime(timezone=True), nullable=True),
        sa.Column("frame_id", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_albums_token", "albums", ["token"], unique=True)
    op.create_index("ix_albums_frame_id", "albums", ["frame_id"])


def downgrade() -> None:
    op.drop_index("ix_albums_frame_id", table_name="albums")
    op.drop_index("ix_albums_token", table_name="albums")
    op.drop_table("albums")
