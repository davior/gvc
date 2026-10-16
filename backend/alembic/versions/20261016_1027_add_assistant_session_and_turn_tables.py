"""Add the assistant_session and assistant_turn tables (M4/M5).

A turn is a job, so it carries the job fields the runner reads (status, stage,
progress, detail, error_message, updated_at) next to everything the turn is: its
prompt, the draft it started from, its steps, its reply and its proposal.

Revision ID: 9b3e7d215f60
Revises: 4a8c2f6e9d13
Create Date: 2026-10-16 10:27:22.137896+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '9b3e7d215f60'
down_revision: Union[str, None] = '4a8c2f6e9d13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('assistant_session',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('messages', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assistant_session', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assistant_session_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assistant_session_user_id'), ['user_id'], unique=False)

    op.create_table('assistant_turn',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('session_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('stage', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('detail', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('prompt', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('base_spec', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('base_version', sa.Integer(), nullable=True),
    sa.Column('focus', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('steps', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('reply', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('proposed_spec', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('changes', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('outcome', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['assistant_session.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_assistant_turn_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assistant_turn_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_assistant_turn_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('assistant_turn', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assistant_turn_user_id'))
        batch_op.drop_index(batch_op.f('ix_assistant_turn_session_id'))
        batch_op.drop_index(batch_op.f('ix_assistant_turn_project_id'))

    op.drop_table('assistant_turn')
    with op.batch_alter_table('assistant_session', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_assistant_session_user_id'))
        batch_op.drop_index(batch_op.f('ix_assistant_session_project_id'))

    op.drop_table('assistant_session')
