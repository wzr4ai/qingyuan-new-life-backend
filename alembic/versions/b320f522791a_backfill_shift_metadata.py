"""Backfill shift metadata columns for scheduling

Revision ID: b320f522791a
Revises: 8d1f74d6f0a2
Create Date: 2025-11-04 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


# revision identifiers, used by Alembic.
revision: str = 'b320f522791a'
down_revision: Union[str, Sequence[str], None] = '8d1f74d6f0a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ensure shift metadata columns exist on environments that missed earlier upgrade."""
    bind = op.get_bind()
    inspector = inspect(bind)

    tables = set(inspector.get_table_names())
    columns = {col['name'] for col in inspector.get_columns('shifts')}
    indexes = {idx['name'] for idx in inspector.get_indexes('shifts')}
    fk_names = {fk['name'] for fk in inspector.get_foreign_keys('shifts')}

    has_period = 'period' in columns
    has_created_by = 'created_by_user_id' in columns
    has_locked = 'locked_by_admin' in columns
    has_is_cancelled = 'is_cancelled' in columns
    has_cancelled_at = 'cancelled_at' in columns
    has_cancelled_by = 'cancelled_by_user_id' in columns
    has_updated_at = 'updated_at' in columns

    # Add missing columns in a single batch operation.
    with op.batch_alter_table('shifts', schema=None) as batch_op:
        if not has_period:
            batch_op.add_column(sa.Column('period', sa.String(length=20), nullable=True))
            has_period = True
        if not has_created_by:
            batch_op.add_column(sa.Column('created_by_user_id', sa.String(length=26), nullable=True))
            has_created_by = True
        if not has_locked:
            batch_op.add_column(
                sa.Column(
                    'locked_by_admin',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('0')
                )
            )
            has_locked = True
        else:
            batch_op.alter_column(
                'locked_by_admin',
                existing_type=sa.Boolean(),
                existing_nullable=False,
                server_default=sa.text('0')
            )
        if not has_is_cancelled:
            batch_op.add_column(
                sa.Column(
                    'is_cancelled',
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text('0')
                )
            )
            has_is_cancelled = True
        else:
            batch_op.alter_column(
                'is_cancelled',
                existing_type=sa.Boolean(),
                existing_nullable=False,
                server_default=sa.text('0')
            )
        if not has_cancelled_at:
            batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
            has_cancelled_at = True
        if not has_cancelled_by:
            batch_op.add_column(sa.Column('cancelled_by_user_id', sa.String(length=26), nullable=True))
            has_cancelled_by = True
        if not has_updated_at:
            batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
            has_updated_at = True

        # Ensure foreign keys exist when corresponding columns are present.
        if has_created_by and 'fk_shifts_created_by_user' not in fk_names:
            batch_op.create_foreign_key(
                'fk_shifts_created_by_user',
                'users',
                ['created_by_user_id'],
                ['uid'],
                ondelete='SET NULL'
            )
        if has_cancelled_by and 'fk_shifts_cancelled_by_user' not in fk_names:
            batch_op.create_foreign_key(
                'fk_shifts_cancelled_by_user',
                'users',
                ['cancelled_by_user_id'],
                ['uid'],
                ondelete='SET NULL'
            )

        # Ensure indexes exist after columns are added.
        if has_period and 'ix_shifts_period' not in indexes:
            batch_op.create_index('ix_shifts_period', ['period'])
        if has_created_by and 'ix_shifts_created_by_user_id' not in indexes:
            batch_op.create_index('ix_shifts_created_by_user_id', ['created_by_user_id'])
        if has_cancelled_by and 'ix_shifts_cancelled_by_user_id' not in indexes:
            batch_op.create_index('ix_shifts_cancelled_by_user_id', ['cancelled_by_user_id'])
        if has_is_cancelled and 'ix_shifts_is_cancelled' not in indexes:
            batch_op.create_index('ix_shifts_is_cancelled', ['is_cancelled'])

    # Backfill admin lock flag so existing rows remain editable.
    op.execute(
        text(
            """
            UPDATE shifts
            SET
                locked_by_admin = COALESCE(locked_by_admin, 0),
                is_cancelled = COALESCE(is_cancelled, 0)
            """
        )
    )

    # Ensure resource-service link table exists for resource capability binding.
    if 'resource_service_link' not in tables:
        op.create_table(
            'resource_service_link',
            sa.Column('resource_id', sa.String(length=26), nullable=False),
            sa.Column('service_id', sa.String(length=26), nullable=False),
            sa.ForeignKeyConstraint(['resource_id'], ['resources.uid'], ),
            sa.ForeignKeyConstraint(['service_id'], ['services.uid'], ),
            sa.PrimaryKeyConstraint('resource_id', 'service_id')
        )


def downgrade() -> None:
    """Do not attempt to remove metadata columns; keeping them is safe."""
    # No-op downgrade to avoid dropping operational columns.
    pass
