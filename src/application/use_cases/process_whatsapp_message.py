import hashlib
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.core.config import get_settings
from src.domain.schemas.rag import LegalQuestionRequest
from src.infrastructure.audio.transcriber import AudioTranscriber
from src.infrastructure.vision.analyzer import VisionAnalyzer
from src.infrastructure.whatsapp.sender import WhatsAppMessageSender

logger = logging.getLogger(__name__)
settings = get_settings()


class ProcessWhatsAppMessageUseCase:
    """Cas d'usage orchestrant le traitement des messages entrants WhatsApp (Texte, Audio, Image)."""

    def __init__(
        self,
        ask_use_case: AskLegalQuestionUseCase,
        whatsapp_sender: WhatsAppMessageSender,
        transcriber: AudioTranscriber,
        vision_analyzer: VisionAnalyzer,
    ):
        self.ask_use_case = ask_use_case
        self.whatsapp_sender = whatsapp_sender
        self.transcriber = transcriber
        self.vision_analyzer = vision_analyzer

    def hash_phone_number(self, phone_number: str) -> str:
        """RG-JUR8 : Hachage SHA-256 irréversible de l'identifiant téléphonique usager."""
        return hashlib.sha256(phone_number.encode("utf-8")).hexdigest()

    async def execute(
        self,
        session: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Traite le payload entrant du webhook WhatsApp."""
        entry = payload.get("entry", [])
        if not entry:
            return {"status": "no_entry"}

        changes = entry[0].get("changes", [])
        if not changes:
            return {"status": "no_changes"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return {"status": "no_messages"}

        msg = messages[0]
        sender_phone = msg.get("from", "")
        msg_type = msg.get("type", "text")
        user_hash = self.hash_phone_number(sender_phone)

        logger.info(
            f"Message WhatsApp reçu: type={msg_type}, user_hash={user_hash[:10]}..."
        )

        question_text = ""

        # 1. Traitement selon le format du message
        if msg_type == "text":
            question_text = msg.get("text", {}).get("body", "").strip()

        elif msg_type in ("audio", "voice"):
            logger.info("Traitement d'une note vocale entrante...")
            # En environnement réel, téléchargement du média via l'URL WhatsApp Graph API
            # Ici, extraction ou simulation de flux audio
            audio_bytes = b"OggS_simulated_audio_data"
            question_text = await self.transcriber.transcribe_bytes(
                audio_bytes=audio_bytes, suffix=".ogg"
            )

        elif msg_type == "image":
            logger.info("Traitement d'une capture d'écran / image entrante...")
            image_bytes = b"JPEG_simulated_image_data"
            analysis = await self.vision_analyzer.analyze_image_bytes(
                image_bytes=image_bytes, suffix=".jpg"
            )
            question_text = analysis.get("formulated_question", "")

        elif msg_type == "interactive":
            # Réponse à un bouton CTA (ex: 'escalade_juriste')
            button_id = msg.get("interactive", {}).get("button_reply", {}).get("id", "")
            if button_id == "escalade_juriste":
                ack_text = (
                    "🏛️ Votre demande d'orientation a été prise en compte. "
                    "Un juriste référent de notre réseau vous contactera dans les meilleurs délais."
                )
                await self.whatsapp_sender.send_text_message(
                    recipient_phone=sender_phone, text=ack_text
                )
                return {"status": "escalation_acknowledged", "user_hash": user_hash}
            elif button_id == "autre_question":
                await self.whatsapp_sender.send_text_message(
                    recipient_phone=sender_phone,
                    text="Posez votre nouvelle question par écrit ou par note vocale.",
                )
                return {"status": "prompted_new_question", "user_hash": user_hash}
            question_text = "Demande d'information complémentaire."

        if not question_text:
            logger.warning("Message WhatsApp vide ou non interprétable.")
            await self.whatsapp_sender.send_text_message(
                recipient_phone=sender_phone,
                text=(
                    "Désolé, nous n'avons pas pu interpréter votre message. "
                    "Veuillez poser votre question par texte, note vocale ou capture d'écran."
                ),
            )
            return {"status": "empty_input"}

        # 2. Interrogation du moteur RAG juridique
        legal_request = LegalQuestionRequest(
            question=question_text,
            user_id=user_hash,
            channel="WHATSAPP",
        )
        legal_response = await self.ask_use_case.execute(
            session=session, request=legal_request
        )

        # 3. Envoi de la réponse structurée à l'usager
        await self.whatsapp_sender.send_legal_response(
            recipient_phone=sender_phone,
            response=legal_response,
        )

        return {
            "status": "processed",
            "interaction_id": legal_response.interaction_id,
            "statut_legal": legal_response.statut_legal.value,
            "user_hash": user_hash,
        }
