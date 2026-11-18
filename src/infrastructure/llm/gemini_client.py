import logging

from google import genai
from google.genai import types

from src.core.config import get_settings
from src.domain.schemas.rag import LegalResponseSchema
from src.infrastructure.llm.retry import run_gemini_with_fallback, run_gemini_with_retry

logger = logging.getLogger(__name__)
settings = get_settings()


class GeminiClient:
    """Client d'intégration officiel Google GenAI pour Gemini et embeddings."""

    last_used_model: str | None = None

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.client: genai.Client | None = None
        self.last_used_model = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning(
                "GEMINI_API_KEY non configurée. Le client Gemini fonctionnera en mode simulation."
            )

    async def get_embedding(self, text: str) -> list[float]:
        """Génère l'embedding vectoriel dense pour un fragment de texte."""
        genai_client = self.client
        if not genai_client:
            # Mode fallback / test (vecteur unitaire dimension 768)
            return [0.0] * settings.EMBEDDING_DIMENSION

        try:
            response = await run_gemini_with_retry(
                lambda: genai_client.models.embed_content(
                    model=settings.GEMINI_EMBEDDING_MODEL,
                    contents=text,
                    config=types.EmbedContentConfig(
                        output_dimensionality=settings.EMBEDDING_DIMENSION,
                    ),
                )
            )
            # Récupère les valeurs du premier embedding
            if hasattr(response, "embeddings") and response.embeddings:
                vals = response.embeddings[0].values
                if vals is not None:
                    return list(vals)
            elif hasattr(response, "embedding") and response.embedding:
                vals = response.embedding.values
                if vals is not None:
                    return list(vals)
            return [0.0] * settings.EMBEDDING_DIMENSION
        except Exception as e:
            logger.error(f"Erreur lors de la génération de l'embedding Gemini: {e}")
            raise

    async def generate_legal_response(
        self, prompt: str, system_instruction: str
    ) -> LegalResponseSchema:
        """Génère une réponse juridique structurée avec bascule multi-modèles sur quota/saturation."""
        genai_client = self.client
        if not genai_client:
            raise RuntimeError("GEMINI_API_KEY requise pour la génération de réponses.")

        config = types.GenerateContentConfig(
            temperature=0.1,  # Température minimale pour un déterminisme maximal
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=LegalResponseSchema,
        )

        response, used_model = await run_gemini_with_fallback(
            lambda model_name: genai_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            ),
            models=settings.get_text_model_candidates(),
            cooldown_seconds=settings.GEMINI_MODEL_COOLDOWN_SECONDS,
        )
        self.last_used_model = used_model

        # Parse et valide via Pydantic
        content_text = response.text or "{}"
        return LegalResponseSchema.model_validate_json(content_text)
