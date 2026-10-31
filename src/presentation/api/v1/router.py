import contextlib
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.application.use_cases.ingest_law import IngestLawUseCase
from src.core.database import get_db_session
from src.domain.entities.interaction import CitizenInteraction, LegalEscalation
from src.domain.schemas.rag import (
    CitizenFeedbackRequest,
    EscalationRequest,
    LegalQuestionRequest,
    LegalQuestionResponse,
)
from src.infrastructure.llm.gemini_client import GeminiClient
from src.infrastructure.observability.langfuse_tracer import get_langfuse_tracer
from src.infrastructure.search.hybrid_search import HybridSearchEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal", tags=["Assistant Juridique Citoyen"])


def get_ask_use_case() -> AskLegalQuestionUseCase:
    gemini_client = GeminiClient()
    search_engine = HybridSearchEngine(gemini_client=gemini_client)
    guardrail = CitationGuardrail()
    return AskLegalQuestionUseCase(
        gemini_client=gemini_client,
        search_engine=search_engine,
        guardrail=guardrail,
    )


@router.post(
    "/ask",
    response_model=LegalQuestionResponse,
    summary="Poser une question juridique sur une action envisagée",
)
async def ask_legal_question(
    request: LegalQuestionRequest,
    session: AsyncSession = Depends(get_db_session),
    use_case: AskLegalQuestionUseCase = Depends(get_ask_use_case),
) -> LegalQuestionResponse:
    """Interroge le moteur RAG officiel pour vérifier la conformité avec le Code du numérique."""
    try:
        return await use_case.execute(session=session, request=request)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors du traitement de la requête juridique : {e!s}",
        ) from e


@router.post(
    "/ask/stream",
    summary="Poser une question juridique avec réponse en flux continu (Server-Sent Events)",
)
async def ask_legal_question_stream(
    request: LegalQuestionRequest,
    session: AsyncSession = Depends(get_db_session),
    use_case: AskLegalQuestionUseCase = Depends(get_ask_use_case),
):
    """Interroge le moteur RAG et émet les étapes et tokens en temps réel via SSE."""

    async def event_generator():
        try:
            # Étape 1 : Recherche
            yield (
                "data: "
                + json.dumps({
                    "type": "status",
                    "stage": "searching",
                    "message": "Recherche dans les 646 articles du Code du numérique...",
                })
                + "\n\n"
            )

            response = await use_case.execute(session=session, request=request)

            # Étape 2 : Sources identifiées
            yield (
                "data: "
                + json.dumps({
                    "type": "sources",
                    "articles": response.articles_cites,
                    "sources": [s.model_dump() for s in response.sources],
                })
                + "\n\n"
            )

            # Étape 3 : Émission progressive du texte
            words = response.explication_vulgarisee.split(" ")
            chunk = []
            for word in words:
                chunk.append(word)
                if len(chunk) >= 5:
                    yield (
                        "data: "
                        + json.dumps({
                            "type": "token",
                            "token": " ".join(chunk) + " ",
                        })
                        + "\n\n"
                    )
                    chunk = []
            if chunk:
                yield (
                    "data: "
                    + json.dumps({
                        "type": "token",
                        "token": " ".join(chunk),
                    })
                    + "\n\n"
                )

            # Étape 4 : Événement complet
            yield (
                "data: "
                + json.dumps({
                    "type": "complete",
                    "response": response.model_dump(),
                })
                + "\n\n"
            )

        except Exception as err:
            logger.error(f"Erreur flux SSE: {err}", exc_info=True)
            yield (
                "data: "
                + json.dumps({
                    "type": "error",
                    "message": f"Erreur de traitement: {err!s}",
                })
                + "\n\n"
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/feedback",
    status_code=status.HTTP_200_OK,
    summary="Signaler une réponse incorrecte ou envoyer une note de satisfaction",
)
async def submit_feedback(
    request: CitizenFeedbackRequest,
    session: AsyncSession = Depends(get_db_session),
):
    try:
        interaction_uuid = uuid.UUID(request.interaction_id)
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="ID d'interaction invalide."
        ) from err

    interaction = await session.get(CitizenInteraction, interaction_uuid)
    if not interaction:
        raise HTTPException(status_code=404, detail="Interaction non trouvée.")

    interaction.user_feedback_rating = request.rating
    interaction.user_feedback_comment = request.comment
    await session.commit()

    tracer = get_langfuse_tracer()
    tracer.record_feedback(
        trace_id=request.interaction_id,
        rating=request.rating,
        comment=request.comment,
    )
    tracer.flush()

    return {"status": "success", "message": "Merci pour votre contribution citoyenne."}


@router.post(
    "/escalate",
    status_code=status.HTTP_201_CREATED,
    summary="Soumettre un formulaire de mise en relation avec un juriste référent",
)
async def create_escalation(
    request: EscalationRequest,
    session: AsyncSession = Depends(get_db_session),
):
    escalation = LegalEscalation(
        citizen_contact=request.citizen_contact,
        question_summary=request.question_summary,
        reason=request.reason,
        status="PENDING",
    )
    if request.interaction_id:
        try:
            escalation.interaction_id = uuid.UUID(request.interaction_id)
        except ValueError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="ID d'interaction invalide."
            ) from err

    session.add(escalation)
    await session.commit()
    await session.refresh(escalation)

    return {
        "status": "success",
        "escalation_id": str(escalation.id),
        "message": "Votre demande a été transmise à notre juriste référent.",
    }


