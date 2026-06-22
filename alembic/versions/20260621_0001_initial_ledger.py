"""Initial immutable fact ledger schema.

Revision ID: 20260621_0001
Revises:
"""
from __future__ import annotations

from alembic import op

from novelloom.persistence.models import Base


revision = "20260621_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind(), checkfirst=True)
