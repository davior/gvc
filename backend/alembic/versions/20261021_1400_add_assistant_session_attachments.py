"""Material attached to an assistant conversation: files, notes and web pages, as text.

A server default so the conversations that already exist read as having none.

Revision ID: 8a4c2e9f1d37
Revises: 5f1b8c3d2a90
Create Date: 2026-10-21 14:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '8a4c2e9f1d37'
down_revision: Union[str, None] = '5f1b8c3d2a90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assistant_session', schema=None) as batch_op:
        batch_op.add_column(sa.Column('attachments', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=False, server_default='[]'))


def downgrade() -> None:
    with op.batch_alter_table('assistant_session', schema=None) as batch_op:
        batch_op.drop_column('attachments')
