"""add the GAM playlist changes an assistant turn proposed

Nullable: every existing turn proposed none.

Revision ID: 9d4b7e2a6c18
Revises: 3f8a6d2c9e41
Create Date: 2026-11-25 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '9d4b7e2a6c18'
down_revision: Union[str, None] = '3f8a6d2c9e41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.add_column(sa.Column('proposed_playlists', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.drop_column('proposed_playlists')
