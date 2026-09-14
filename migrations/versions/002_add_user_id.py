"""Add user_id to conversations and reminders

Revision ID: 002_add_user_id
Revises: 001_initial_schema
Create Date: 2026-08-24 22:50:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002_add_user_id'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add user_id column with server_default to ensure existing rows do not break NOT NULL in production
    op.add_column(
        'conversations',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()'))
    )
    op.create_index('idx_conversations_user_id', 'conversations', ['user_id'])

    op.add_column(
        'reminders',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text('gen_random_uuid()'))
    )
    op.create_index('idx_reminders_user_id', 'reminders', ['user_id'])


def downgrade() -> None:
    op.drop_index('idx_reminders_user_id', table_name='reminders')
    op.drop_column('reminders', 'user_id')
    op.drop_index('idx_conversations_user_id', table_name='conversations')
    op.drop_column('conversations', 'user_id')
