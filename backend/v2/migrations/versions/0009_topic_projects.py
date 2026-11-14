"""Topic projects and extractive, revalidated learning-memory pointers.

Revision ID: 0009_topic_projects
Revises: 0008_conversations
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0009_topic_projects'
down_revision = '0008_conversations'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('projects',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('title', sa.String(100), nullable=False),
        sa.Column('description', sa.String(500), server_default='', nullable=False),
        sa.Column('memory_source_ids', postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint('length(btrim(title)) > 0', name=op.f('ck_projects_title_not_blank')),
        sa.CheckConstraint('length(title) <= 100', name=op.f('ck_projects_title_length')),
        sa.CheckConstraint('length(description) <= 500', name=op.f('ck_projects_description_length')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_projects_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_projects')),
    )
    op.create_index('ix_projects_user_active_created', 'projects', ['user_id', 'created_at'], postgresql_where=sa.text('deleted_at IS NULL'))
    op.add_column('conversations', sa.Column('project_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_conversations_project_id_projects'), 'conversations', 'projects', ['project_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_conversations_project_id', 'conversations', ['project_id'])
    op.create_table('project_memories',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('project_id', sa.Uuid(), nullable=False),
        sa.Column('answer_message_id', sa.Uuid(), nullable=False),
        sa.Column('topic', sa.String(100), nullable=False),
        sa.Column('summary', sa.String(600), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('length(summary) <= 600', name=op.f('ck_project_memories_summary_length')),
        sa.CheckConstraint('length(topic) <= 100', name=op.f('ck_project_memories_topic_length')),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], name=op.f('fk_project_memories_project_id_projects'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['answer_message_id'], ['messages.id'], name=op.f('fk_project_memories_answer_message_id_messages'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_project_memories')),
        sa.UniqueConstraint('answer_message_id', name='uq_project_memories_answer_message'),
    )
    op.create_index('ix_project_memories_project_created', 'project_memories', ['project_id', 'created_at'])


def downgrade():
    op.drop_index('ix_project_memories_project_created', table_name='project_memories')
    op.drop_table('project_memories')
    op.drop_index('ix_conversations_project_id', table_name='conversations')
    op.drop_constraint(op.f('fk_conversations_project_id_projects'), 'conversations', type_='foreignkey')
    op.drop_column('conversations', 'project_id')
    op.drop_index('ix_projects_user_active_created', table_name='projects', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_table('projects')
