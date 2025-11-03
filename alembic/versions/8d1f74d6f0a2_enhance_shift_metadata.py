"""Enhance shift metadata for technician scheduling

Revision ID: 8d1f74d6f0a2
Revises: 0d9f2a7c520b
Create Date: 2025-11-03 18:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d1f74d6f0a2'
down_revision: Union[str, Sequence[str], None] = '0d9f2a7c520b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add audit, cancellation, and period metadata to shifts."""
    with op.batch_alter_table('shifts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('period', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('created_by_user_id', sa.String(length=26), nullable=True))
        batch_op.add_column(
            sa.Column(
                'locked_by_admin',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('0')
            )
        )
        batch_op.add_column(
            sa.Column(
                'is_cancelled',
                sa.Boolean(),
                nullable=False,
                server_default=sa.text('0')
            )
        )
        batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('cancelled_by_user_id', sa.String(length=26), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            'fk_shifts_created_by_user',
            'users',
            ['created_by_user_id'],
            ['uid'],
            ondelete='SET NULL'
        )
        batch_op.create_foreign_key(
            'fk_shifts_cancelled_by_user',
            'users',
            ['cancelled_by_user_id'],
            ['uid'],
            ondelete='SET NULL'
        )
        batch_op.create_index('ix_shifts_created_by_user_id', ['created_by_user_id'])
        batch_op.create_index('ix_shifts_cancelled_by_user_id', ['cancelled_by_user_id'])
        batch_op.create_index('ix_shifts_is_cancelled', ['is_cancelled'])
        batch_op.create_index('ix_shifts_period', ['period'])

    # 将现有排班标记为管理员创建
    op.execute(
        """
        UPDATE shifts
        SET locked_by_admin = 1
        """
    )


def downgrade() -> None:
    """Revert shift metadata additions."""
    with op.batch_alter_table('shifts', schema=None) as batch_op:
        batch_op.drop_index('ix_shifts_period')
        batch_op.drop_index('ix_shifts_is_cancelled')
        batch_op.drop_index('ix_shifts_cancelled_by_user_id')
        batch_op.drop_index('ix_shifts_created_by_user_id')
        batch_op.drop_constraint('fk_shifts_cancelled_by_user', type_='foreignkey')
        batch_op.drop_constraint('fk_shifts_created_by_user', type_='foreignkey')
        batch_op.drop_column('updated_at')
        batch_op.drop_column('cancelled_by_user_id')
        batch_op.drop_column('cancelled_at')
        batch_op.drop_column('is_cancelled')
        batch_op.drop_column('locked_by_admin')
        batch_op.drop_column('created_by_user_id')
        batch_op.drop_column('period')
