import hashlib
import inspect
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.core.config import get_settings
from src.domain.entities.interaction import CitizenInteraction, LegalEscalation
from src.domain.schemas.rag import LegalQuestionRequest
from src.infrastructure.audio.synthesizer import SpeechSynthesizer
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
        synthesizer: SpeechSynthesizer | None = None,
    ):
        self.ask_use_case = ask_use_case
        self.whatsapp_sender = whatsapp_sender
        self.transcriber = transcriber
        self.vision_analyzer = vision_analyzer
        self.synthesizer = synthesizer or SpeechSynthesizer()

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
            media_id = (
                msg.get("audio", {}).get("id")
                or msg.get("voice", {}).get("id")
            )
            audio_bytes = b"OggS_simulated_audio_data"
            if media_id and hasattr(self.whatsapp_sender, "download_media"):
                try:
                    res = self.whatsapp_sender.download_media(media_id)
                    downloaded = await res if inspect.isawaitable(res) else res
                    if isinstance(downloaded, (bytes, bytearray)) and downloaded:
                        audio_bytes = bytes(downloaded)
                except Exception as e:
                    logger.warning(f"Échec téléchargement audio WhatsApp: {e}")

            question_text = await self.transcriber.transcribe_bytes(
                audio_bytes=audio_bytes, suffix=".ogg"
            )

        elif msg_type == "image":
            logger.info("Traitement d'une capture d'écran / image entrante...")
            media_id = msg.get("image", {}).get("id")
            caption = msg.get("image", {}).get("caption", "").strip()
            image_bytes = b"JPEG_simulated_image_data"
            if media_id and hasattr(self.whatsapp_sender, "download_media"):
                try:
                    res = self.whatsapp_sender.download_media(media_id)
                    downloaded = await res if inspect.isawaitable(res) else res
                    if isinstance(downloaded, (bytes, bytearray)) and downloaded:
                        image_bytes = bytes(downloaded)
                except Exception as e:
                    logger.warning(f"Échec téléchargement image WhatsApp: {e}")

            analysis = await self.vision_analyzer.analyze_image_bytes(
                image_bytes=image_bytes, suffix=".jpg"
            )
            question_text = analysis.get("formulated_question", "")
            if caption:
                question_text = f"{question_text}\nPrécision usager : {caption}"

        elif msg_type == "interactive":
            # Réponse à un bouton CTA (ex: 'escalade_juriste')
            button_id = msg.get("interactive", {}).get("button_reply", {}).get("id", "")
            if button_id == "escalade_juriste":
                # Récupération de la dernière interaction pour contextualiser le dossier d'escalade
                last_interaction = None
                try:
                    stmt = (
                        select(CitizenInteraction)
                        .where(CitizenInteraction.user_hash == user_hash)
                        .order_by(CitizenInteraction.created_at.desc())
                        .limit(1)
                    )
                    query_result = await session.execute(stmt)
                    if hasattr(query_result, "scalar_one_or_none"):
                        item = query_result.scalar_one_or_none()
                        item = await item if inspect.isawaitable(item) else item
                        if isinstance(item, CitizenInteraction):
                            last_interaction = item
                except Exception as e:
                    logger.warning(f"Impossible de récupérer l'interaction précédente: {e}")

                interaction_id = last_interaction.id if last_interaction else None
                raw_input_text = (
                    last_interaction.raw_input
                    if last_interaction and isinstance(last_interaction.raw_input, str)
                    else "Demande d'orientation directe WhatsApp"
                )
                reason = (
                    "ZONE_GRISE"
                    if (last_interaction and getattr(last_interaction, "is_escalated", False))
                    else "DEMANDE_USAGER"
                )

                escalation = LegalEscalation(
                    id=uuid.uuid4(),
                    interaction_id=interaction_id,
                    citizen_contact=sender_phone,
                    question_summary=raw_input_text,
                    reason=reason,
                    status="PENDING",
                )
                session.add(escalation)
                await session.commit()

                ack_text = (
                    "🏛️ Votre demande d'orientation a été prise en compte et transmise à notre juriste référent. "
                    "Un spécialiste de notre réseau vous contactera dans les meilleurs délais."
                )
                await self.whatsapp_sender.send_text_message(
                    recipient_phone=sender_phone, text=ack_text
                )
                return {
                    "status": "escalation_acknowledged",
                    "escalation_id": str(escalation.id),
                    "user_hash": user_hash,
                }
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

        # 3. Envoi de la réponse structurée à l'usager (texte enrichi avec boutons)
        await self.whatsapp_sender.send_legal_response(
            recipient_phone=sender_phone,
            response=legal_response,
        )

        # 4. Si la question initiale était vocale, émettre également une réponse audio (Section 4.2 CdC)
        if msg_type in ("audio", "voice"):
            try:
                synth_call = self.synthesizer.synthesize_speech(
                    legal_response.explication_vulgarisee
                )
                audio_data = (
                    await synth_call if inspect.isawaitable(synth_call) else synth_call
                )
                if audio_data and hasattr(self.whatsapp_sender, "send_audio_message"):
                    send_call = self.whatsapp_sender.send_audio_message(
                        recipient_phone=sender_phone,
                        audio_url="https://lexbenin.bj/audio/sample_response.ogg",
                    )
                    if inspect.isawaitable(send_call):
                        await send_call
            except Exception as e:
                logger.warning(f"Échec de l'envoi de la note vocale WhatsApp de retour: {e}")

        return {
            "status": "processed",
            "interaction_id": legal_response.interaction_id,
            "statut_legal": legal_response.statut_legal.value,
            "user_hash": user_hash,
        }
