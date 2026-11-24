"""add recipes, and the recipe a turn ran and the recipes it proposed

Additive: a new table, and two nullable columns on assistant_turn that every existing
turn leaves empty (it ran no recipe and proposed none).

Revision ID: 3f8a6d2c9e41
Revises: 7c3e1f9a5b24
Create Date: 2026-11-24 12:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '3f8a6d2c9e41'
down_revision: Union[str, None] = '7c3e1f9a5b24'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recipe',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('prompt', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('tags', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('defaults', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('recipe', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_recipe_user_id'), ['user_id'], unique=False)
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipe_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('proposed_recipes', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.drop_column('proposed_recipes')
        batch_op.drop_column('recipe_id')
    with op.batch_alter_table('recipe', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_recipe_user_id'))
    op.drop_table('recipe')
