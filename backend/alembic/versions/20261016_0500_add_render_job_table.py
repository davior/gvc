"""Add the render_job table: one render of one version of a project.

Revision ID: 1c0c7b02acd3
Revises: 389de295043a
Create Date: 2026-10-16 05:00:03.642906+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '1c0c7b02acd3'
down_revision: Union[str, None] = '389de295043a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('render_job',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('version_seq', sa.Integer(), nullable=False),
    sa.Column('preview', sa.Boolean(), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('stage', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('detail', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('warnings', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('video_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('subtitle_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('poster_path', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('duration', sa.Float(), nullable=True),
    sa.Column('size_bytes', sa.Integer(), nullable=True),
    sa.Column('narration_chars', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('render_job', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_render_job_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_render_job_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('render_job', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_render_job_user_id'))
        batch_op.drop_index(batch_op.f('ix_render_job_project_id'))

    op.drop_table('render_job')
