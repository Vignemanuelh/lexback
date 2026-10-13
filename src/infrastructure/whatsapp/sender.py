import logging
from typing import Any

import httpx

from src.core.config import get_settings
from src.domain.schemas.rag import LegalQuestionResponse, LegalStatus

logger = logging.getLogger(__name__)
settings = get_settings()


STATUS_EMOJIS: dict[LegalStatus, str] = {
    LegalStatus.AUTORISE: "✅ AUTORISÉ",
    LegalStatus.INTERDIT: "🚫 STRICTEMENT INTERDIT",
    LegalStatus.A_RISQUE: "⚠️ ACTION À RISQUE",
    LegalStatus.ZONE_GRISE: "⚖️ ZONE GRISE (AVIS JURIDIQUE RECOMMANDÉ)",
}


class WhatsAppMessageSender:
    """Service d'expédition de messages via l'API Meta WhatsApp Cloud Graph."""

    def __init__(
        self,
        access_token: str | None = None,
        phone_number_id: str | None = None,
        api_version: str | None = None,
        base_url: str | None = None,
    ):
        self.access_token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        self.api_version = api_version or settings.WHATSAPP_API_VERSION
        self.base_url = base_url or settings.WHATSAPP_API_BASE_URL

    @property
    def messages_endpoint(self) -> str:
        return f"{self.base_url}/{self.api_version}/{self.phone_number_id}/messages"

    def format_legal_message(self, response: LegalQuestionResponse) -> str:
        """Formate la réponse juridique sous forme de message WhatsApp pédagogique et structuré."""
        status_label = STATUS_EMOJIS.get(response.statut_legal, response.statut_legal.value.upper())
        articles_str = (
            ", ".join(response.articles_cites) if response.articles_cites else "Aucun article direct"
        )

        message_parts = [
            "🏛️ *LEXBENIN — Assistant Numérique Citoyen*\n",
            f"*Qualification juridique :* {status_label}",
            f"*Articles applicables :* {articles_str}\n",
            f"📖 *Explication en langage clair :*\n{response.explication_vulgarisee}\n",
            f"💡 *Conseil pratique pour agir en règle :*\n{response.conseil_pratique}\n",
        ]

        if response.necessite_escalade:
            message_parts.append(
                "⚖️ *Attention :* Votre situation présente des incertitudes ou des complexités. "
                "Nous vous recommandons de demander l'avis d'un juriste spécialisé.\n"
            )

        message_parts.append(f"ℹ️ _{response.avertissement_legal}_")
        return "\n".join(message_parts)

    async def send_text_message(self, recipient_phone: str, text: str) -> dict[str, Any]:
        """Envoie un message texte simple à un numéro d'usager."""
        if not self.access_token or not self.phone_number_id:
            logger.warning(
                "Configuration WhatsApp incomplète (token ou phone_id manquant). Mode simulation actif."
            )
            return {"status": "simulated", "recipient": recipient_phone, "text": text}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(self.messages_endpoint, json=payload, headers=headers)
                res.raise_for_status()
                return res.json()
        except Exception as e:
            logger.error(f"Échec de l'envoi WhatsApp vers {recipient_phone}: {e}")
            raise

    async def send_legal_response(
        self,
        recipient_phone: str,
        response: LegalQuestionResponse,
    ) -> dict[str, Any]:
        """Envoie une réponse juridique complète formatée avec boutons d'action interactive."""
        formatted_text = self.format_legal_message(response)

        # Si le canal WhatsApp est configuré et que l'usager a besoin d'escalade
        buttons = []
        if response.necessite_escalade:
            buttons.append({"id": "escalade_juriste", "title": "Parler à un juriste"})
        buttons.append({"id": "autre_question", "title": "Autre question"})

        if self.access_token and self.phone_number_id and len(buttons) <= 3:
            try:
                return await self.send_interactive_buttons(
                    recipient_phone=recipient_phone,
                    body_text=formatted_text,
                    buttons=buttons,
                )
            except Exception as e:
                logger.warning(f"Repli sur message texte simple après erreur boutons: {e}")

        return await self.send_text_message(recipient_phone=recipient_phone, text=formatted_text)

    async def send_interactive_buttons(
        self,
        recipient_phone: str,
        body_text: str,
        buttons: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Envoie un message avec boutons de réponse rapide (CTA)."""
        if not self.access_token or not self.phone_number_id:
            return {"status": "simulated", "recipient": recipient_phone, "buttons": buttons}

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        action_buttons = [
            {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
            for b in buttons[:3]
        ]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text[:1024]},
                "action": {"buttons": action_buttons},
            },
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(self.messages_endpoint, json=payload, headers=headers)
            res.raise_for_status()
            return res.json()
