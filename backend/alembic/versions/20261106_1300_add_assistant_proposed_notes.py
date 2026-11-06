"""add the notes an assistant turn proposed for Gecko Notes

Nullable: every existing turn proposed none.

Revision ID: 7c3e1f9a5b24
Revises: b6d29f0c4e17
Create Date: 2026-11-06 13:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '7c3e1f9a5b24'
down_revision: Union[str, None] = 'b6d29f0c4e17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proposed_notes', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.drop_column('proposed_notes')
