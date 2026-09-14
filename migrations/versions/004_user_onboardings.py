"""add user_onboardings table

Revision ID: 004_user_onboardings
Revises: 2f7d7d47598c
Create Date: 2026-09-04 22:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '004_user_onboardings'
down_revision: Union[str, None] = '2f7d7d47598c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_onboardings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('has_seen', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.UniqueConstraint('user_id', name='uq_user_onboardings_user_id')
    )
    op.create_index('ix_user_onboardings_user_id', 'user_onboardings', ['user_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_user_onboardings_user_id', table_name='user_onboardings')
    op.drop_table('user_onboardings')
