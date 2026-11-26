"""add auto_run to assistant turns

Every existing turn was asked without it, hence the server default.

Revision ID: 5b2e8c4f1a37
Revises: 9d4b7e2a6c18
Create Date: 2026-11-26 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '5b2e8c4f1a37'
down_revision: Union[str, None] = '9d4b7e2a6c18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_run', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.drop_column('auto_run')
