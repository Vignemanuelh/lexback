from enum import StrEnum

from pydantic import BaseModel, Field


class LegalStatus(StrEnum):
    """Statut juridique de l'action envisagée selon le Code du numérique."""

    AUTORISE = "autorisé"
    INTERDIT = "interdit"
    A_RISQUE = "à risque"
    ZONE_GRISE = "zone grise"


class LegalResponseSchema(BaseModel):
    """Schéma de sortie structuré imposé à Google Gemini."""

    statut_legal: LegalStatus = Field(
        description="Statut juridique clair de l'action selon le Code du numérique béninois."
    )
    articles_cites: list[str] = Field(
        default_factory=list,
        description=(
            "Liste exacte des numéros d'articles cités et applicables "
            "(ex: ['Article 550', 'Article 552'])."
        ),
    )
    explication_vulgarisee: str = Field(
        description=(
            "Explication pédagogique accessible au citoyen en français clair sans jargon inutile."
        )
    )
    conseil_pratique: str = Field(
        description="Conseil concret et opérationnel pour agir en toute légalité et sécurité."
    )
    avertissement_legal: str = Field(
        default=(
            "Cet assistant est un outil de vulgarisation et ne remplace pas un conseil "
            "juridique professionnel dispensé par un avocat."
        ),
        description="Mention obligatoire sur les limites de l'outil.",
    )
    necessite_escalade: bool = Field(
        default=False,
        description="Vrai si la situation est ambigüe, incertaine ou dépasse le champ couvert.",
    )


class LegalQuestionRequest(BaseModel):
    """Requête utilisateur envoyée à l'API."""

    question: str = Field(
        ..., min_length=3, max_length=2000, description="Question en langage naturel de l'usager."
    )
    user_id: str | None = Field(None, description="Identifiant usager (anonymisé ou session web).")
    channel: str = Field("WEB", description="Canal d'origine: WEB ou WHATSAPP.")


class LegalArticleCitation(BaseModel):
    """Extrait d'article retourné en source."""

    article_number: str
    structure_title: str | None = None
    content: str
    relevance_score: float


class LegalQuestionResponse(BaseModel):
    """Réponse complète transmise au client Web ou au bot WhatsApp."""

    interaction_id: str
    statut_legal: LegalStatus
    articles_cites: list[str]
    explication_vulgarisee: str
    conseil_pratique: str
    avertissement_legal: str
    necessite_escalade: bool
    sources: list[LegalArticleCitation] = Field(default_factory=list)
    confidence_score: float = 1.0


class CitizenFeedbackRequest(BaseModel):
    """Signalement ou retour d'usager sur une réponse."""

    interaction_id: str
    rating: int = Field(..., ge=-1, le=1, description="1 pour satisfaisant, -1 pour insatisfaisant")
    comment: str | None = Field(
        None, max_length=1000, description="Précision ou signalement d'erreur"
    )


class EscalationRequest(BaseModel):
    """Formulaire de mise en relation vers un juriste."""

    interaction_id: str | None = None
    citizen_contact: str = Field(..., description="Numéro de téléphone ou email de l'usager")
    question_summary: str = Field(..., description="Résumé de la situation à clarifier")
    reason: str = Field("ZONE_GRISE", description="Raison de l'escalade")


class MultimodalQuestionResponse(LegalQuestionResponse):
    """Réponse enrichie pour les requêtes citoyennes multimodales Web."""

    extracted_content: str | None = Field(
        None, description="Contenu brut extrait par transcription audio ou analyse OCR."
    )
    detected_media_type: str | None = Field(
        None, description="Type de média détecté : 'audio' ou 'image'."
    )


class EscalationUpdateRequest(BaseModel):
    """Mise à jour d'un dossier d'escalade par un juriste référent."""

    status: str | None = Field(None, description="Nouveau statut : PENDING, IN_REVIEW, RESOLVED")
    assigned_jurist: str | None = Field(None, description="Nom du juriste référent assigné")
    jurist_response: str | None = Field(None, description="Notes d'instruction ou avis formulé")


class EscalationItemResponse(BaseModel):
    """Fiche détaillée d'un dossier d'escalade citoyenne."""

    id: str
    interaction_id: str | None = None
    reference_number: str
    citizen_contact: str
    question_summary: str
    reason: str
    status: str
    assigned_jurist: str | None = None
    jurist_response: str | None = None
    created_at: str
    resolved_at: str | None = None
    interaction_context: dict | None = None


class PartnerMetricsResponse(BaseModel):
    """Indicateurs d'audit et de performance juridique de la permanence conventionnée."""

    sla_average_hours: float = 4.25
    monthly_requests: int = 47
    accuracy_rate: float = 96.4
    citation_verification_rate: float = 99.1
    grey_zone_escalation_rate: float = 8.2
    pending_audits_count: int = 12
    active_law_reference: str = "Loi N° 2017-20 consolidée"
    total_indexed_articles: int = 646
    apdp_encrypted: bool = True

