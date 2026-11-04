"""add the persona an assistant turn was asked as

A turn may be asked as one of Gecko Suite's personas. Nullable: every existing turn was
asked as none.

Revision ID: b6d29f0c4e17
Revises: 3e7a9c51b2d4
Create Date: 2026-11-04 10:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'b6d29f0c4e17'
down_revision: Union[str, None] = '3e7a9c51b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.add_column(sa.Column('persona_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.drop_column('persona_id')
