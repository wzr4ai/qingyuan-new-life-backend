"""Set default value for resource type column

Revision ID: e6b7c91a4a74
Revises: cb030248aed2
Create Date: 2025-11-03 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text, inspect


# revision identifiers, used by Alembic.
revision: str = 'e6b7c91a4a74'
down_revision: Union[str, Sequence[str], None] = '7e22940322c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure resources.type column exists and defaults to 'room'."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('resources')]
    resource_enum = sa.Enum('technician', 'room', name='resource_type_enum')

    if 'type' not in columns:
        resource_enum.create(bind, checkfirst=True)
        op.add_column(
            'resources',
            sa.Column('type', resource_enum, nullable=False, server_default='room')
        )
    else:
        with op.batch_alter_table('resources', schema=None) as batch_op:
            batch_op.alter_column(
                'type',
                existing_type=resource_enum,
                server_default='room'
            )

    op.execute(text("UPDATE resources SET type = 'room' WHERE type IS NULL OR type = ''"))


def downgrade() -> None:
    """Rollback default or column addition for resources.type."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns('resources')]
    resource_enum = sa.Enum('technician', 'room', name='resource_type_enum')

    if 'type' not in columns:
        return

    with op.batch_alter_table('resources', schema=None) as batch_op:
        batch_op.alter_column(
            'type',
            existing_type=resource_enum,
            server_default=None
        )
