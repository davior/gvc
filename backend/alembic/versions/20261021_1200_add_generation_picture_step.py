"""A clip made from a picture generated for it: the picture, and the clip run waiting.

`then` holds the clip's run (model, prompt, params) while the picture is being made,
and is cleared once the clip has been started from it. `picture_id` is the GAM asset
the picture became, kept so a failed clip can be tried again from it.

Revision ID: 5f1b8c3d2a90
Revises: c6d1a4e8b207
Create Date: 2026-10-21 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '5f1b8c3d2a90'
down_revision: Union[str, None] = 'c6d1a4e8b207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('generation', schema=None) as batch_op:
        batch_op.add_column(sa.Column('then', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('picture_id', sqlmodel.sql.sqltypes.AutoString(),
                                      nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('generation', schema=None) as batch_op:
        batch_op.drop_column('picture_id')
        batch_op.drop_column('then')
