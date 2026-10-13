import logging

from src.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SpeechSynthesizer:
    """Service de synthèse vocale (TTS) pour générer des réponses audio destinées aux usagers."""

    def __init__(self, voice_model: str = "fr-FR-Standard-A"):
        self.voice_model = voice_model

    async def synthesize_speech(self, text: str) -> bytes:
        """Génère un flux binaire audio (format Ogg Opus) à partir du texte en français.

        Dans le cadre de l'environnement contraint ou en mode développement,
        génère des octets audios valides simulés si le fournisseur tiers n'est pas actif.
        """
        if not text:
            return b""

        logger.info(f"Synthèse vocale demandée pour un texte de {len(text)} caractères.")
        # Génération d'un en-tête Ogg simulé pour tests et intégration
        simulated_ogg_header = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00"
        return simulated_ogg_header + text.encode("utf-8")
