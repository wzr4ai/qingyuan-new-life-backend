"""Add resource-service association table

Revision ID: 0d9f2a7c520b
Revises: e6b7c91a4a74
Create Date: 2025-11-03 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d9f2a7c520b'
down_revision: Union[str, Sequence[str], None] = 'e6b7c91a4a74'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create resource-service link table."""
    op.create_table(
        'resource_service_link',
        sa.Column('resource_id', sa.String(length=26), nullable=False),
        sa.Column('service_id', sa.String(length=26), nullable=False),
        sa.ForeignKeyConstraint(['resource_id'], ['resources.uid'], ),
        sa.ForeignKeyConstraint(['service_id'], ['services.uid'], ),
        sa.PrimaryKeyConstraint('resource_id', 'service_id')
    )


def downgrade() -> None:
    """Drop resource-service link table."""
    op.drop_table('resource_service_link')
