"""Texts go through carrier email-to-SMS gateways (Veriphone lookup) instead of Twilio.

Adds the cached carrier and gateway address, records email fallbacks for failed
texts, and removes the picture-message and delivery-receipt columns, which
gateways don't support.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02 22:31:12.214665+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('people', sa.Column('sms_carrier', sa.String(length=120), nullable=True))
    op.add_column('sms_campaigns', sa.Column('fallback_email_count', sa.Integer(), server_default='0', nullable=False))
    op.drop_constraint(op.f('fk_sms_campaigns_media_asset_id_email_assets'), 'sms_campaigns', type_='foreignkey')
    op.drop_column('sms_campaigns', 'media_asset_id')
    op.add_column('sms_recipients', sa.Column('gateway_address', sa.String(length=255), nullable=True))
    op.add_column('sms_recipients', sa.Column('fallback_email_sent', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.drop_column('sms_recipients', 'error_code')
    op.drop_column('sms_recipients', 'delivered_at')
    op.drop_column('sms_recipients', 'failed_at')
    op.execute("UPDATE sms_recipients SET status = 'sent' WHERE status = 'delivered'")
    op.execute("UPDATE sms_recipients SET status = 'failed' WHERE status = 'undelivered'")
    op.drop_constraint(op.f('ck_sms_recipients_status'), 'sms_recipients', type_='check')
    op.create_check_constraint(op.f('ck_sms_recipients_status'), 'sms_recipients', "status IN ('queued', 'sent', 'failed', 'skipped')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_sms_recipients_status'), 'sms_recipients', type_='check')
    op.create_check_constraint(op.f('ck_sms_recipients_status'), 'sms_recipients',
                               "status IN ('queued', 'sent', 'delivered', 'failed', 'undelivered', 'skipped')")
    op.add_column('sms_recipients', sa.Column('failed_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('sms_recipients', sa.Column('delivered_at', postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True))
    op.add_column('sms_recipients', sa.Column('error_code', sa.VARCHAR(length=40), autoincrement=False, nullable=True))
    op.drop_column('sms_recipients', 'fallback_email_sent')
    op.drop_column('sms_recipients', 'gateway_address')
    op.add_column('sms_campaigns', sa.Column('media_asset_id', sa.INTEGER(), autoincrement=False, nullable=True))
    op.create_foreign_key(op.f('fk_sms_campaigns_media_asset_id_email_assets'), 'sms_campaigns', 'email_assets', ['media_asset_id'], ['id'], ondelete='SET NULL')
    op.drop_column('sms_campaigns', 'fallback_email_count')
    op.drop_column('people', 'sms_carrier')
