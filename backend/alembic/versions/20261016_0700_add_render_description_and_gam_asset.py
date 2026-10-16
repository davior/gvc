"""Add render_job.description and render_job.gam_asset_id (M2b).

`description`: the chapters and credits a render worked out, to paste where the video
is published. `gam_asset_id`: the GAM asset a render was saved as, so saving twice
files it once. An id in another app's database, so no foreign key.

Revision ID: 7e2d5a91b3c6
Revises: 1c0c7b02acd3
Create Date: 2026-10-16 07:00:00.000000+00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


revision: str = '7e2d5a91b3c6'
down_revision: Union[str, None] = '1c0c7b02acd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('render_job', schema=None) as batch_op:
        batch_op.add_column(sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column('gam_asset_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('render_job', schema=None) as batch_op:
        batch_op.drop_column('gam_asset_id')
        batch_op.drop_column('description')
