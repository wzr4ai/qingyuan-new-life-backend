"""Add technician policy and pricing tables

Revision ID: d1cfe2c1b6d8
Revises: b320f522791a
Create Date: 2025-11-05 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d1cfe2c1b6d8"
down_revision = "b320f522791a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technician_policies",
        sa.Column("uid", sa.String(length=26), nullable=False),
        sa.Column("technician_id", sa.String(length=26), nullable=False),
        sa.Column("location_id", sa.String(length=26), nullable=True),
        sa.Column("max_daily_online", sa.Integer(), nullable=True),
        sa.Column("max_morning_online", sa.Integer(), nullable=True),
        sa.Column("max_afternoon_online", sa.Integer(), nullable=True),
        sa.Column("auto_assign_priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("allow_public_booking", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["location_id"], ["locations.uid"]),
        sa.ForeignKeyConstraint(["technician_id"], ["users.uid"]),
        sa.PrimaryKeyConstraint("uid"),
        sa.UniqueConstraint("technician_id", "location_id", name="uq_technician_policy"),
    )
    op.create_index(op.f("ix_technician_policies_uid"), "technician_policies", ["uid"], unique=False)
    op.create_index(op.f("ix_technician_policies_technician_id"), "technician_policies", ["technician_id"], unique=False)
    op.create_index(op.f("ix_technician_policies_location_id"), "technician_policies", ["location_id"], unique=False)

    op.create_table(
        "technician_service_pricing",
        sa.Column("uid", sa.String(length=26), nullable=False),
        sa.Column("service_id", sa.String(length=26), nullable=False),
        sa.Column("technician_id", sa.String(length=26), nullable=True),
        sa.Column("location_id", sa.String(length=26), nullable=True),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["location_id"], ["locations.uid"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.uid"]),
        sa.ForeignKeyConstraint(["technician_id"], ["users.uid"]),
        sa.PrimaryKeyConstraint("uid"),
        sa.UniqueConstraint(
            "service_id",
            "technician_id",
            "location_id",
            name="uq_technician_service_pricing",
        ),
    )
    op.create_index(
        op.f("ix_technician_service_pricing_uid"),
        "technician_service_pricing",
        ["uid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_technician_service_pricing_service_id"),
        "technician_service_pricing",
        ["service_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_technician_service_pricing_technician_id"),
        "technician_service_pricing",
        ["technician_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_technician_service_pricing_location_id"),
        "technician_service_pricing",
        ["location_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_technician_service_pricing_location_id"), table_name="technician_service_pricing")
    op.drop_index(op.f("ix_technician_service_pricing_technician_id"), table_name="technician_service_pricing")
    op.drop_index(op.f("ix_technician_service_pricing_service_id"), table_name="technician_service_pricing")
    op.drop_index(op.f("ix_technician_service_pricing_uid"), table_name="technician_service_pricing")
    op.drop_table("technician_service_pricing")

    op.drop_index(op.f("ix_technician_policies_location_id"), table_name="technician_policies")
    op.drop_index(op.f("ix_technician_policies_technician_id"), table_name="technician_policies")
    op.drop_index(op.f("ix_technician_policies_uid"), table_name="technician_policies")
    op.drop_table("technician_policies")
