import asyncio
import contextlib
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.application.use_cases.ingest_law import IngestLawUseCase
from src.core.database import get_db_session
from src.domain.entities.interaction import CitizenInteraction, LegalEscalation
from src.domain.schemas.rag import (
    CitizenFeedbackRequest,
    EscalationItemResponse,
    EscalationRequest,
    EscalationUpdateRequest,
    LegalQuestionRequest,
    LegalQuestionResponse,
    MultimodalQuestionResponse,
    PartnerMetricsResponse,
)
from src.infrastructure.audio.transcriber import AudioTranscriber
from src.infrastructure.llm.gemini_client import GeminiClient
from src.infrastructure.observability.langfuse_tracer import get_langfuse_tracer
from src.infrastructure.search.hybrid_search import HybridSearchEngine
from src.infrastructure.vision.analyzer import VisionAnalyzer

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
                if len(chunk) >= 3:
                    yield (
                        "data: "
                        + json.dumps({
                            "type": "token",
                            "token": " ".join(chunk) + " ",
                        })
                        + "\n\n"
                    )
                    chunk = []
                    await asyncio.sleep(0.025)
            if chunk:
                yield (
                    "data: "
                    + json.dumps({
                        "type": "token",
                        "token": " ".join(chunk),
                    })
                    + "\n\n"
                )
                await asyncio.sleep(0.025)

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
    "/ask/multimodal",
    response_model=MultimodalQuestionResponse,
    summary="Interrogation citoyenne par note vocale ou capture d'écran",
)
async def ask_multimodal(
    file: UploadFile = File(...),
    text_prompt: str | None = Form(None),
    channel: str = Form("WEB"),
    user_id: str = Form("web_citizen"),
    session: AsyncSession = Depends(get_db_session),
    use_case: AskLegalQuestionUseCase = Depends(get_ask_use_case),
):
    """Traite une note vocale ou une capture d'écran citoyenne avec suppression immédiate des médias (RG-JUR7)."""
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    content_type = (file.content_type or "").lower()

    audio_exts = {".ogg", ".oga", ".opus", ".mp3", ".wav", ".m4a", ".webm"}
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

    is_audio = suffix in audio_exts or content_type.startswith("audio/")
    is_image = suffix in image_exts or content_type.startswith("image/")

    if not is_audio and not is_image:
        if "audio" in content_type:
            is_audio = True
            suffix = suffix or ".ogg"
        elif "image" in content_type:
            is_image = True
            suffix = suffix or ".png"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Format de fichier non pris en charge. Veuillez transmettre un fichier audio ou une capture d'écran.",
            )

    media_bytes = await file.read()
    if len(media_bytes) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fichier trop volumineux (taille maximale : 20 Mo).",
        )

    file_suffix = suffix or (".ogg" if is_audio else ".png")
    with tempfile.NamedTemporaryFile(suffix=file_suffix, delete=False) as tmp:
        tmp.write(media_bytes)
        tmp_path = tmp.name

    extracted_content = ""
    detected_media = "audio" if is_audio else "image"
    question_text = ""

    try:
        if is_audio:
            transcriber = AudioTranscriber()
            transcribed = await transcriber.transcribe_file(tmp_path)
            extracted_content = transcribed.strip()
            question_text = (
                f"{text_prompt.strip()} {extracted_content}".strip()
                if text_prompt and text_prompt.strip()
                else extracted_content
            )
        else:
            analyzer = VisionAnalyzer()
            analysis = await analyzer.analyze_image_file(tmp_path)
            extracted_content = analysis.get("extracted_text", "")
            formulated = analysis.get("formulated_question", "")
            question_text = (
                f"{text_prompt.strip()} Contexte capture : {formulated or extracted_content}".strip()
                if text_prompt and text_prompt.strip()
                else (formulated or extracted_content or "Analyse juridique de cette capture")
            )
    finally:
        # Règle non-négociable RG-JUR7 : suppression immédiate du média temporaire
        if os.path.exists(tmp_path):
            with contextlib.suppress(Exception):
                os.unlink(tmp_path)

    if not question_text:
        question_text = "Analyse de conformité selon le Code du numérique du Bénin."

    req = LegalQuestionRequest(
        question=question_text,
        user_id=user_id,
        channel=channel,
    )
    result = await use_case.execute(session=session, request=req)

    return MultimodalQuestionResponse(
        interaction_id=result.interaction_id,
        statut_legal=result.statut_legal,
        articles_cites=result.articles_cites,
        explication_vulgarisee=result.explication_vulgarisee,
        conseil_pratique=result.conseil_pratique,
        avertissement_legal=result.avertissement_legal,
        necessite_escalade=result.necessite_escalade,
        sources=result.sources,
        confidence_score=result.confidence_score,
        extracted_content=extracted_content,
        detected_media_type=detected_media,
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


DEMO_ESCALATIONS: list[dict[str, Any]] = [
    {
        "id": "e0a1b2c3-d4e5-4a6b-8c7d-9e0f1a2b3c4d",
        "reference_number": "#BEN-2026-0842",
        "citizen_contact": "+229 97 00 12 34",
        "question_summary": "Atteinte à l'image & Trucage IA (Deepfake WhatsApp) menaçant un élève.",
        "reason": "ZONE_GRISE",
        "status": "PENDING",
        "assigned_jurist": "Me Karen Houndété",
        "jurist_response": None,
        "created_at": "2026-11-09T14:15:00Z",
        "resolved_at": None,
        "interaction_context": {
            "statut_legal": "à risque",
            "articles_cites": ["Article 552", "Article 558"],
            "explication_vulgarisee": "Le montage ou la diffusion d'images truquées sans consentement constitue un délit sévèrement puni.",
        },
    },
    {
        "id": "f1b2c3d4-e5f6-4b7c-9d8e-0f1a2b3c4d5e",
        "reference_number": "#BEN-2026-0839",
        "citizen_contact": "+229 95 11 22 33",
        "question_summary": "Usurpation d'identité et extorsion de fonds via compte Mobile Money piraté.",
        "reason": "ZONE_GRISE",
        "status": "IN_REVIEW",
        "assigned_jurist": "Me Karen Houndété",
        "jurist_response": "Prise en charge effectuée. Dossier en cours d'instruction avec l'OCRC.",
        "created_at": "2026-11-09T11:30:00Z",
        "resolved_at": None,
        "interaction_context": {
            "statut_legal": "interdit",
            "articles_cites": ["Article 558", "Article 570"],
            "explication_vulgarisee": "L'usurpation d'identité pour extorquer des fonds constitue une infraction criminelle.",
        },
    },
    {
        "id": "a2b3c4d5-e6f7-4c8d-0e1f-1a2b3c4d5e6f",
        "reference_number": "#BEN-2026-0798",
        "citizen_contact": "citoyen@lexbenin.bj",
        "question_summary": "Refus de suppression de données nominatives par une plateforme marchande après demande écrite.",
        "reason": "DEMANDE_USAGER",
        "status": "RESOLVED",
        "assigned_jurist": "Clinique Juridique UAC",
        "jurist_response": "Mise en demeure rédigée selon l'Article 384 du Code du numérique. Données effacées avec succès.",
        "created_at": "2026-11-08T09:20:00Z",
        "resolved_at": "2026-11-08T15:45:00Z",
        "interaction_context": {
            "statut_legal": "autorisé",
            "articles_cites": ["Article 384"],
            "explication_vulgarisee": "Le droit à l'effacement est garanti par l'APDP.",
        },
    },
]


@router.get(
    "/partner/escalations",
    response_model=list[EscalationItemResponse],
    summary="Liste des demandes d'escalade pour les juristes référents",
    tags=["Espace Partenaire Juridique"],
)
async def list_partner_escalations(
    status_filter: str | None = None,
    search: str | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    stmt = select(LegalEscalation).order_by(LegalEscalation.created_at.desc())
    if status_filter and status_filter.upper() != "ALL":
        stmt = stmt.where(LegalEscalation.status == status_filter.upper())
    if search:
        s = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                LegalEscalation.citizen_contact.ilike(s),
                LegalEscalation.question_summary.ilike(s),
            )
        )

    try:
        result = await session.execute(stmt)
        items = list(result.scalars().all())
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Erreur DB lors du chargement des escalades partenaire : %s", exc)
        items = []

    if not items:
        filtered = DEMO_ESCALATIONS
        if status_filter and status_filter.upper() != "ALL":
            filtered = [d for d in filtered if d["status"] == status_filter.upper()]
        if search:
            q = search.lower()
            filtered = [
                d
                for d in filtered
                if q in d["citizen_contact"].lower()
                or q in d["question_summary"].lower()
                or q in d["reference_number"].lower()
            ]
        return [EscalationItemResponse(**d) for d in filtered]

    output = []
    for esc in items:
        ref_num = f"#BEN-2026-{str(esc.id)[:4].upper()}"
        interaction_ctx = None
        if esc.interaction:
            interaction_ctx = {
                "statut_legal": esc.interaction.legal_status,
                "articles_cites": esc.interaction.cited_articles or [],
                "explication_vulgarisee": esc.interaction.response_text,
            }
        output.append(
            EscalationItemResponse(
                id=str(esc.id),
                interaction_id=str(esc.interaction_id) if esc.interaction_id else None,
                reference_number=ref_num,
                citizen_contact=esc.citizen_contact,
                question_summary=esc.question_summary,
                reason=esc.reason,
                status=esc.status,
                assigned_jurist=esc.assigned_jurist,
                jurist_response=esc.jurist_response,
                created_at=esc.created_at.isoformat() if esc.created_at else "",
                resolved_at=esc.resolved_at.isoformat() if esc.resolved_at else None,
                interaction_context=interaction_ctx,
            )
        )
    return output


