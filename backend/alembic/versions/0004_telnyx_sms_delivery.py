"""Add Telnyx delivery analytics fields and provider event idempotency.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.add_column("sms_campaigns", sa.Column("media_asset_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_sms_campaigns_media_asset_id_email_assets", "sms_campaigns", "email_assets", ["media_asset_id"], ["id"], ondelete="SET NULL")
    op.add_column("sms_recipients", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sms_recipients", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sms_recipients", sa.Column("error_code", sa.String(length=80), nullable=True))
    op.drop_constraint("ck_sms_recipients_status", "sms_recipients", type_="check")
    op.create_check_constraint("ck_sms_recipients_status", "sms_recipients", "status IN ('queued', 'sent', 'delivered', 'undelivered', 'failed', 'skipped')")
    op.create_table(
        "sms_provider_events",
        sa.Column("id", sa.String(length=255), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade() -> None:
    op.drop_table("sms_provider_events")
    op.drop_constraint("ck_sms_recipients_status", "sms_recipients", type_="check")
    op.create_check_constraint("ck_sms_recipients_status", "sms_recipients", "status IN ('queued', 'sent', 'failed', 'skipped')")
    op.drop_column("sms_recipients", "error_code")
    op.drop_column("sms_recipients", "failed_at")
    op.drop_column("sms_recipients", "delivered_at")
    op.drop_constraint("fk_sms_campaigns_media_asset_id_email_assets", "sms_campaigns", type_="foreignkey")
    op.drop_column("sms_campaigns", "media_asset_id")
