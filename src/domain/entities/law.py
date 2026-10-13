import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import VECTOR

from src.core.database import Base


class LawVersion(Base):
    """Représente une version officielle du Code ou d'un texte de loi."""

    __tablename__ = "law_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_name: Mapped[str] = mapped_column(String(255), nullable=False)
    official_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    promulgation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    structures: Mapped[list["LegalStructure"]] = relationship(
        "LegalStructure", back_populates="law_version", cascade="all, delete-orphan"
    )
    articles: Mapped[list["LegalArticle"]] = relationship(
        "LegalArticle", back_populates="law_version", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<LawVersion {self.official_reference} (active={self.is_active})>"


class LegalStructure(Base):
    """Structure hiérarchique de la loi (Livre, Titre, Chapitre, Section)."""

    __tablename__ = "legal_structures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    law_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("law_versions.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_structures.id", ondelete="CASCADE"), nullable=True
    )
    structure_type: Mapped[str] = mapped_column(String(50), nullable=False)
    number_label: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    law_version: Mapped["LawVersion"] = relationship("LawVersion", back_populates="structures")
    parent: Mapped[Optional["LegalStructure"]] = relationship(
        "LegalStructure", remote_side=[id], backref="children"
    )
    articles: Mapped[list["LegalArticle"]] = relationship(
        "LegalArticle", back_populates="structure"
    )

    def __repr__(self) -> str:
        return f"<LegalStructure {self.structure_type} {self.number_label}: {self.title[:30]}>"


class LegalArticle(Base):
    """Article individuel du Code du numérique conservé intégralement."""

    __tablename__ = "legal_articles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    law_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("law_versions.id", ondelete="CASCADE"), nullable=False
    )
    structure_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_structures.id", ondelete="SET NULL"), nullable=True
    )
    article_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    full_content: Mapped[str] = mapped_column(Text, nullable=False)
    is_in_force: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    amendment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    search_vector = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    law_version: Mapped["LawVersion"] = relationship("LawVersion", back_populates="articles")
    structure: Mapped[Optional["LegalStructure"]] = relationship(
        "LegalStructure", back_populates="articles"
    )
    embeddings: Mapped[list["ArticleEmbedding"]] = relationship(
        "ArticleEmbedding", back_populates="article", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_legal_articles_tsv", search_vector, postgresql_using="gin"),
        Index("idx_article_version_num", law_version_id, article_number),
    )

    def __repr__(self) -> str:
        return f"<LegalArticle {self.article_number} (in_force={self.is_in_force})>"


class ArticleEmbedding(Base):
    """Représentation vectorielle dense d'un article pour la recherche sémantique."""

    __tablename__ = "article_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legal_articles.id", ondelete="CASCADE"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(100), default="text-embedding-004", nullable=False)
    embedding = mapped_column(VECTOR(768), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    article: Mapped["LegalArticle"] = relationship("LegalArticle", back_populates="embeddings")

    __table_args__ = (
        Index(
            "idx_article_embedding_hnsw",
            embedding,
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
