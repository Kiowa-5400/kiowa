"""Add the roster member number and an NRA life member flag to people.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("people", sa.Column("member_number", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_people_member_number"), "people", ["member_number"])
    op.add_column("people", sa.Column("nra_life_member", sa.Boolean(), server_default=sa.text("false"), nullable=False))

def downgrade() -> None:
    op.drop_column("people", "nra_life_member")
    op.drop_index(op.f("ix_people_member_number"), table_name="people")
    op.drop_column("people", "member_number")
