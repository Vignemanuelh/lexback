import json

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.application.use_cases.process_whatsapp_message import ProcessWhatsAppMessageUseCase
from src.core.config import get_settings
from src.core.database import async_session_factory
from src.infrastructure.audio.synthesizer import SpeechSynthesizer
from src.infrastructure.audio.transcriber import AudioTranscriber
from src.infrastructure.llm.gemini_client import GeminiClient
from src.infrastructure.search.hybrid_search import HybridSearchEngine
from src.infrastructure.vision.analyzer import VisionAnalyzer
from src.infrastructure.whatsapp.security import verify_whatsapp_signature
from src.infrastructure.whatsapp.sender import WhatsAppMessageSender

logger = structlog.get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Cloud API"])


def get_whatsapp_orchestrator() -> ProcessWhatsAppMessageUseCase:
    gemini_client = GeminiClient()
    search_engine = HybridSearchEngine(gemini_client=gemini_client)
    guardrail = CitationGuardrail()
    ask_use_case = AskLegalQuestionUseCase(
        gemini_client=gemini_client,
        search_engine=search_engine,
        guardrail=guardrail,
    )
    whatsapp_sender = WhatsAppMessageSender()
    transcriber = AudioTranscriber()
    vision_analyzer = VisionAnalyzer()
    synthesizer = SpeechSynthesizer()
    return ProcessWhatsAppMessageUseCase(
        ask_use_case=ask_use_case,
        whatsapp_sender=whatsapp_sender,
        transcriber=transcriber,
        vision_analyzer=vision_analyzer,
        synthesizer=synthesizer,
    )


async def _process_whatsapp_in_background(payload: dict):
    """Exécute le traitement en arrière-plan avec sa propre session de base de données."""
    try:
        orchestrator = get_whatsapp_orchestrator()
        async with async_session_factory() as session:
            await orchestrator.execute(session=session, payload=payload)
    except Exception as e:
        logger.error(
            "erreur_traitement_arriere_plan_whatsapp",
            exc_info=True,
            erreur=str(e),
        )


@router.get("/webhook", summary="Vérification du webhook par les serveurs de Meta")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Étape de vérification d'abonnement initiale imposée par Meta Cloud API."""
    if hub_mode == "subscribe" and hub_token == settings.WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook WhatsApp validé avec succès par Meta.")
        return PlainTextResponse(content=hub_challenge)

    logger.warning("Tentative de validation webhook avec token incorrect.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Jeton de vérification non valide.",
    )


@router.post("/webhook", summary="Réception des événements et messages usagers Meta")
async def receive_whatsapp(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Réception des messages WhatsApp avec accusé de réception immédiat (< 500ms).

    Règles d'or Meta :
    - Répondre impérativement HTTP 200 pour éviter les boucles infinies de rejeux.
    - Vérification de signature obligatoire via X-Hub-Signature-256.
    - Délégation du traitement RAG lourd aux tâches de fond (BackgroundTasks).
    """
    try:
        payload_bytes = await request.body()
        signature = request.headers.get("X-Hub-Signature-256")

        # Vérification cryptographique de la signature
        if (settings.ENVIRONMENT != "development" or signature) and not verify_whatsapp_signature(
            payload_bytes=payload_bytes,
            signature_header=signature,
            app_secret=settings.WHATSAPP_APP_SECRET,
        ):
            logger.warning("signature_invalide_rejetee")
            return {"status": "ignored"}

        payload = json.loads(payload_bytes.decode("utf-8")) if payload_bytes else {}

        # Délégation en tâche de fond pour répondre sous < 500ms à Meta
        background_tasks.add_task(_process_whatsapp_in_background, payload)

    except Exception as e:
        # « Never let an exception reach WhatsApp silently »
        logger.error("erreur_webhook_whatsapp", exc_info=True, erreur=str(e))

    return {"status": "ok"}
