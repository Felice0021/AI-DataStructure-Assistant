"""Add private raw file metadata and recoverable soft-delete cleanup markers."""
from alembic import op
import sqlalchemy as sa

revision = "0004_documents"
down_revision = "0003_knowledge_bases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storage_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="RESTRICT", name="fk_documents_knowledge_base_id_knowledge_bases"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="RESTRICT", name="fk_documents_uploaded_by_users"),
        sa.UniqueConstraint("storage_key", name="uq_documents_storage_key"),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_documents_positive_size")),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_sha256")),
        sa.CheckConstraint("storage_key ~ '^[0-9a-f]{64}$'", name=op.f("ck_documents_storage_key")),
        sa.CheckConstraint("length(original_filename) BETWEEN 1 AND 255", name=op.f("ck_documents_filename")),
        sa.CheckConstraint("mime_type IN ('application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain')", name=op.f("ck_documents_mime_type")),
        sa.CheckConstraint("status IN ('uploaded', 'processing', 'ready', 'failed')", name=op.f("ck_documents_status")),
        sa.CheckConstraint("storage_deleted_at IS NULL OR deleted_at IS NOT NULL", name=op.f("ck_documents_cleanup_after_delete")),
    )
    op.create_index("ix_documents_kb_active", "documents", ["knowledge_base_id", "created_at", "id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_documents_kb_storage", "documents", ["knowledge_base_id"], postgresql_where=sa.text("storage_deleted_at IS NULL"))
    op.create_index("ix_documents_uploaded_by", "documents", ["uploaded_by"])
    op.create_index("ix_documents_cleanup_pending", "documents", ["deleted_at"], postgresql_where=sa.text("deleted_at IS NOT NULL AND storage_deleted_at IS NULL"))


def downgrade():
    op.drop_table("documents")
