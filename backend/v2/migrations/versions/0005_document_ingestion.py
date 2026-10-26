"""Add versioned text chunks and leased PostgreSQL ingestion jobs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_document_ingestion"
down_revision = "0004_documents"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(op.f("ck_documents_status"), "documents", type_="check")
    op.create_check_constraint(op.f("ck_documents_status"), "documents", "status IN ('uploaded','processing','parsed','ready','failed')")
    op.add_column("documents", sa.Column("ingestion_version", sa.Integer(), nullable=False, server_default=sa.text("1")))
    op.add_column("documents", sa.Column("parsed_version", sa.Integer(), nullable=True))
    op.create_check_constraint(op.f("ck_documents_ingestion_version"), "documents", "ingestion_version > 0")
    op.create_check_constraint(op.f("ck_documents_parsed_version"), "documents", "parsed_version IS NULL OR parsed_version = ingestion_version")
    op.create_index("ix_documents_ingestion_pending", "documents", ["status", "created_at"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(300), nullable=True),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT", name="fk_document_chunks_document_id_documents"),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_id"),
        sa.CheckConstraint("chunk_index >= 0", name=op.f("ck_document_chunks_chunk_index")),
        sa.CheckConstraint("generation > 0", name=op.f("ck_document_chunks_generation")),
        sa.CheckConstraint("length(content) > 0", name=op.f("ck_document_chunks_content")),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_document_chunks_content_hash")),
        sa.CheckConstraint("page_number IS NULL OR page_number > 0", name=op.f("ck_document_chunks_page_number")),
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_jobs"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT", name="fk_ingestion_jobs_document_id_documents"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT", name="fk_ingestion_jobs_requested_by_users"),
        sa.UniqueConstraint("document_id", name="uq_ingestion_jobs_document_id"),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name=op.f("ck_ingestion_jobs_status")),
        sa.CheckConstraint("generation > 0", name=op.f("ck_ingestion_jobs_generation")),
        sa.CheckConstraint("attempts >= 0 AND attempts <= max_attempts AND max_attempts BETWEEN 1 AND 10", name=op.f("ck_ingestion_jobs_attempts")),
        sa.CheckConstraint("(status = 'running' AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'running' AND lease_token IS NULL AND lease_expires_at IS NULL)", name=op.f("ck_ingestion_jobs_lease")),
        sa.CheckConstraint("error_code IS NULL OR error_code ~ '^[a-z_]{1,64}$'", name=op.f("ck_ingestion_jobs_error_code")),
    )
    op.create_index("ix_ingestion_jobs_due", "ingestion_jobs", ["status", "next_retry_at", "lease_expires_at"])
    op.create_index("ix_ingestion_jobs_requested_by", "ingestion_jobs", ["requested_by"])


def downgrade():
    op.drop_table("ingestion_jobs")
    op.drop_table("document_chunks")
    op.drop_constraint(op.f("ck_documents_parsed_version"), "documents", type_="check")
    op.drop_constraint(op.f("ck_documents_ingestion_version"), "documents", type_="check")
    op.drop_index("ix_documents_ingestion_pending", table_name="documents")
    op.drop_column("documents", "parsed_version")
    op.drop_column("documents", "ingestion_version")
    op.drop_constraint(op.f("ck_documents_status"), "documents", type_="check")
    op.execute("UPDATE documents SET status='uploaded' WHERE status='parsed'")
    op.create_check_constraint(op.f("ck_documents_status"), "documents", "status IN ('uploaded','processing','ready','failed')")
