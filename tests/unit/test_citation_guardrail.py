import pytest

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.domain.schemas.rag import LegalResponseSchema, LegalStatus


@pytest.fixture
def guardrail():
    return CitationGuardrail()


def test_guardrail_valid_citation(guardrail):
    """RG-JUR2 : La citation est valide quand l'article cité est dans le contexte documentaire."""
    response = LegalResponseSchema(
        statut_legal=LegalStatus.INTERDIT,
        articles_cites=["Article 552"],
        explication_vulgarisee=(
            "L'article 552 du Code du numérique punit la captation d'image non autorisée."
        ),
        conseil_pratique="Demandez le consentement écrit avant toute publication.",
        necessite_escalade=False,
    )
    retrieved_articles = ["552", "553", "554"]

    result = guardrail.validate(response=response, retrieved_article_numbers=retrieved_articles)
    assert result.is_valid is True
    assert len(result.hallucinated_articles) == 0
    assert result.validated_response.statut_legal == LegalStatus.INTERDIT
    assert result.validated_response.necessite_escalade is False


def test_guardrail_detects_hallucination_and_escalates(guardrail):
    """RG-JUR2 & RG-JUR5 : Rejet et escalade si l'article n'est pas dans le contexte."""
    response = LegalResponseSchema(
        statut_legal=LegalStatus.INTERDIT,
        articles_cites=["Article 999"],  # Article fictif / absent des sources
        explication_vulgarisee="L'article 999 interdit formellement cette action.",
        conseil_pratique="Ne publiez rien.",
        necessite_escalade=False,
    )
    retrieved_articles = ["550", "551"]  # 999 n'est pas dedans

    result = guardrail.validate(response=response, retrieved_article_numbers=retrieved_articles)
    assert result.is_valid is False
    assert "999" in result.hallucinated_articles
    # Le garde-fou doit avoir basculé la réponse en zone grise et activé l'escalade
    assert result.validated_response.statut_legal == LegalStatus.ZONE_GRISE
    assert result.validated_response.necessite_escalade is True
    assert result.validated_response.articles_cites == []


def test_extract_article_numbers(guardrail):
    """Vérifie l'extraction de numéros d'articles dans un texte complexe."""
    text = "Selon l'Article 550 et l'art. 552-1 ainsi que l'article 558 du Code."
    numbers = guardrail.extract_article_numbers(text)
    assert "550" in numbers
    assert "552-1" in numbers
    assert "558" in numbers
