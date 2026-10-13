import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.application.use_cases.ask_legal_question import AskLegalQuestionUseCase
from src.core.database import get_db_session
from src.domain.entities.interaction import CitizenInteraction, LegalEscalation
from src.domain.schemas.rag import (
    CitizenFeedbackRequest,
    EscalationRequest,
    LegalQuestionRequest,
    LegalQuestionResponse,
)
from src.infrastructure.llm.gemini_client import GeminiClient
from src.infrastructure.search.hybrid_search import HybridSearchEngine

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


@router.get("/faq", summary="Consulter la foire aux questions pré-validées")
async def get_faq():
    """Renvoie les questions courantes pré-validées par le juriste référent."""
    return [
        {
            "question": "Puis-je publier la photo d'une personne sans son accord préalable ?",
            "statut_legal": "interdit",
            "article": "Article 552",
            "resume": (
                "La captation, l'enregistrement ou la diffusion de l'image d'une personne "
                "dans un lieu privé ou public sans son consentement exprès est punie par la loi."
            ),
        },
        {
            "question": (
                "Est-ce une infraction de créer un faux profil sur les réseaux sociaux "
                "sous le nom d'un camarade ?"
            ),
            "statut_legal": "interdit",
            "article": "Article 558",
            "resume": (
                "L'usurpation d'identité numérique et l'utilisation de données permettant "
                "d'identifier un tiers dans le but de troubler sa tranquillité constituent un délit."
            ),
        },
        {
            "question": (
                "Que risque-t-on en partageant une information non vérifiée (fake news) "
                "qui porte atteinte à une entreprise ou un individu ?"
            ),
            "statut_legal": "interdit",
            "article": "Article 550",
            "resume": (
                "La publication ou le partage de fausses nouvelles de nature à troubler la paix "
                "publique ou à porter atteinte à l'honneur d'autrui est sévèrement sanctionné."
            ),
        },
    ]
