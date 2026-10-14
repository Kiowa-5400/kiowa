"""Remember pairs of records the board says are different people.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "not_duplicates",
        sa.Column("person_a_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("person_b_id", sa.Integer(), sa.ForeignKey("people.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("not_duplicates")
