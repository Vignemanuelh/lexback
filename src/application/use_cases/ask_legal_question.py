import hashlib
import logging

from langfuse import observe
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.guardrails.citation_guardrail import CitationGuardrail
from src.core.config import get_settings
from src.domain.entities.interaction import CitizenInteraction
from src.domain.schemas.rag import (
    LegalArticleCitation,
    LegalQuestionRequest,
    LegalQuestionResponse,
    LegalResponseSchema,
    LegalStatus,
)
from src.infrastructure.llm.gemini_client import GeminiClient
from src.infrastructure.observability.langfuse_tracer import LangfuseTracer, get_langfuse_tracer
from src.infrastructure.search.hybrid_search import HybridSearchEngine

logger = logging.getLogger(__name__)
settings = get_settings()


SYSTEM_INSTRUCTION = """Tu es LEXBENIN, l'assistant juridique d'information citoyenne sur le Code du numérique du Bénin.
Ton rôle est de vulgariser le droit auprès des citoyens pour prévenir les infractions numériques (diffamation, atteinte à la vie privée, usurpation, cyberharcèlement, fake news).

RÈGLES D'OR DE COMPORTEMENT :
1. VÉRITÉ TERRAIN ABSOLUE : Tu dois répondre STRICTEMENT et EXCLUSIVEMENT à partir des extraits d'articles fournis dans le contexte ci-dessous. Tu n'inventes AUCUN article et n'extrapoles AUCUNE règle.
2. CITATION EXACTE : Tu ne dois mentionner que des articles effectivement présents dans les extraits ci-dessous.
3. STATUT CLAIR : Tu dois qualifier l'action selon un des statuts suivants : 'autorisé', 'interdit', 'à risque', ou 'zone grise'.
4. ZONE GRISE & ABSENCE : Si la question ne trouve pas de réponse claire ou si aucun article fourni ne couvre la situation, déclare le statut 'zone grise', explique poliment l'ambiguïté et active 'necessite_escalade=true'.
5. LANGAGE CITOYEN : Exprime-toi dans un français simple, bienveillant, clair et pédagogique, sans jargon juridique excessif.
6. AVERTISSEMENT : Rappelle toujours que l'outil est informatif et ne remplace pas l'avis d'un avocat.
"""


class AskLegalQuestionUseCase:
    """Cas d'usage principal orchestrant la recherche hybride, Gemini, les garde-fous et Langfuse."""

    def __init__(
        self,
        gemini_client: GeminiClient,
        search_engine: HybridSearchEngine,
        guardrail: CitationGuardrail,
        tracer: LangfuseTracer | None = None,
    ):
        self.gemini_client = gemini_client
        self.search_engine = search_engine
        self.guardrail = guardrail
        self.tracer = tracer or get_langfuse_tracer()

    def _hash_user_id(self, user_id: str | None) -> str:
        if not user_id:
            return "anonymous"
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    @observe(name="ask_legal_question")
    async def execute(
        self,
        session: AsyncSession,
        request: LegalQuestionRequest,
    ) -> LegalQuestionResponse:
        """Exécute l'orchestration de bout en bout."""

        # 1. Recherche documentaire hybride
        search_span = self.tracer.start_span(
            trace_id="",
            name="hybrid_search",
            span_type="retriever",
            inputs={"query": request.question, "top_k": 4},
        )
        search_results = await self.search_engine.search(
            session=session,
            query=request.question,
            top_k=4,
        )
        self.tracer.end_span(
            search_span,
            outputs={"retrieved_count": len(search_results)},
        )

        sources: list[LegalArticleCitation] = []
        retrieved_article_numbers: list[str] = []
        context_blocks: list[str] = []

        for res in search_results:
            art = res.article
            structure_title = res.structure.title if res.structure else ""
            retrieved_article_numbers.append(art.article_number)

            sources.append(
                LegalArticleCitation(
                    article_number=f"Article {art.article_number}",
                    structure_title=structure_title,
                    content=art.full_content,
                    relevance_score=res.rrf_score,
                )
            )

            context_blocks.append(
                f"[ARTICLE {art.article_number}] {structure_title}\n{art.full_content}"
            )

        # 2. Vérification si des documents pertinents ont été récupérés
        if not context_blocks:
            # Aucun article trouvé -> Escalade directe sans appel LLM halluciné
            schema_resp = LegalResponseSchema(
                statut_legal=LegalStatus.ZONE_GRISE,
                articles_cites=[],
                explication_vulgarisee=(
                    "Le Code du numérique ne semble pas comporter de disposition directe "
                    "relative à cette situation particulière."
                ),
                conseil_pratique=(
                    "En cas de doute, abstenez-vous de poser cet acte en ligne "
                    "et consultez un professionnel du droit."
                ),
                necessite_escalade=True,
            )
            is_valid = True
        else:
            context_text = "\n\n---\n\n".join(context_blocks)
            prompt = f"""QUESTION DU CITOYEN :
{request.question}

DOCUMENTS JURIDIQUES OFFICIELS EXTRAITS :
{context_text}

Rédige ta réponse structurée en respectant scrupuleusement les règles et le format JSON requis.
"""
            # 3. Génération structurée via Gemini
            gen_span = self.tracer.start_span(
                trace_id="",
                name="gemini_generation",
                span_type="generation",
                inputs={"prompt_length": len(prompt)},
                metadata={"model": settings.GEMINI_TEXT_MODEL},
            )
            raw_llm_response = await self.gemini_client.generate_legal_response(
                prompt=prompt,
                system_instruction=SYSTEM_INSTRUCTION,
            )
            used_model = getattr(self.gemini_client, "last_used_model", None) or settings.GEMINI_TEXT_MODEL
            self.tracer.end_span(
                gen_span,
                outputs={
                    "statut": raw_llm_response.statut_legal.value,
                    "model": used_model,
                },
            )

            # 4. Garde-fou anti-hallucination déterministe
            guard_span = self.tracer.start_span(
                trace_id="",
                name="citation_guardrail",
                span_type="guardrail",
                inputs={"retrieved": retrieved_article_numbers},
            )
            guard_check = self.guardrail.validate(
                response=raw_llm_response,
                retrieved_article_numbers=retrieved_article_numbers,
            )
            self.tracer.end_span(
                guard_span,
                outputs={
                    "is_valid": guard_check.is_valid,
                    "cited_articles": guard_check.validated_response.articles_cites,
                },
            )
            schema_resp = guard_check.validated_response
            is_valid = guard_check.is_valid

        # 5. Enregistrement de l'interaction en base PostgreSQL
        interaction = CitizenInteraction(
            channel=request.channel,
            user_hash=self._hash_user_id(request.user_id),
            raw_input=request.question,
            input_type="TEXT",
            normalized_query=request.question,
            legal_status=schema_resp.statut_legal.value,
            response_text=schema_resp.explication_vulgarisee,
            cited_articles=schema_resp.articles_cites,
            confidence_score=1.0 if is_valid else 0.5,
            is_escalated=schema_resp.necessite_escalade,
        )
        session.add(interaction)
        await session.commit()
        await session.refresh(interaction)

        return LegalQuestionResponse(
            interaction_id=str(interaction.id),
            statut_legal=schema_resp.statut_legal,
            articles_cites=schema_resp.articles_cites,
            explication_vulgarisee=schema_resp.explication_vulgarisee,
            conseil_pratique=schema_resp.conseil_pratique,
            avertissement_legal=schema_resp.avertissement_legal,
            necessite_escalade=schema_resp.necessite_escalade,
            sources=sources,
            confidence_score=interaction.confidence_score,
        )
