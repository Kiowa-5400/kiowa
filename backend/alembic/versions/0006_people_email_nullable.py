"""Let a person be on file without an email (roster members added by spreadsheet).

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.alter_column("people", "email", existing_type=sa.String(length=255), nullable=True)

def downgrade() -> None:
    # Fails while anyone is on file without an email; give them one first.
    op.alter_column("people", "email", existing_type=sa.String(length=255), nullable=False)
