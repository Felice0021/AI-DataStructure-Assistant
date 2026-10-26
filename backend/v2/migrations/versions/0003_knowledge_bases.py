"""Add owned private and system-managed public knowledge bases."""
from alembic import op
import sqlalchemy as sa

revision = "0003_knowledge_bases"
down_revision = "0002_login_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_key", sa.Text(), sa.Computed("lower(btrim(regexp_replace(normalize(name, NFKC), '[[:space:]]+', ' ', 'g')))", persisted=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("visibility", sa.String(7), nullable=False, server_default="private"),
        sa.Column("index_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_bases")),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT", name=op.f("fk_knowledge_bases_owner_id_users")),
        sa.CheckConstraint("visibility IN ('private', 'public')", name=op.f("ck_knowledge_bases_visibility")),
        sa.CheckConstraint("(visibility = 'private' AND owner_id IS NOT NULL) OR (visibility = 'public' AND owner_id IS NULL)", name=op.f("ck_knowledge_bases_ownership")),
        sa.CheckConstraint("length(name_key) > 0", name=op.f("ck_knowledge_bases_name_not_blank")),
        sa.CheckConstraint("length(description) <= 4000", name=op.f("ck_knowledge_bases_description_length")),
        sa.CheckConstraint("index_version >= 0", name=op.f("ck_knowledge_bases_index_version")),
    )
    op.create_index("ix_knowledge_bases_owner_id", "knowledge_bases", ["owner_id"])
    op.create_index("ix_knowledge_bases_visibility", "knowledge_bases", ["visibility"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("uq_knowledge_bases_private_name", "knowledge_bases", ["owner_id", "name_key"], unique=True, postgresql_where=sa.text("visibility = 'private' AND deleted_at IS NULL"))
    op.create_index("uq_knowledge_bases_public_name", "knowledge_bases", ["name_key"], unique=True, postgresql_where=sa.text("visibility = 'public' AND deleted_at IS NULL"))


def downgrade() -> None:
    # Destructive; never executed automatically on a development database.
    op.drop_table("knowledge_bases")
