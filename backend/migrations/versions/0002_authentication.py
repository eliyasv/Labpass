"""Add credentials and opaque sessions without changing existing users/bookings.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    # Nullable deliberately: legacy users cannot authenticate until credentials exist.
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    # Case-only duplicates cause a transactional migration failure, never a silent merge.
    op.create_index("users_email_case_insensitive", "users", [sa.text("lower(email)")], unique=True)
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="auth_sessions_lifetime_positive"),
    )
    op.create_index("auth_sessions_user", "auth_sessions", ["user_id"])
    op.create_index("auth_sessions_expiry", "auth_sessions", ["expires_at"])


def downgrade():
    # Removes credentials and sessions; not a safe public-deployment rollback.
    op.drop_index("auth_sessions_expiry", table_name="auth_sessions")
    op.drop_index("auth_sessions_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("users_email_case_insensitive", table_name="users")
    op.drop_column("users", "password_hash")