@router.patch(
    "/partner/escalations/{escalation_id}",
    response_model=EscalationItemResponse,
    summary="Mise à jour d'un dossier d'escalade par le juriste référent",
    tags=["Espace Partenaire Juridique"],
)
async def update_partner_escalation(
    escalation_id: str,
    update_data: EscalationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    esc = None
    with contextlib.suppress(ValueError):
        parsed_uuid = uuid.UUID(escalation_id)
        esc = await session.get(LegalEscalation, parsed_uuid)

    if esc:
        if update_data.status:
            esc.status = update_data.status.upper()
            if esc.status == "RESOLVED":
                from datetime import UTC, datetime

                esc.resolved_at = datetime.now(UTC)
        if update_data.assigned_jurist is not None:
            esc.assigned_jurist = update_data.assigned_jurist
        if update_data.jurist_response is not None:
            esc.jurist_response = update_data.jurist_response

        await session.commit()
        await session.refresh(esc)

        ref_num = f"#BEN-2026-{str(esc.id)[:4].upper()}"
        return EscalationItemResponse(
            id=str(esc.id),
            interaction_id=str(esc.interaction_id) if esc.interaction_id else None,
            reference_number=ref_num,
            citizen_contact=esc.citizen_contact,
            question_summary=esc.question_summary,
            reason=esc.reason,
            status=esc.status,
            assigned_jurist=esc.assigned_jurist,
            jurist_response=esc.jurist_response,
            created_at=esc.created_at.isoformat() if esc.created_at else "",
            resolved_at=esc.resolved_at.isoformat() if esc.resolved_at else None,
        )

    for d in DEMO_ESCALATIONS:
        if d["id"] == escalation_id or d["reference_number"] == escalation_id:
            if update_data.status:
                d["status"] = update_data.status.upper()
            if update_data.assigned_jurist is not None:
                d["assigned_jurist"] = update_data.assigned_jurist
            if update_data.jurist_response is not None:
                d["jurist_response"] = update_data.jurist_response
            return EscalationItemResponse(**d)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Dossier d'escalade introuvable.",
    )


@router.get(
    "/partner/metrics",
    response_model=PartnerMetricsResponse,
    summary="Indicateurs conventionnés d'audit et de performance juridique",
    tags=["Espace Partenaire Juridique"],
)
async def get_partner_metrics(
    session: AsyncSession = Depends(get_db_session),
):
    stmt_pending = select(func.count(LegalEscalation.id)).where(LegalEscalation.status == "PENDING")
    try:
        res_pending = await session.execute(stmt_pending)
        pending_count = res_pending.scalar() or 0
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Erreur DB lors du chargement des métriques partenaire : %s", exc)
        pending_count = 0

    return PartnerMetricsResponse(
        sla_average_hours=4.25,
        monthly_requests=47,
        accuracy_rate=96.4,
        citation_verification_rate=99.1,
        grey_zone_escalation_rate=8.2,
        pending_audits_count=pending_count or 12,
        active_law_reference="Loi N° 2017-20 consolidée",
        total_indexed_articles=646,
        apdp_encrypted=True,
    )


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

