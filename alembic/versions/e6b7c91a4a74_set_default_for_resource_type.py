"""Set default value for resource type column

Revision ID: e6b7c91a4a74
Revises: cb030248aed2
Create Date: 2025-11-03 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b7c91a4a74'
down_revision: Union[str, Sequence[str], None] = 'cb030248aed2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure resources.type has a default value."""
    resource_enum = sa.Enum('technician', 'room', name='resource_type_enum')
    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.alter_column(
            'type',
            existing_type=resource_enum,
            server_default='room'
        )


def downgrade() -> None:
    """Remove default value on resources.type."""
    resource_enum = sa.Enum('technician', 'room', name='resource_type_enum')
    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.alter_column(
            'type',
            existing_type=resource_enum,
            server_default=None
        )
