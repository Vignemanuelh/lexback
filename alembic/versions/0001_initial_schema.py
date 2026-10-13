"""Initial schema with pgvector and legal entities

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2026-10-13 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import pgvector
from pgvector.sqlalchemy import VECTOR

# revision identifiers, used by Alembic.
revision = '0001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Activation de l'extension pgvector
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # 2. Table law_versions
    op.create_table(
        'law_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('code_name', sa.String(255), nullable=False),
        sa.Column('official_reference', sa.String(255), nullable=False),
        sa.Column('promulgation_date', sa.Date(), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 3. Table legal_structures
    op.create_table(
        'legal_structures',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('law_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('law_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('legal_structures.id', ondelete='CASCADE'), nullable=True),
        sa.Column('structure_type', sa.String(50), nullable=False),
        sa.Column('number_label', sa.String(100), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
    )

    # 4. Table legal_articles
    op.create_table(
        'legal_articles',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('law_version_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('law_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('structure_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('legal_structures.id', ondelete='SET NULL'), nullable=True),
        sa.Column('article_number', sa.String(50), nullable=False),
        sa.Column('full_content', sa.Text(), nullable=False),
        sa.Column('is_in_force', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('amendment_notes', sa.Text(), nullable=True),
        sa.Column('search_vector', postgresql.TSVECTOR(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_legal_articles_tsv', 'legal_articles', ['search_vector'], postgresql_using='gin')
    op.create_index('idx_article_version_num', 'legal_articles', ['law_version_id', 'article_number'])

    # 5. Table article_embeddings
    op.create_table(
        'article_embeddings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('article_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('legal_articles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model_name', sa.String(100), nullable=False, server_default='text-embedding-004'),
        sa.Column('embedding', VECTOR(768), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        'idx_article_embedding_hnsw',
        'article_embeddings',
        ['embedding'],
        postgresql_using='hnsw',
        postgresql_ops={'embedding': 'vector_cosine_ops'},
    )

    # 6. Table citizen_interactions
    op.create_table(
        'citizen_interactions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('channel', sa.String(20), nullable=False),
        sa.Column('user_hash', sa.String(64), nullable=False),
        sa.Column('raw_input', sa.Text(), nullable=False),
        sa.Column('input_type', sa.String(20), nullable=False, server_default='TEXT'),
        sa.Column('normalized_query', sa.Text(), nullable=False),
        sa.Column('legal_status', sa.String(30), nullable=False),
        sa.Column('response_text', sa.Text(), nullable=False),
        sa.Column('cited_articles', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('confidence_score', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('is_escalated', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('langfuse_trace_id', sa.String(100), nullable=True),
        sa.Column('user_feedback_rating', sa.Integer(), nullable=True),
        sa.Column('user_feedback_comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('idx_interaction_user_hash', 'citizen_interactions', ['user_hash'])

    # 7. Table legal_escalations
    op.create_table(
        'legal_escalations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('interaction_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('citizen_interactions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('citizen_contact', sa.String(255), nullable=False),
        sa.Column('question_summary', sa.Text(), nullable=False),
        sa.Column('reason', sa.String(100), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='PENDING'),
        sa.Column('assigned_jurist', sa.String(100), nullable=True),
        sa.Column('jurist_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('legal_escalations')
    op.drop_table('citizen_interactions')
    op.drop_table('article_embeddings')
    op.drop_table('legal_articles')
    op.drop_table('legal_structures')
    op.drop_table('law_versions')
