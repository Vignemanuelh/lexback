import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from src.core.config import get_settings
from src.infrastructure.llm.retry import run_gemini_with_fallback

logger = logging.getLogger(__name__)
settings = get_settings()


def _parse_vision_json(raw_text: str) -> dict[str, Any]:
    """Extrait proprement le JSON retourné par Gemini Vision même s'il est encapsulé."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"extracted_text": raw_text.strip()}

    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        return parsed[0]
    if isinstance(parsed, dict):
        return parsed
    return {"extracted_text": raw_text.strip()}


class VisionAnalyzer:
    """Service d'analyse visuelle et d'OCR pour les captures d'écran et images transmises par les usagers."""

    def __init__(self, gemini_api_key: str | None = None):
        self.api_key = gemini_api_key or settings.GEMINI_API_KEY
        self.client: genai.Client | None = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    async def analyze_image_file(self, image_path: str) -> dict[str, Any]:
        """Extrait le texte et analyse le contexte d'une capture d'écran via Gemini Vision."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier image introuvable: {image_path}")

        genai_client = self.client
        if not genai_client:
            logger.info("Mode simulation actif pour l'analyse d'image.")
            return {
                "extracted_text": "Menace reçue sur WhatsApp: Envoie 100 000 FCFA ou je publie tes photos.",
                "context": "Capture d'écran de conversation de messagerie instantanée contenant une tentative d'extorsion et de chantage.",
                "contains_identifiable_person": True,
                "is_potential_ai_or_manipulated": False,
                "formulated_question": (
                    "Une personne menace de diffuser des photos intimes d'un individu en échange "
                    "d'une somme d'argent sur WhatsApp. Que prévoit la loi béninoise ?"
                ),
            }

        try:
            with open(image_path, "rb") as f:
                img_bytes = f.read()

            suffix = path.suffix.lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
            }
            mime_type = mime_map.get(suffix, "image/jpeg")

            prompt = """Tu es un module OCR et d'analyse juridique d'images pour le Code du numérique du Bénin.
Analyse cette capture d'écran ou photo :
1. Extrais fidèlement tout le texte visible dans l'image.
2. Décris brièvement le contexte (ex: conversation WhatsApp, statut Facebook, publication TikTok, SMS).
3. Détecte si l'image implique une ou plusieurs personnes identifiables (photo réelle ou capture), et évalue l'enjeu du consentement et de l'atteinte à la vie privée / droit à l'image.
4. Repère si l'image présente des indices de trucage, photomontage, caricature ou génération artificielle par IA (deepfake) de nature à constituer une usurpation d'identité, diffamation ou fausse nouvelle.
5. Formule une question juridique précise en langage naturel résumant l'action ou l'acte litigieux visible dans l'image en intégrant les risques spécifiques détectés.

Réponds sous le format JSON suivant :
{
    "extracted_text": "...",
    "context": "...",
    "contains_identifiable_person": true,
    "is_potential_ai_or_manipulated": false,
    "formulated_question": "..."
}"""

            contents: Any = [
                types.Part.from_bytes(data=img_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ]
            response, _used_model = await run_gemini_with_fallback(
                lambda model_name: genai_client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    ),
                ),
                models=settings.get_text_model_candidates(),
                cooldown_seconds=settings.GEMINI_MODEL_COOLDOWN_SECONDS,
            )
            text_resp = response.text or "{}"
            data = _parse_vision_json(text_resp)
            return {
                "extracted_text": data.get("extracted_text", ""),
                "context": data.get("context", ""),
                "contains_identifiable_person": bool(data.get("contains_identifiable_person", False)),
                "is_potential_ai_or_manipulated": bool(data.get("is_potential_ai_or_manipulated", False)),
                "formulated_question": data.get(
                    "formulated_question",
                    data.get("extracted_text", "Capture d'écran soumise pour avis juridique."),
                ),
            }
        except Exception as e:
            logger.error(f"Erreur lors de l'analyse d'image Gemini Vision: {e}")
            raise

    async def analyze_image_bytes(self, image_bytes: bytes, suffix: str = ".jpg") -> dict[str, Any]:
        """Analyse des octets d'image avec suppression immédiate garantie (RG-JUR7)."""
        tmp_path = ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        try:
            return await self.analyze_image_file(tmp_path)
        finally:
            # RG-JUR7 : Suppression immédiate et inconditionnelle des fichiers temporaires
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                    logger.debug(f"Fichier temporaire image supprimé: {tmp_path}")
                except OSError as err:
                    logger.warning(f"Impossible de supprimer le fichier image temporaire {tmp_path}: {err}")
