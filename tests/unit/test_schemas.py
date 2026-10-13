import pytest
from pydantic import ValidationError

from src.domain.schemas.rag import (
    LegalQuestionRequest,
    LegalResponseSchema,
    LegalStatus,
)


def test_legal_status_enum():
    """RG-JUR4 : Vérification stricte des 4 statuts légaux autorisés."""
    assert LegalStatus.AUTORISE.value == "autorisé"
    assert LegalStatus.INTERDIT.value == "interdit"
    assert LegalStatus.A_RISQUE.value == "à risque"
    assert LegalStatus.ZONE_GRISE.value == "zone grise"


def test_legal_response_schema_validation():
    """Vérifie la sérialisation et les valeurs par défaut de LegalResponseSchema."""
    schema = LegalResponseSchema(
        statut_legal=LegalStatus.A_RISQUE,
        articles_cites=["Article 550"],
        explication_vulgarisee="Cette publication comporte des risques de diffamation.",
        conseil_pratique="Vérifiez les faits auprès d'une source officielle.",
        necessite_escalade=False,
    )
    assert schema.statut_legal == LegalStatus.A_RISQUE
    assert "avocat" in schema.avertissement_legal  # RG-JUR6 Avertissement présent par défaut


def test_question_request_length_validation():
    """Vérifie le rejet des questions trop courtes (< 3 caractères)."""
    with pytest.raises(ValidationError):
        LegalQuestionRequest(question="ab")