@router.get("/faq", summary="Consulter la foire aux questions sur l'utilisation de LexBénin")
async def get_faq():
    """Renvoie les questions d'utilisation et de fonctionnement de la plateforme (style America.gov)."""
    return [
        {
            "question": "Qu'est-ce que LexBénin et quelle est sa mission ?",
            "statut_legal": "autorisé",
            "article": "Loi N° 2017-20 modifiée",
            "categorie": "Général & Mission",
            "reponse": (
                "LexBénin est un service civique d'intérêt général dédié à la vulgarisation "
                "et à la prévention juridique autour du Code du numérique béninois (Loi N° 2017-20 modifiée). "
                "Notre mission est de rendre le droit numérique compréhensible et accessible à chaque citoyen, "
                "professionnel et étudiant afin de prévenir les infractions et sécuriser leurs usages quotidiens."
            ),
            "resume": (
                "LexBénin est un service civique d'intérêt général dédié à la vulgarisation "
                "et à la prévention juridique autour du Code du numérique béninois (Loi N° 2017-20 modifiée)."
            ),
            "actionLabel": "Découvrir la mission & déontologie",
            "actionHref": "/a-propos",
        },
        {
            "question": "LexBénin est-il un service entièrement gratuit ?",
            "statut_legal": "autorisé",
            "article": "Plateforme civique",
            "categorie": "Général & Mission",
            "reponse": (
                "Oui, l'accès à LexBénin est 100 % gratuit pour tous les citoyens béninois, "
                "aussi bien sur le portail Web que sur WhatsApp. Il n'y a aucun abonnement, "
                "aucun paiement requis et aucune publicité."
            ),
            "resume": (
                "Oui, l'accès à LexBénin est 100 % gratuit pour tous les citoyens béninois, "
                "aussi bien sur le portail Web que sur WhatsApp. Zéro frais, zéro publicité."
            ),
            "actionLabel": "Interroger l'assistant sans frais",
            "actionHref": "/chat",
        },
        {
            "question": "L'assistant remplace-t-il un avocat ou un conseil juridique officiel ?",
            "statut_legal": "zone grise",
            "article": "Barreau du Bénin",
            "categorie": "Général & Mission",
            "reponse": (
                "Non. LexBénin est un outil citoyen de première orientation et d'information préventive. "
                "Ses réponses n'ont pas valeur d'avis juridique opposable ni de consultation officielle. "
                "En cas de litige avéré ou de plainte pénale, consultez un avocat ou une clinique juridique."
            ),
            "resume": (
                "Non. LexBénin informe et oriente mais ne remplace en aucun cas un avocat "
                "inscrit au Barreau du Bénin ni une consultation juridique personnalisée."
            ),
            "actionLabel": "Demander une assistance juridique",
            "actionHref": "/escalade",
        },
        {
            "question": "Comment fonctionne l'IA de LexBénin pour répondre aux questions ?",
            "statut_legal": "autorisé",
            "article": "RAG Hybride BM25 + pgvector",
            "categorie": "Fonctionnement de l'IA",
            "reponse": (
                "LexBénin repose sur une architecture RAG hybride. À chaque question, le moteur "
                "recherche simultanément dans les 646 articles du Code en combinant recherche lexicale "
                "(BM25) et recherche sémantique vectorielle (pgvector) avec synthèse vulgarisée par Gemini."
            ),
            "resume": (
                "LexBénin combine recherche par mots-clés (BM25) et sémantique (pgvector) "
                "sur les 646 articles du Code officiel avec synthèse vulgarisée par IA."
            ),
            "actionLabel": "Tester le moteur de recherche",
            "actionHref": "/chat",
        },
        {
            "question": "Comment mes données personnelles et ma vie privée sont-elles protégées (APDP) ?",
            "statut_legal": "autorisé",
            "article": "Conformité APDP",
            "categorie": "Confidentialité & APDP",
            "reponse": (
                "LexBénin applique les normes les plus strictes de l'Autorité de Protection des Données "
                "Personnelles (APDP). Vos identifiants sont pseudonymisés par empreinte SHA-256. "
                "Aucune donnée nominative n'est stockée en clair et aucun modèle public n'est entraîné."
            ),
            "resume": (
                "Conformité APDP stricte : anonymisation irréversible SHA-256, zéro revente "
                "de données et zéro entraînement public sur vos messages."
            ),
            "actionLabel": "Consulter la charte de confidentialité",
            "actionHref": "/a-propos",
        },
    ]


@router.post(
    "/admin/corpus/upload",
    summary="Charger ou mettre à jour un corpus de loi (format JSON structuré)",
    tags=["Administration Corpus"],
)
async def upload_corpus(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
):
    """Permet à un administrateur d'ingérer une nouvelle version du Code sans intervention serveur (Section 4.3 CdC)."""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Seuls les fichiers .json structurés sont acceptés pour l'ingestion.",
        )

    content = await file.read()
    tmp_path = ""
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        gemini_client = GeminiClient()
        use_case = IngestLawUseCase(gemini_client=gemini_client)
        report = await use_case.ingest_from_json(
            session=session,
            json_path=Path(tmp_path),
            compute_embeddings=False,
        )
        return {
            "status": "success",
            "code_name": report.code_name,
            "official_reference": report.official_reference,
            "total_articles": report.total_articles,
            "created_articles": report.created_articles,
            "updated_articles": report.updated_articles,
            "total_structures": report.total_structures,
            "created_structures": report.created_structures,
        }
    except Exception as e:
        logger.error(f"Erreur lors de l'ingestion du corpus: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur d'ingestion : {e!s}",
        ) from e
    finally:
        if tmp_path and os.path.exists(tmp_path):
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

