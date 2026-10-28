"""Add the theme table: named prompt modifiers a project's generations are styled by.

Revision ID: 3e7a9c51b2d4
Revises: 8a4c2e9f1d37
Create Date: 2026-10-28 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '3e7a9c51b2d4'
down_revision: Union[str, None] = '8a4c2e9f1d37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('theme',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('prompt', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('theme', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_theme_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('theme', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_theme_user_id'))
    op.drop_table('theme')
