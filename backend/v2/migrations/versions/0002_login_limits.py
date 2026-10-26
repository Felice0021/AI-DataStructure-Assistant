"""Add persistent cross-process login failure windows; preserve existing data."""
from alembic import op
import sqlalchemy as sa

revision = "0002_login_limits"
down_revision = "0001_auth_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_login_limits",
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("failures", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_auth_login_limits")),
        sa.CheckConstraint("failures >= 0", name=op.f("ck_auth_login_limits_failures_nonnegative")),
    )


def downgrade() -> None:
    op.drop_table("auth_login_limits")
