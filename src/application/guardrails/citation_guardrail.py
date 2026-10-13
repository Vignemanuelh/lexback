import re
import logging
from dataclasses import dataclass
from src.domain.schemas.rag import LegalResponseSchema, LegalStatus

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    is_valid: bool
    hallucinated_articles: list[str]
    validated_response: LegalResponseSchema
    rejection_reason: str | None = None


class CitationGuardrail:
    """Garde-fou déterministe assurant qu'aucun article fictif n'est cité."""

    ARTICLE_REGEX = re.compile(r"(?:article|art\.?)\s*(\d+(?:[-–]\d+)?)", re.IGNORECASE)

    def extract_article_numbers(self, text: str) -> set[str]:
        """Extrait tous les numéros d'articles mentionnés dans une chaîne."""
        matches = self.ARTICLE_REGEX.findall(text)
        return {m.strip() for m in matches}

    def normalize_article_num(self, num_str: str) -> str:
        """Nettoie le préfixe 'Article' éventuel pour ne garder que le numéro."""
        cleaned = re.sub(r"^(?:article|art\.?)\s*", "", num_str.strip(), flags=re.IGNORECASE)
        return cleaned.strip()

    def validate(
        self,
        response: LegalResponseSchema,
        retrieved_article_numbers: list[str],
    ) -> GuardrailResult:
        """Vérifie que tous les articles cités font partie du contexte documentaire récupéré."""

        allowed_numbers = {self.normalize_article_num(n) for n in retrieved_article_numbers}

        # 1. Vérification des articles listés dans 'articles_cites'
        cited_in_list = {self.normalize_article_num(n) for n in response.articles_cites}

        # 2. Vérification des articles mentionnés dans l'explication textuelle
        cited_in_text = self.extract_article_numbers(response.explication_vulgarisee)

        all_cited_numbers = cited_in_list.union(cited_in_text)

        # Articles cités mais absents des sources documentaires réelles
        hallucinated = [num for num in all_cited_numbers if num not in allowed_numbers]

        if hallucinated:
            logger.warning(
                f"[GARDE-FOU VIOLÉ] Hallucination détectée ! Articles cités non sourcés: {hallucinated}. "
                f"Articles autorisés: {allowed_numbers}"
            )
            # Remplacement sécurisé par un message d'incertitude et orientation escalade
            fallback_response = LegalResponseSchema(
                statut_legal=LegalStatus.ZONE_GRISE,
                articles_cites=[],
                explication_vulgarisee=(
                    "Les dispositions spécifiques applicables à votre situation nécessitent une vérification "
                    "approfondie par un juriste. Le système ne dispose pas d'articles suffisamment précis "
                    "dans sa base pour trancher sans ambiguïté."
                ),
                conseil_pratique=(
                    "Nous vous recommandons de ne pas diffuser ce contenu tant qu'une confirmation juridique "
                    "n'a pas été obtenue, ou de solliciter l'avis d'un juriste référent."
                ),
                necessite_escalade=True,
            )
            return GuardrailResult(
                is_valid=False,
                hallucinated_articles=hallucinated,
                validated_response=fallback_response,
                rejection_reason=f"Articles non présents dans les sources officielles: {', '.join(hallucinated)}",
            )

        return GuardrailResult(
            is_valid=True,
            hallucinated_articles=[],
            validated_response=response,
            rejection_reason=None,
        )
