import logging
from typing import Optional
from google import genai
from google.genai import types

from src.core.config import get_settings
from src.domain.schemas.rag import LegalResponseSchema

logger = logging.getLogger(__name__)
settings = get_settings()


class GeminiClient:
    """Client d'intégration officiel Google GenAI pour Gemini 2.0 et embeddings."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            self.client = None
            logger.warning("GEMINI_API_KEY non configurée. Le client Gemini fonctionnera en mode simulation.")

    async def get_embedding(self, text: str) -> list[float]:
        """Génère l'embedding vectoriel dense pour un fragment de texte."""
        if not self.client:
            # Mode fallback / test (vecteur unitaire dimension 768)
            return [0.0] * settings.EMBEDDING_DIMENSION

        try:
            response = self.client.models.embed_content(
                model=settings.GEMINI_EMBEDDING_MODEL,
                contents=text,
            )
            # Récupère les valeurs du premier embedding
            if hasattr(response, "embeddings") and response.embeddings:
                return response.embeddings[0].values
            elif hasattr(response, "embedding") and response.embedding:
                return response.embedding.values
            return [0.0] * settings.EMBEDDING_DIMENSION
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'embedding Gemini: {e}")
            raise

    async def generate_legal_response(
        self, prompt: str, system_instruction: str
    ) -> LegalResponseSchema:
        """Génère une réponse juridique structurée et typée via Gemini Structured Outputs."""
        if not self.client:
            raise RuntimeError("GEMINI_API_KEY requise pour la génération de réponses.")

        config = types.GenerateContentConfig(
            temperature=0.1,  # Température minimale pour un déterminisme maximal
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=LegalResponseSchema,
        )

        response = self.client.models.generate_content(
            model=settings.GEMINI_TEXT_MODEL,
            contents=prompt,
            config=config,
        )

        # Parse et valide via Pydantic
        return LegalResponseSchema.model_validate_json(response.text)
