from sqladmin import ModelView

from src.domain.entities.interaction import CitizenInteraction, LegalEscalation
from src.domain.entities.law import LawVersion, LegalArticle, LegalStructure


class LawVersionAdmin(ModelView, model=LawVersion):
    """Vue d'administration des versions du Code du numérique."""

    name = "Version de Loi"
    name_plural = "Versions du Code"
    icon = "fa-solid fa-book"
    column_list = [
        LawVersion.official_reference,
        LawVersion.code_name,
        LawVersion.effective_date,
        LawVersion.is_active,
        LawVersion.created_at,
    ]
    column_searchable_list = [LawVersion.official_reference, LawVersion.code_name]
    column_sortable_list = [LawVersion.effective_date, LawVersion.is_active]
    can_create = True
    can_edit = True
    can_delete = False


class LegalStructureAdmin(ModelView, model=LegalStructure):
    """Vue d'administration de la structure hiérarchique du Code."""

    name = "Structure Juridique"
    name_plural = "Structures (Livres/Titres/Chapitres)"
    icon = "fa-solid fa-sitemap"
    column_list = [
        LegalStructure.structure_type,
        LegalStructure.number_label,
        LegalStructure.title,
        LegalStructure.order_index,
    ]
    column_searchable_list = [LegalStructure.title, LegalStructure.number_label]


class LegalArticleAdmin(ModelView, model=LegalArticle):
    """Vue d'administration des articles individuels."""

    name = "Article du Code"
    name_plural = "Articles de Loi"
    icon = "fa-solid fa-scale-balanced"
    column_list = [
        LegalArticle.article_number,
        LegalArticle.is_in_force,
        LegalArticle.created_at,
    ]
    column_searchable_list = [LegalArticle.article_number, LegalArticle.full_content]
    column_filters = [LegalArticle.is_in_force]
    can_create = True
    can_edit = True
    can_delete = False


class CitizenInteractionAdmin(ModelView, model=CitizenInteraction):
    """Vue d'audit des questions et réponses posées par les usagers."""

    name = "Interaction Citoyenne"
    name_plural = "Historique des Échanges"
    icon = "fa-solid fa-comments"
    column_list = [
        CitizenInteraction.id,
        CitizenInteraction.channel,
        CitizenInteraction.legal_status,
        CitizenInteraction.confidence_score,
        CitizenInteraction.is_escalated,
        CitizenInteraction.created_at,
    ]
    column_searchable_list = [CitizenInteraction.raw_input, CitizenInteraction.response_text]
    column_filters = [
        CitizenInteraction.channel,
        CitizenInteraction.legal_status,
        CitizenInteraction.is_escalated,
    ]
    can_create = False
    can_edit = False
    can_delete = False


class LegalEscalationAdmin(ModelView, model=LegalEscalation):
    """Vue d'escalade et traitement des cas ambigus par les juristes."""

    name = "Dossier d'Escalade"
    name_plural = "Escalades Juridiques"
    icon = "fa-solid fa-user-shield"
    column_list = [
        LegalEscalation.id,
        LegalEscalation.citizen_contact,
        LegalEscalation.reason,
        LegalEscalation.status,
        LegalEscalation.assigned_jurist,
        LegalEscalation.created_at,
    ]
    column_searchable_list = [LegalEscalation.citizen_contact, LegalEscalation.question_summary]
    column_filters = [LegalEscalation.status, LegalEscalation.reason]
    can_create = False
    can_edit = True
    can_delete = False
