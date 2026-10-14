"""Bounded outbox retries and durable fenced email delivery claims.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "outbox_events",
        sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbox_events",
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column("outbox_events", sa.Column("failed_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_events", sa.Column("last_error_code", sa.String(64)))
    op.create_table(
        "email_deliveries",
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("outbox_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="retry"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.CheckConstraint("attempts >= 0", name="email_deliveries_attempts_nonnegative"),
        sa.CheckConstraint(
            "(status = 'sending' AND lease_token IS NOT NULL AND lease_until IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'retry' AND lease_token IS NULL AND lease_until IS NULL "
            "AND completed_at IS NULL) OR "
            "(status IN ('sent', 'skipped', 'failed') AND lease_token IS NULL "
            "AND lease_until IS NULL AND completed_at IS NOT NULL)",
            name="email_deliveries_state_consistent",
        ),
    )


def downgrade():
    # Removes retry/delivery evidence; not a safe operational rollback.
    op.drop_table("email_deliveries")
    for name in ("last_error_code", "failed_at", "next_attempt_at", "publish_attempts"):
        op.drop_column("outbox_events", name)
