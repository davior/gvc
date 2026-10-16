"""Add the aiprovider and usageevent tables (M4/M5, the assistant's first half).

Both are copied from GAM's, which came from gecko-notes. `usageevent.project_id` and
`turn_id` are plain indexed columns, not foreign keys: deleting a project must not
delete the record of what was spent on it.

Revision ID: 4a8c2f6e9d13
Revises: 7e2d5a91b3c6
Create Date: 2026-10-16 10:16:48.213291+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '4a8c2f6e9d13'
down_revision: Union[str, None] = '7e2d5a91b3c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('aiprovider',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('provider_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('api_key', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('base_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('model', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('max_tokens', sa.Integer(), nullable=False),
    sa.Column('supports_images', sa.Boolean(), nullable=False),
    sa.Column('use_anthropic_api', sa.Boolean(), nullable=False),
    sa.Column('extra_params', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('aiprovider', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_aiprovider_user_id'), ['user_id'], unique=False)

    op.create_table('usageevent',
    sa.Column('id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('project_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('kind', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('model', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('units', sa.Integer(), nullable=False),
    sa.Column('unit_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=True),
    sa.Column('currency', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('cost_estimated', sa.Boolean(), nullable=True),
    sa.Column('turn_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('usageevent', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_usageevent_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_usageevent_kind'), ['kind'], unique=False)
        batch_op.create_index(batch_op.f('ix_usageevent_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_usageevent_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_usageevent_turn_id'), ['turn_id'], unique=False)
        batch_op.create_index('ix_usageevent_user_created', ['user_id', 'created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_usageevent_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('usageevent', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_usageevent_user_id'))
        batch_op.drop_index('ix_usageevent_user_created')
        batch_op.drop_index(batch_op.f('ix_usageevent_turn_id'))
        batch_op.drop_index(batch_op.f('ix_usageevent_provider'))
        batch_op.drop_index(batch_op.f('ix_usageevent_project_id'))
        batch_op.drop_index(batch_op.f('ix_usageevent_kind'))
        batch_op.drop_index(batch_op.f('ix_usageevent_created_at'))

    op.drop_table('usageevent')
    with op.batch_alter_table('aiprovider', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_aiprovider_user_id'))

    op.drop_table('aiprovider')
