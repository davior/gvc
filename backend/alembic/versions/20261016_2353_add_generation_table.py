"""Add the generation table: GVC's record of each generation it asked GAM for.

The job runs in GAM; a row is how GVC follows it and knows which placeholder it fills.
`gam_job_id` is GAM's id, so no foreign key.

Revision ID: c6d1a4e8b207
Revises: 9b3e7d215f60
Create Date: 2026-10-16 23:53:58.001597+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = 'c6d1a4e8b207'
down_revision: Union[str, None] = '9b3e7d215f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('generation',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('turn_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('asset_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('gam_job_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('prompt', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('model_label', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('params', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('stage', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('detail', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('result_ids', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('used_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('estimate', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('generation', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_generation_gam_job_id'), ['gam_job_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_generation_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_generation_turn_id'), ['turn_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_generation_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('generation', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_generation_user_id'))
        batch_op.drop_index(batch_op.f('ix_generation_turn_id'))
        batch_op.drop_index(batch_op.f('ix_generation_project_id'))
        batch_op.drop_index(batch_op.f('ix_generation_gam_job_id'))

    op.drop_table('generation')
