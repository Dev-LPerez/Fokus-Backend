"""Tasks expanded and user integrations table

Revision ID: 003_tasks_and_integrations
Revises: 002_add_user_id
Create Date: 2026-08-29 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_tasks_and_integrations'
down_revision = '002_add_user_id'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add completed and google_event_id to reminders
    op.add_column(
        'reminders',
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )
    op.add_column(
        'reminders',
        sa.Column('google_event_id', sa.Text(), nullable=True)
    )

    # 2. Create user_integrations table
    op.create_table(
        'user_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.Text(), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=False),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=False),
        sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', 'provider', name='uq_user_integrations_user_provider')
    )
    op.create_index('idx_user_integrations_user_id', 'user_integrations', ['user_id'])


def downgrade() -> None:
    op.drop_index('idx_user_integrations_user_id', table_name='user_integrations')
    op.drop_table('user_integrations')
    op.drop_column('reminders', 'google_event_id')
    op.drop_column('reminders', 'completed')
