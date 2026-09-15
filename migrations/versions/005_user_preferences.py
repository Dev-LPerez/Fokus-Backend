"""add user_preferences table

Revision ID: 005_user_preferences
Revises: 004_user_onboardings
Create Date: 2026-09-14 23:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '005_user_preferences'
down_revision: Union[str, None] = '004_user_onboardings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_preferences',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('city', sa.String(length=100), nullable=True),
        sa.Column('workday_start_hour', sa.Integer(), nullable=False, server_default=sa.text('8')),
        sa.Column('workday_end_hour', sa.Integer(), nullable=False, server_default=sa.text('19')),
        sa.Column('buffer_minutes', sa.Integer(), nullable=False, server_default=sa.text('10')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', name='uq_user_preferences_user_id')
    )
    op.create_index('ix_user_preferences_user_id', 'user_preferences', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_preferences_user_id', table_name='user_preferences')
    op.drop_table('user_preferences')
