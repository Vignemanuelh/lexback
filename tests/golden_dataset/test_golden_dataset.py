import json
from pathlib import Path

import pytest

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.domain.schemas.rag import LegalResponseSchema, LegalStatus

GOLDEN_DATASET_PATH = Path(__file__).parent / "golden_cases.json"
CODE_COMPLET_PATH = Path(__file__).parents[2] / "data" / "processed" / "code_du_numerique_complet.json"


def load_golden_cases():
    with open(GOLDEN_DATASET_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_official_articles():
    if not CODE_COMPLET_PATH.exists():
        return {}
    with open(CODE_COMPLET_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {art["article_number"]: art for art in data}
    return {art["article_number"]: art for art in data.get("articles", [])}


class TestGoldenDatasetIntegrity:
    """Vérifie la rigueur et la conformité juridique du banc de test (Golden Dataset)."""

    def test_golden_dataset_has_minimum_cases(self):
        cases = load_golden_cases()
        assert len(cases) >= 20, f"Le Golden Dataset doit contenir au moins 20 cas, trouvé: {len(cases)}"

    def test_all_cases_have_valid_legal_status(self):
        cases = load_golden_cases()
        valid_statuses = {s.value for s in LegalStatus}
        for case in cases:
            status = case.get("expected_status")
            assert status in valid_statuses, (
                f"Cas {case['id']}: statut '{status}' non valide. Statuts acceptés: {valid_statuses}"
            )

    def test_rg_jur5_escalation_mandatory_for_grey_zones(self):
        """RG-JUR5 : Toute zone grise doit obligatoirement avoir must_escalate=True."""
        cases = load_golden_cases()
        for case in cases:
            if case.get("expected_status") == LegalStatus.ZONE_GRISE.value:
                assert case.get("must_escalate") is True, (
                    f"Cas {case['id']}: zone grise sans escalade obligatoire."
                )

    def test_rg_jur1_expected_articles_exist_in_official_code(self):
        """RG-JUR1 : Aucun article attendu ne doit être fictif ou absent du Code officiel."""
        cases = load_golden_cases()
        official_articles = load_official_articles()
        if not official_articles:
            pytest.skip("Fichier code_du_numerique_complet.json non présent sur le disque.")

        for case in cases:
            for art_num in case.get("expected_articles", []):
                assert art_num in official_articles, (
                    f"Cas {case['id']}: l'article {art_num} attendu n'existe pas dans le Code du numérique!"
                )

    def test_distribution_of_legal_statuses(self):
        """Vérifie que les 4 qualifications juridiques sont représentées dans le banc."""
        cases = load_golden_cases()
        statuses_found = {case["expected_status"] for case in cases}
        assert LegalStatus.INTERDIT.value in statuses_found
        assert LegalStatus.AUTORISE.value in statuses_found
        assert LegalStatus.A_RISQUE.value in statuses_found
        assert LegalStatus.ZONE_GRISE.value in statuses_found


class TestGoldenDatasetGuardrailFidelity:
    """Évalue la fidélité juridique et le comportement du CitationGuardrail sur chaque cas."""

    @pytest.mark.parametrize("case", load_golden_cases())
    def test_guardrail_validates_golden_cases(self, case):
        guardrail = CitationGuardrail()
        status_enum = LegalStatus(case["expected_status"])
        expected_articles = [f"Article {a}" for a in case["expected_articles"]]

        # Simule la réponse du LLM pour le cas
        llm_response = LegalResponseSchema(
            statut_legal=status_enum,
            articles_cites=expected_articles,
            explication_vulgarisee=case["rationale"],
            conseil_pratique="Respectez les prescriptions légales.",
            avertissement_legal="Cet assistant est un outil d'information juridique citoyenne.",
            necessite_escalade=case["must_escalate"],
        )

        # Si des articles sont attendus, ils sont présents dans le contexte récupéré
        retrieved = case["expected_articles"]
        result = guardrail.validate(response=llm_response, retrieved_article_numbers=retrieved)

        assert result.is_valid is True, f"Cas {case['id']} rejeté à tort par le guardrail."
        assert len(result.hallucinated_articles) == 0
        assert result.validated_response.statut_legal == status_enum
        assert result.validated_response.necessite_escalade == case["must_escalate"]
        assert len(result.validated_response.avertissement_legal) > 10

    @pytest.mark.parametrize("case", load_golden_cases())
    def test_guardrail_rejects_hallucination_on_golden_cases(self, case):
        """RG-JUR2 : Tout article halluciné (absent des sources) doit être détecté et rejeté."""
        if not case["expected_articles"]:
            # Cas déjà sans article (zone grise)
            return

        guardrail = CitationGuardrail()
        status_enum = LegalStatus(case["expected_status"])

        # Injecte un article fictif absent du contexte récupéré
        hallucinated_article = "9999"
        llm_response = LegalResponseSchema(
            statut_legal=status_enum,
            articles_cites=[f"Article {hallucinated_article}"],
            explication_vulgarisee="Réponse avec hallucination d'article.",
            conseil_pratique="Ne rien faire.",
            avertissement_legal="Avertissement.",
            necessite_escalade=False,
        )

        # Le contexte ne contient que les articles légitimes
        retrieved = case["expected_articles"]
        result = guardrail.validate(response=llm_response, retrieved_article_numbers=retrieved)

        assert result.is_valid is False, f"Cas {case['id']}: l'hallucination n'a pas été détectée!"
        assert hallucinated_article in result.hallucinated_articles
        # Doit être rétrogradé en zone grise avec escalade obligatoire
        assert result.validated_response.statut_legal == LegalStatus.ZONE_GRISE
        assert result.validated_response.necessite_escalade is True
