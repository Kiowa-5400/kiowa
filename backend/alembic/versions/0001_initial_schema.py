"""Initial PostgreSQL schema for the Kiowa Gun Club application.

Revision ID: 0001
Revises: 
Create Date: 2026-10-02 21:00:13.627500+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('job_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_name', sa.String(length=80), nullable=False),
    sa.Column('period_key', sa.String(length=40), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('result', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_runs')),
    sa.UniqueConstraint('job_name', 'period_key', name='uq_job_runs_job_period')
    )
    op.create_table('matches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('discipline', sa.String(length=120), nullable=False),
    sa.Column('event_date', sa.Date(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('results_url', sa.String(length=500), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_matches'))
    )
    op.create_index(op.f('ix_matches_discipline'), 'matches', ['discipline'], unique=False)
    op.create_index(op.f('ix_matches_event_date'), 'matches', ['event_date'], unique=False)
    op.create_table('people',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('first_name', sa.String(length=120), nullable=False),
    sa.Column('last_name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=40), nullable=True),
    sa.Column('address_line1', sa.String(length=255), nullable=True),
    sa.Column('address_line2', sa.String(length=255), nullable=True),
    sa.Column('city', sa.String(length=120), nullable=True),
    sa.Column('state', sa.String(length=40), nullable=True),
    sa.Column('zip_code', sa.String(length=20), nullable=True),
    sa.Column('membership_status', sa.String(length=30), server_default='non_member', nullable=False),
    sa.Column('on_board', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('on_shooting_committee', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('member_since', sa.Date(), nullable=True),
    sa.Column('renewal_date', sa.Date(), nullable=True),
    sa.Column('terminated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('nra_number', sa.String(length=20), nullable=True),
    sa.Column('nra_expiration_date', sa.Date(), nullable=True),
    sa.Column('nra_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('background_check_cleared', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('background_check_cleared_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sms_opt_in', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('sms_opt_in_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sms_opt_in_source', sa.String(length=60), nullable=True),
    sa.Column('sms_opt_out_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('email_opt_out', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('email_opt_out_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('unsubscribe_token', sa.String(length=64), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_login_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("membership_status IN ('member', 'waiting_list', 'non_member', 'expired', 'terminated')", name=op.f('ck_people_membership_status')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_people')),
    sa.UniqueConstraint('nra_number', name=op.f('uq_people_nra_number')),
    sa.UniqueConstraint('unsubscribe_token', name=op.f('uq_people_unsubscribe_token'))
    )
    op.create_index(op.f('ix_people_membership_status'), 'people', ['membership_status'], unique=False)
    op.create_index(op.f('ix_people_renewal_date'), 'people', ['renewal_date'], unique=False)
    op.create_index('uq_people_email_lower', 'people', [sa.literal_column('lower(email)')], unique=True)
    op.create_table('position_options',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_position_options')),
    sa.UniqueConstraint('label', name=op.f('uq_position_options_label'))
    )
    op.create_table('stripe_events',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_stripe_events'))
    )
    op.create_table('applications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('application_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('documentation_method', sa.String(length=30), nullable=True),
    sa.Column('claims_cleanup_discount', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('applicant_notes', sa.Text(), nullable=True),
    sa.Column('submitted_profile', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('rules_version', sa.String(length=40), nullable=True),
    sa.Column('rules_acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('printed_name', sa.String(length=200), nullable=True),
    sa.Column('signature_name', sa.String(length=200), nullable=True),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('signature_ip', sa.String(length=64), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('nra_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('discount_approved', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_reason', sa.Text(), nullable=True),
    sa.Column('info_request_message', sa.Text(), nullable=True),
    sa.Column('payment_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('payment_status', sa.String(length=20), server_default='unpaid', nullable=False),
    sa.Column('payment_eligible', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('payment_block_reason', sa.Text(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("application_type IN ('renewal', 'waiting_list')", name=op.f('ck_applications_application_type')),
    sa.CheckConstraint("documentation_method IS NULL OR documentation_method IN ('background_check', 'concealed_carry')", name=op.f('ck_applications_documentation_method')),
    sa.CheckConstraint("payment_status IN ('unpaid', 'pending', 'paid', 'refunded')", name=op.f('ck_applications_payment_status')),
    sa.CheckConstraint("status IN ('draft', 'submitted', 'needs_info', 'approved', 'declined', 'completed', 'withdrawn')", name=op.f('ck_applications_status')),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_applications_person_id_people'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['people.id'], name=op.f('fk_applications_reviewed_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_applications'))
    )
    op.create_index(op.f('ix_applications_person_id'), 'applications', ['person_id'], unique=False)
    op.create_index('ix_applications_status_type', 'applications', ['status', 'application_type'], unique=False)
    op.create_index('uq_applications_one_open', 'applications', ['person_id'], unique=True,
                    postgresql_where=sa.text("status IN ('draft', 'submitted', 'needs_info', 'approved')"))
    op.create_table('audit_logs',
    sa.Column('id', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_label', sa.String(length=255), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('entity_type', sa.String(length=60), nullable=True),
    sa.Column('entity_id', sa.String(length=60), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['actor_id'], ['people.id'], name=op.f('fk_audit_logs_actor_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_id'), 'audit_logs', ['actor_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)
    op.create_table('auth_tokens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.String(length=30), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("purpose IN ('password_reset', 'email_verification', 'board_invite')", name=op.f('ck_auth_tokens_purpose')),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_auth_tokens_person_id_people'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_auth_tokens_token_hash'))
    )
    op.create_index(op.f('ix_auth_tokens_person_id'), 'auth_tokens', ['person_id'], unique=False)
    op.create_table('board_users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('position', sa.String(length=120), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('invited_by_id', sa.Integer(), nullable=True),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('tech_admin', 'president', 'vice_president', 'treasurer', 'board_member')", name=op.f('ck_board_users_role')),
    sa.ForeignKeyConstraint(['invited_by_id'], ['people.id'], name=op.f('fk_board_users_invited_by_id_people'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_board_users_person_id_people'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_board_users')),
    sa.UniqueConstraint('person_id', name=op.f('uq_board_users_person_id'))
    )
    op.create_table('calendar_series',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('nth', sa.Integer(), nullable=False),
    sa.Column('weekday', sa.Integer(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.CheckConstraint('nth BETWEEN 1 AND 5', name=op.f('ck_calendar_series_nth')),
    sa.CheckConstraint('weekday BETWEEN 0 AND 6', name=op.f('ck_calendar_series_weekday')),
    sa.ForeignKeyConstraint(['created_by_id'], ['people.id'], name=op.f('fk_calendar_series_created_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calendar_series'))
    )
    op.create_table('email_assets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('public_token', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('image', 'attachment')", name=op.f('ck_email_assets_kind')),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['people.id'], name=op.f('fk_email_assets_uploaded_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_assets')),
    sa.UniqueConstraint('public_token', name=op.f('uq_email_assets_public_token')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_email_assets_storage_key'))
    )
    op.create_table('email_campaigns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), server_default='manual', nullable=False),
    sa.Column('subject', sa.String(length=255), nullable=False),
    sa.Column('body_html', sa.Text(), nullable=False),
    sa.Column('recipient_summary', sa.Text(), nullable=True),
    sa.Column('attachment_names', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('failed_count', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint("kind IN ('manual', 'renewal_reminder', 'system')", name=op.f('ck_email_campaigns_kind')),
    sa.ForeignKeyConstraint(['created_by_id'], ['people.id'], name=op.f('fk_email_campaigns_created_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_campaigns'))
    )
    op.create_table('match_photos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('match_id', sa.Integer(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('caption', sa.String(length=255), nullable=True),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['match_id'], ['matches.id'], name=op.f('fk_match_photos_match_id_matches'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_match_photos')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_match_photos_storage_key'))
    )
    op.create_index(op.f('ix_match_photos_match_id'), 'match_photos', ['match_id'], unique=False)
    op.create_table('page_sections',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('page_slug', sa.String(length=60), nullable=False),
    sa.Column('section_key', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=120), nullable=True),
    sa.Column('heading', sa.String(length=255), nullable=True),
    sa.Column('body_html', sa.Text(), server_default='', nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('is_custom', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_visible', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['updated_by_id'], ['people.id'], name=op.f('fk_page_sections_updated_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_page_sections')),
    sa.UniqueConstraint('page_slug', 'section_key', name='uq_page_sections_slug_key')
    )
    op.create_index(op.f('ix_page_sections_page_slug'), 'page_sections', ['page_slug'], unique=False)
    op.create_table('public_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=60), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('is_published', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['people.id'], name=op.f('fk_public_documents_uploaded_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_public_documents')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_public_documents_storage_key'))
    )
    op.create_table('renewal_reminders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('cycle_date', sa.Date(), nullable=False),
    sa.Column('threshold_days', sa.Integer(), nullable=False),
    sa.Column('channel', sa.String(length=10), nullable=False),
    sa.Column('succeeded', sa.Boolean(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("channel IN ('email', 'sms')", name=op.f('ck_renewal_reminders_channel')),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_renewal_reminders_person_id_people'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_renewal_reminders')),
    sa.UniqueConstraint('person_id', 'cycle_date', 'threshold_days', 'channel', name='uq_renewal_reminders_once')
    )
    op.create_index(op.f('ix_renewal_reminders_person_id'), 'renewal_reminders', ['person_id'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('realm', sa.String(length=10), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.CheckConstraint("realm IN ('member', 'board')", name=op.f('ck_sessions_realm')),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_sessions_person_id_people'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessions_person_id'), 'sessions', ['person_id'], unique=False)
    op.create_table('site_images',
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('alt_text', sa.String(length=255), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("key IN ('logo', 'hero', 'about', 'rules', 'matches_flyer')", name=op.f('ck_site_images_key')),
    sa.ForeignKeyConstraint(['updated_by_id'], ['people.id'], name=op.f('fk_site_images_updated_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_site_images'))
    )
    op.create_table('site_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('site_title', sa.String(length=120), nullable=False),
    sa.Column('site_subtitle', sa.String(length=200), nullable=False),
    sa.Column('contact_email', sa.String(length=255), nullable=True),
    sa.Column('contact_phone', sa.String(length=40), nullable=True),
    sa.Column('mailing_address', sa.Text(), nullable=True),
    sa.Column('physical_address', sa.Text(), nullable=True),
    sa.Column('map_url', sa.String(length=500), nullable=True),
    sa.Column('social_facebook', sa.String(length=500), nullable=True),
    sa.Column('social_instagram', sa.String(length=500), nullable=True),
    sa.Column('social_youtube', sa.String(length=500), nullable=True),
    sa.Column('footer_links', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('dues_amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('cleanup_discount_amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('renewal_cutoff_month', sa.Integer(), nullable=False),
    sa.Column('renewal_cutoff_day', sa.Integer(), nullable=False),
    sa.Column('accepting_waiting_list', sa.Boolean(), nullable=False),
    sa.Column('background_check_url', sa.String(length=500), nullable=True),
    sa.Column('rules_version', sa.String(length=40), nullable=False),
    sa.Column('range_rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('rules_agreement_clause', sa.Text(), nullable=False),
    sa.Column('rules_reporting_clause', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by_id', sa.Integer(), nullable=True),
    sa.CheckConstraint('cleanup_discount_amount >= 0', name=op.f('ck_site_settings_discount_non_negative')),
    sa.CheckConstraint('dues_amount > 0', name=op.f('ck_site_settings_dues_positive')),
    sa.CheckConstraint('id = 1', name=op.f('ck_site_settings_singleton')),
    sa.CheckConstraint('renewal_cutoff_day BETWEEN 1 AND 31', name=op.f('ck_site_settings_cutoff_day')),
    sa.CheckConstraint('renewal_cutoff_month BETWEEN 1 AND 12', name=op.f('ck_site_settings_cutoff_month')),
    sa.ForeignKeyConstraint(['updated_by_id'], ['people.id'], name=op.f('fk_site_settings_updated_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site_settings'))
    )
    op.create_table('application_notes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_application_notes_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['author_id'], ['people.id'], name=op.f('fk_application_notes_author_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_application_notes'))
    )
    op.create_index(op.f('ix_application_notes_application_id'), 'application_notes', ['application_id'], unique=False)
    op.create_table('calendar_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('all_day', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('category', sa.String(length=20), server_default='event', nullable=False),
    sa.Column('description_html', sa.Text(), nullable=True),
    sa.Column('link_url', sa.String(length=500), nullable=True),
    sa.Column('link_label', sa.String(length=120), nullable=True),
    sa.Column('image_key', sa.String(length=500), nullable=True),
    sa.Column('image_filename', sa.String(length=255), nullable=True),
    sa.Column('image_mime', sa.String(length=100), nullable=True),
    sa.Column('document_key', sa.String(length=500), nullable=True),
    sa.Column('document_filename', sa.String(length=255), nullable=True),
    sa.Column('series_id', sa.Uuid(), nullable=True),
    sa.Column('recurrence_label', sa.String(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("category IN ('match', 'member', 'meeting', 'event', 'closure')", name=op.f('ck_calendar_events_category')),
    sa.CheckConstraint('ends_at IS NULL OR ends_at >= starts_at', name=op.f('ck_calendar_events_ends_after_start')),
    sa.ForeignKeyConstraint(['series_id'], ['calendar_series.id'], name=op.f('fk_calendar_events_series_id_calendar_series'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_calendar_events'))
    )
    op.create_index(op.f('ix_calendar_events_series_id'), 'calendar_events', ['series_id'], unique=False)
    op.create_index(op.f('ix_calendar_events_starts_at'), 'calendar_events', ['starts_at'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('document_type', sa.String(length=30), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('review_status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_notes', sa.Text(), nullable=True),
    sa.Column('purged_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("document_type IN ('nra_proof', 'background_check', 'concealed_carry', 'cleanup_discount', 'other')", name=op.f('ck_documents_document_type')),
    sa.CheckConstraint("review_status IN ('pending', 'approved', 'rejected')", name=op.f('ck_documents_review_status')),
    sa.CheckConstraint('size_bytes > 0', name=op.f('ck_documents_size_positive')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_documents_application_id_applications'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_documents_person_id_people'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['reviewed_by_id'], ['people.id'], name=op.f('fk_documents_reviewed_by_id_people'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['people.id'], name=op.f('fk_documents_uploaded_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documents')),
    sa.UniqueConstraint('storage_key', name=op.f('uq_documents_storage_key'))
    )
    op.create_index(op.f('ix_documents_application_id'), 'documents', ['application_id'], unique=False)
    op.create_index(op.f('ix_documents_person_id'), 'documents', ['person_id'], unique=False)
    op.create_index('ix_documents_review_status', 'documents', ['review_status'], unique=False)
    op.create_table('email_recipients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('provider_message_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('clicked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('bounced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('bounce_type', sa.String(length=100), nullable=True),
    sa.Column('complained_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'sent', 'failed', 'delivered', 'bounced', 'complained')", name=op.f('ck_email_recipients_status')),
    sa.ForeignKeyConstraint(['campaign_id'], ['email_campaigns.id'], name=op.f('fk_email_recipients_campaign_id_email_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_email_recipients_person_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_email_recipients'))
    )
    op.create_index(op.f('ix_email_recipients_campaign_id'), 'email_recipients', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_email_recipients_person_id'), 'email_recipients', ['person_id'], unique=False)
    op.create_index(op.f('ix_email_recipients_provider_message_id'), 'email_recipients', ['provider_message_id'], unique=False)
    op.create_table('payments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=False),
    sa.Column('application_id', sa.Integer(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), server_default='usd', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('method', sa.String(length=10), server_default='card', nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('stripe_checkout_session_id', sa.String(length=255), nullable=True),
    sa.Column('stripe_payment_intent_id', sa.String(length=255), nullable=True),
    sa.Column('refunded_amount', sa.Numeric(precision=10, scale=2), server_default='0', nullable=False),
    sa.Column('covers_through', sa.Date(), nullable=True),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('recorded_by_id', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("method IN ('card', 'cash', 'check', 'other')", name=op.f('ck_payments_method')),
    sa.CheckConstraint("status IN ('pending', 'paid', 'failed', 'cancelled', 'refunded', 'partially_refunded')", name=op.f('ck_payments_status')),
    sa.CheckConstraint('amount >= 0', name=op.f('ck_payments_amount_non_negative')),
    sa.CheckConstraint('refunded_amount >= 0', name=op.f('ck_payments_refunded_non_negative')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_payments_application_id_applications'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_payments_person_id_people'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['recorded_by_id'], ['people.id'], name=op.f('fk_payments_recorded_by_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments')),
    sa.UniqueConstraint('stripe_checkout_session_id', name=op.f('uq_payments_stripe_checkout_session_id'))
    )
    op.create_index(op.f('ix_payments_application_id'), 'payments', ['application_id'], unique=False)
    op.create_index(op.f('ix_payments_person_id'), 'payments', ['person_id'], unique=False)
    op.create_index('ix_payments_status_paid_at', 'payments', ['status', 'paid_at'], unique=False)
    op.create_index(op.f('ix_payments_stripe_payment_intent_id'), 'payments', ['stripe_payment_intent_id'], unique=False)
    op.create_table('sms_campaigns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), server_default='manual', nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('media_asset_id', sa.Integer(), nullable=True),
    sa.Column('recipient_summary', sa.Text(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('sent_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('failed_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('skipped_count', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint("kind IN ('manual', 'renewal_reminder', 'system')", name=op.f('ck_sms_campaigns_kind')),
    sa.ForeignKeyConstraint(['created_by_id'], ['people.id'], name=op.f('fk_sms_campaigns_created_by_id_people'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['media_asset_id'], ['email_assets.id'], name=op.f('fk_sms_campaigns_media_asset_id_email_assets'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sms_campaigns'))
    )
    op.create_table('sms_recipients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('campaign_id', sa.Integer(), nullable=False),
    sa.Column('person_id', sa.Integer(), nullable=True),
    sa.Column('phone', sa.String(length=40), nullable=False),
    sa.Column('provider_message_id', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
    sa.Column('error_code', sa.String(length=40), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'sent', 'delivered', 'failed', 'undelivered', 'skipped')", name=op.f('ck_sms_recipients_status')),
    sa.ForeignKeyConstraint(['campaign_id'], ['sms_campaigns.id'], name=op.f('fk_sms_recipients_campaign_id_sms_campaigns'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], name=op.f('fk_sms_recipients_person_id_people'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sms_recipients'))
    )
    op.create_index(op.f('ix_sms_recipients_campaign_id'), 'sms_recipients', ['campaign_id'], unique=False)
    op.create_index(op.f('ix_sms_recipients_person_id'), 'sms_recipients', ['person_id'], unique=False)
    op.create_index(op.f('ix_sms_recipients_provider_message_id'), 'sms_recipients', ['provider_message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_sms_recipients_provider_message_id'), table_name='sms_recipients')
    op.drop_index(op.f('ix_sms_recipients_person_id'), table_name='sms_recipients')
    op.drop_index(op.f('ix_sms_recipients_campaign_id'), table_name='sms_recipients')
    op.drop_table('sms_recipients')
    op.drop_table('sms_campaigns')
    op.drop_index(op.f('ix_payments_stripe_payment_intent_id'), table_name='payments')
    op.drop_index('ix_payments_status_paid_at', table_name='payments')
    op.drop_index(op.f('ix_payments_person_id'), table_name='payments')
    op.drop_index(op.f('ix_payments_application_id'), table_name='payments')
    op.drop_table('payments')
    op.drop_index(op.f('ix_email_recipients_provider_message_id'), table_name='email_recipients')
    op.drop_index(op.f('ix_email_recipients_person_id'), table_name='email_recipients')
    op.drop_index(op.f('ix_email_recipients_campaign_id'), table_name='email_recipients')
    op.drop_table('email_recipients')
    op.drop_index('ix_documents_review_status', table_name='documents')
    op.drop_index(op.f('ix_documents_person_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_application_id'), table_name='documents')
    op.drop_table('documents')
    op.drop_index(op.f('ix_calendar_events_starts_at'), table_name='calendar_events')
    op.drop_index(op.f('ix_calendar_events_series_id'), table_name='calendar_events')
    op.drop_table('calendar_events')
    op.drop_index(op.f('ix_application_notes_application_id'), table_name='application_notes')
    op.drop_table('application_notes')
    op.drop_table('site_settings')
    op.drop_table('site_images')
    op.drop_index(op.f('ix_sessions_person_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_renewal_reminders_person_id'), table_name='renewal_reminders')
    op.drop_table('renewal_reminders')
    op.drop_table('public_documents')
    op.drop_index(op.f('ix_page_sections_page_slug'), table_name='page_sections')
    op.drop_table('page_sections')
    op.drop_index(op.f('ix_match_photos_match_id'), table_name='match_photos')
    op.drop_table('match_photos')
    op.drop_table('email_campaigns')
    op.drop_table('email_assets')
    op.drop_table('calendar_series')
    op.drop_table('board_users')
    op.drop_index(op.f('ix_auth_tokens_person_id'), table_name='auth_tokens')
    op.drop_table('auth_tokens')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index('uq_applications_one_open', table_name='applications')
    op.drop_index('ix_applications_status_type', table_name='applications')
    op.drop_index(op.f('ix_applications_person_id'), table_name='applications')
    op.drop_table('applications')
    op.drop_table('stripe_events')
    op.drop_table('position_options')
    op.drop_index('uq_people_email_lower', table_name='people')
    op.drop_index(op.f('ix_people_renewal_date'), table_name='people')
    op.drop_index(op.f('ix_people_membership_status'), table_name='people')
    op.drop_table('people')
    op.drop_index(op.f('ix_matches_event_date'), table_name='matches')
    op.drop_index(op.f('ix_matches_discipline'), table_name='matches')
    op.drop_table('matches')
    op.drop_table('job_runs')
