import logging
import os
import tempfile
from pathlib import Path

from google import genai
from google.genai import types

from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AudioTranscriber:
    """Service de reconnaissance vocale (ASR / STT) pour transcrire les notes vocales citoyennes."""

    def __init__(self, gemini_api_key: str | None = None):
        self.api_key = gemini_api_key or settings.GEMINI_API_KEY
        self.client: genai.Client | None = None
        if self.api_key:
            self.client = genai.Client(api_key=self.api_key)

    async def transcribe_file(self, audio_file_path: str) -> str:
        """Transcrit un fichier audio local en texte français avec ponctuation."""
        path = Path(audio_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fichier audio introuvable: {audio_file_path}")

        if not self.client:
            logger.info("Mode simulation actif pour la transcription audio.")
            return "Transcription vocale simulée: Est-ce autorisé de publier une capture d'écran sans accord ?"

        try:
            with open(audio_file_path, "rb") as f:
                audio_bytes = f.read()

            suffix = path.suffix.lower()
            mime_map = {
                ".ogg": "audio/ogg",
                ".oga": "audio/ogg",
                ".opus": "audio/ogg",
                ".mp3": "audio/mp3",
                ".wav": "audio/wav",
                ".m4a": "audio/mp4",
            }
            mime_type = mime_map.get(suffix, "audio/ogg")

            from typing import Any

            contents: Any = [
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                types.Part.from_text(
                    text=(
                        "Transcris fidèlement et intégralement cet enregistrement vocal en français. "
                        "Renvoie uniquement le texte transcrit mot à mot sans aucun commentaire."
                    )
                ),
            ]
            response = self.client.models.generate_content(
                model=settings.GEMINI_TEXT_MODEL,
                contents=contents,
            )
            transcription = response.text.strip() if response.text else ""
            logger.info(f"Transcription réussie ({len(transcription)} caractères).")
            return transcription
        except Exception as e:
            logger.error(f"Erreur lors de la transcription audio Gemini: {e}")
            raise

    async def transcribe_bytes(self, audio_bytes: bytes, suffix: str = ".ogg") -> str:
        """Transcrit des octets audio avec suppression immédiate garantie (RG-JUR7)."""
        tmp_path = ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            return await self.transcribe_file(tmp_path)
        finally:
            # RG-JUR7 : Suppression immédiate et inconditionnelle des fichiers multimédias
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                    logger.debug(f"Fichier temporaire audio supprimé: {tmp_path}")
                except OSError as err:
                    logger.warning(f"Impossible de supprimer le fichier temporaire {tmp_path}: {err}")
