import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class CitizenInteraction(Base):
    """Journalise chaque échange pour l'audit, l'observabilité et le signalement."""

    __tablename__ = "citizen_interactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)  # "WHATSAPP", "WEB"
    user_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_input: Mapped[str] = mapped_column(Text, nullable=False)
    input_type: Mapped[str] = mapped_column(String(20), default="TEXT", nullable=False)  # TEXT, AUDIO, IMAGE
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False)
    legal_status: Mapped[str] = mapped_column(String(30), nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    cited_articles: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    is_escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    langfuse_trace_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Retours d'usagers
    user_feedback_rating: Mapped[Optional[int]] = mapped_column(nullable=True)  # +1 (satisfait), -1 (insatisfait)
    user_feedback_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    escalations: Mapped[list["LegalEscalation"]] = relationship(
        "LegalEscalation", back_populates="interaction"
    )

    def __repr__(self) -> str:
        return f"<CitizenInteraction {self.id} [{self.channel}] status={self.legal_status}>"


class LegalEscalation(Base):
    """Dossier d'escalade vers un juriste référent pour les cas ambigus ou zones grises."""

    __tablename__ = "legal_escalations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    interaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citizen_interactions.id", ondelete="SET NULL"), nullable=True
    )
    citizen_contact: Mapped[str] = mapped_column(String(255), nullable=False)
    question_summary: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(100), nullable=False)  # "ZONE_GRISE", "HORS_CHAMP", "DEMANDE_USAGER"
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)  # PENDING, IN_REVIEW, RESOLVED
    assigned_jurist: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    jurist_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    interaction: Mapped[Optional["CitizenInteraction"]] = relationship(
        "CitizenInteraction", back_populates="escalations"
    )

    def __repr__(self) -> str:
        return f"<LegalEscalation {self.id} status={self.status}>"
