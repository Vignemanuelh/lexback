import json
import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.use_cases.ingest_law import (
    IngestLawUseCase,
    LawIngestionUseCase,
    parse_structure_component,
)
from src.domain.entities.law import (
    ArticleEmbedding,
    LawVersion,
    LegalArticle,
    LegalStructure,
)


class FakeScalarsResult:
    """Simulateur du résultat scalars() de SQLAlchemy."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None

    def one_or_none(self) -> Any | None:
        return self._items[0] if self._items else None


class FakeQueryResult:
    """Simulateur d'un résultat d'exécution de requête SQLAlchemy."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def scalars(self) -> FakeScalarsResult:
        return FakeScalarsResult(self._items)

    def scalar_one(self) -> Any:
        if not self._items:
            raise ValueError("No item found")
        return self._items[0]

    def all(self) -> list[Any]:
        return list(self._items)


class FakeAsyncSession:
    """Session asynchrone en mémoire pour tester les use cases sans base PostgreSQL."""

    def __init__(self) -> None:
        self.versions: list[LawVersion] = []
        self.structures: list[LegalStructure] = []
        self.articles: list[LegalArticle] = []
        self.embeddings: list[ArticleEmbedding] = []
        self.added_entities: list[Any] = []
        self.flush_count = 0
        self.commit_count = 0

    def add(self, obj: Any) -> None:
        self.added_entities.append(obj)
        if isinstance(obj, LawVersion):
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            if obj not in self.versions:
                self.versions.append(obj)
        elif isinstance(obj, LegalStructure):
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            if obj not in self.structures:
                self.structures.append(obj)
        elif isinstance(obj, LegalArticle):
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            if obj not in self.articles:
                self.articles.append(obj)
        elif isinstance(obj, ArticleEmbedding):
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()
            if obj not in self.embeddings:
                self.embeddings.append(obj)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1

    async def refresh(self, obj: Any) -> None:
        pass

    async def execute(self, stmt: Any) -> FakeQueryResult:
        # Analyse de l'entité ciblée par l'expression select
        if hasattr(stmt, "column_descriptions") and stmt.column_descriptions:
            entity = stmt.column_descriptions[0].get("entity")
            if entity and issubclass(entity, LawVersion):
                return FakeQueryResult(self.versions)
            if entity and issubclass(entity, LegalStructure):
                return FakeQueryResult(self.structures)
            if entity and issubclass(entity, LegalArticle):
                return FakeQueryResult(self.articles)
            if entity and issubclass(entity, ArticleEmbedding):
                return FakeQueryResult(self.embeddings)
        return FakeQueryResult([])


@pytest.fixture
def fake_session() -> Any:
    return FakeAsyncSession()


@pytest.fixture
def mock_gemini_client() -> MagicMock:
    client = MagicMock()
    client.get_embedding = AsyncMock(return_value=[0.05] * 768)
    return client


def test_parse_structure_component_strings():
    """Vérifie le parsing robuste de différentes syntaxes de structures."""
    # 1. Structure simple
    stype, num, title = parse_structure_component("livre", "LIVRE PRELIMINAIRE")
    assert stype == "LIVRE"
    assert num == "PRELIMINAIRE"
    assert title == "LIVRE PRELIMINAIRE"

    # 2. Structure avec numéro ordinal
    stype, num, title = parse_structure_component("livre", "LIVRE PREMIER")
    assert stype == "LIVRE"
    assert num == "PREMIER"

    # 3. Structure avec titre explicite
    stype, num, title = parse_structure_component("chapitre", "CHAPITRE II : Des principes généraux")
    assert stype == "CHAPITRE"
    assert num == "II"
    assert title == "Des principes généraux"

    # 4. Format dictionnaire direct
    dict_val = {
        "structure_type": "SECTION",
        "number_label": "IV",
        "title": "Dispositions particulières",
    }
    stype, num, title = parse_structure_component("section", dict_val)
    assert stype == "SECTION"
    assert num == "IV"
    assert title == "Dispositions particulières"

    # 5. Fallback avec type générique
    stype, num, title = parse_structure_component("titre", "ANNEXE UNIQUE")
    assert stype == "TITRE"
    assert num == "ANNEXE UNIQUE"


def test_parse_legal_text():
    """Vérifie le découpage de texte brut par expression régulière."""
    use_case = IngestLawUseCase()
    raw = (
        "Article 1er : Objet\nLe présent code fixe les règles...\n\n"
        "Article 2 : Définitions\nOn entend par réseau tout ensemble...\n"
    )
    parsed = use_case.parse_legal_text(raw)
    assert len(parsed) == 2
    assert parsed[0].article_number == "1er"
    assert parsed[0].title == "Objet"
    assert "Le présent code fixe" in parsed[0].content
    assert parsed[1].article_number == "2"
    assert parsed[1].title == "Définitions"


def test_parse_legal_text_empty():
    """Vérifie la robustesse si aucun article n'est trouvé."""
    use_case = IngestLawUseCase()
    parsed = use_case.parse_legal_text("Texte quelconque sans aucun mot clé d'article.")
    assert parsed == []


@pytest.mark.asyncio
async def test_ingest_articles_nominal_creation(
    fake_session: Any,
    mock_gemini_client: MagicMock,
):
    """Vérifie la création nominale complète d'une version, de structures et d'articles."""
    use_case = IngestLawUseCase(gemini_client=mock_gemini_client)

    sample_articles = [
        {
            "article_number": "1er",
            "title": "Définitions",
            "full_content": "Au sens du présent code, les termes...",
            "hierarchy": {
                "livre": "LIVRE PRELIMINAIRE",
                "titre": None,
                "chapitre": None,
                "section": None,
            },
        },
        {
            "article_number": "10",
            "title": "Obligations de service universel",
            "full_content": "Les opérateurs contribuent au service universel...",
            "hierarchy": {
                "livre": "LIVRE PREMIER",
                "titre": "TITRE PREMIER",
                "chapitre": "CHAPITRE II",
                "section": "SECTION I",
            },
        },
    ]

    report = await use_case.ingest_articles(
        session=fake_session,
        articles_data=sample_articles,
        code_name="Code du numérique",
        official_reference="Loi 2017-20 modifiée 2020-35",
        promulgation_date=date(2018, 4, 20),
        effective_date=date(2021, 1, 6),
        notes="Texte officiel consolidé",
        batch_size=10,
        compute_embeddings=True,
    )

    # 1. Vérification du rapport
    assert report.total_articles == 2
    assert report.created_articles == 2
    assert report.updated_articles == 0
    assert report.created_structures == 5  # Livre Prelim, Livre 1, Titre 1, Chap 2, Sec 1
    assert report.embeddings_computed == 2

    # 2. Vérification de la LawVersion
    assert len(fake_session.versions) == 1
    version = fake_session.versions[0]
    assert version.official_reference == "Loi 2017-20 modifiée 2020-35"
    assert version.is_active is True
    assert version.effective_date == date(2021, 1, 6)

    # 3. Vérification des liaisons hiérarchiques (LegalStructure)
    assert len(fake_session.structures) == 5
    struct_dict = {(s.structure_type, s.number_label): s for s in fake_session.structures}

    livre_prelim = struct_dict[("LIVRE", "PRELIMINAIRE")]
    assert livre_prelim.parent_id is None

    livre_1 = struct_dict[("LIVRE", "PREMIER")]
    assert livre_1.parent_id is None

    titre_1 = struct_dict[("TITRE", "PREMIER")]
    assert titre_1.parent_id == livre_1.id

    chap_2 = struct_dict[("CHAPITRE", "II")]
    assert chap_2.parent_id == titre_1.id

    sec_1 = struct_dict[("SECTION", "I")]
    assert sec_1.parent_id == chap_2.id

    # 4. Vérification des LegalArticle et rattachement à la structure la plus spécifique
    art1 = next(a for a in fake_session.articles if a.article_number == "1er")
    assert art1.title == "Définitions"
    assert art1.structure_id == livre_prelim.id
    assert art1.is_in_force is True

    art10 = next(a for a in fake_session.articles if a.article_number == "10")
    assert art10.title == "Obligations de service universel"
    assert art10.structure_id == sec_1.id  # Structure la plus spécifique !

    # 5. Vérification des ArticleEmbedding
    assert len(fake_session.embeddings) == 2
    assert mock_gemini_client.get_embedding.call_count == 2
    emb_art10 = next(e for e in fake_session.embeddings if e.article_id == art10.id)
    assert len(emb_art10.embedding) == 768


@pytest.mark.asyncio
async def test_ingest_articles_total_idempotency(
    fake_session: Any,
    mock_gemini_client: MagicMock,
):
    """Garantit l'idempotence totale : réexécuter l'ingestion ne duplique aucun objet."""
    use_case = IngestLawUseCase(gemini_client=mock_gemini_client)

    sample_articles = [
        {
            "article_number": "1",
            "title": "Titre initial",
            "full_content": "Contenu initial de l'article 1",
            "hierarchy": {
                "livre": "LIVRE PREMIER",
                "titre": "TITRE I",
            },
        },
        {
            "article_number": "2",
            "title": "Article 2",
            "full_content": "Contenu article 2",
            "hierarchy": {
                "livre": "LIVRE PREMIER",
                "titre": "TITRE I",
            },
        },
    ]

    # Premier passage
    rep1 = await use_case.ingest_articles(
        session=fake_session,
        articles_data=sample_articles,
        code_name="Code du numérique",
        official_reference="Loi 2017-20",
    )
    assert rep1.created_articles == 2
    assert rep1.created_structures == 2  # Livre I + Titre I
    assert rep1.embeddings_computed == 2
    assert len(fake_session.versions) == 1
    assert len(fake_session.structures) == 2
    assert len(fake_session.articles) == 2
    assert len(fake_session.embeddings) == 2

    # Second passage avec modification de texte sur l'article 1
    sample_updated = [
        {
            "article_number": "1",
            "title": "Titre mis à jour",
            "full_content": "Contenu consolidé 2021",
            "hierarchy": {
                "livre": "LIVRE PREMIER",
                "titre": "TITRE I",
            },
        },
        {
            "article_number": "2",
            "title": "Article 2",
            "full_content": "Contenu article 2",
            "hierarchy": {
                "livre": "LIVRE PREMIER",
                "titre": "TITRE I",
            },
        },
    ]

    rep2 = await use_case.ingest_articles(
        session=fake_session,
        articles_data=sample_updated,
        code_name="Code du numérique",
        official_reference="Loi 2017-20",
    )

    # 0 nouvelle création, uniquement des mises à jour !
    assert rep2.created_articles == 0
    assert rep2.updated_articles == 2
    assert rep2.created_structures == 0
    assert rep2.embeddings_computed == 0

    # Pas de doublons dans les collections
    assert len(fake_session.versions) == 1
    assert len(fake_session.structures) == 2
    assert len(fake_session.articles) == 2
    assert len(fake_session.embeddings) == 2

    # L'article 1 a bien été mis à jour sur place
    art1 = next(a for a in fake_session.articles if a.article_number == "1")
    assert art1.title == "Titre mis à jour"
    assert art1.full_content == "Contenu consolidé 2021"


@pytest.mark.asyncio
async def test_ingest_from_json_file(
    tmp_path,
    fake_session: Any,
    mock_gemini_client: MagicMock,
):
    """Teste le chargement et l'ingestion directe depuis un fichier JSON sur le disque."""
    data = [
        {
            "article_number": "42",
            "title": "Cryptographie",
            "full_content": "L'utilisation des moyens cryptologiques est libre...",
            "hierarchy": {"livre": "LIVRE TROISIEME"},
        }
    ]
    json_file = tmp_path / "test_articles.json"
    json_file.write_text(json.dumps(data), encoding="utf-8")

    use_case = IngestLawUseCase(gemini_client=mock_gemini_client)
    report = await use_case.ingest_from_json(
        session=fake_session,
        json_path=json_file,
        official_reference="Loi 2017-20",
    )

    assert report.total_articles == 1
    assert report.created_articles == 1
    assert len(fake_session.articles) == 1
    assert fake_session.articles[0].article_number == "42"


@pytest.mark.asyncio
async def test_ingest_from_json_file_not_found(fake_session: Any):
    """Vérifie l'exception si le fichier JSON n'existe pas."""
    use_case = IngestLawUseCase()
    with pytest.raises(FileNotFoundError):
        await use_case.ingest_from_json(
            session=fake_session,
            json_path="/tmp/unlikely_existing_file_999.json",
        )


@pytest.mark.asyncio
async def test_ingest_without_embeddings(
    fake_session: Any,
    mock_gemini_client: MagicMock,
):
    """Vérifie que l'option compute_embeddings=False saute les embeddings."""
    use_case = IngestLawUseCase(gemini_client=mock_gemini_client)
    sample = [
        {
            "article_number": "5",
            "full_content": "Texte court",
            "hierarchy": {},
        }
    ]

    report = await use_case.ingest_articles(
        session=fake_session,
        articles_data=sample,
        compute_embeddings=False,
    )

    assert report.embeddings_computed == 0
    assert len(fake_session.embeddings) == 0
    mock_gemini_client.get_embedding.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_law_version_compatibility(
    fake_session: Any,
    mock_gemini_client: MagicMock,
):
    """Teste la méthode historique ingest_law_version avec texte brut découpé."""
    use_case = LawIngestionUseCase(gemini_client=mock_gemini_client)
    raw_text = (
        "Article 100 : Secret des correspondances\n"
        "Le secret des correspondances émises par voie électronique est garanti.\n"
    )

    version = await use_case.ingest_law_version(
        session=fake_session,
        code_name="Code du numérique",
        official_reference="Loi 2017-20-compat",
        effective_date=date(2018, 4, 20),
        raw_text=raw_text,
    )

    assert isinstance(version, LawVersion)
    assert version.official_reference == "Loi 2017-20-compat"
    assert len(fake_session.articles) == 1
    assert fake_session.articles[0].article_number == "100"


@pytest.mark.asyncio
async def test_ingest_article_without_hierarchy(
    fake_session: Any,
    mock_gemini_client: MagicMock,
):
    """Vérifie le traitement d'un article sans hiérarchie (structure_id=None)."""
    use_case = IngestLawUseCase(gemini_client=mock_gemini_client)
    sample = [
        {
            "article_number": "999",
            "full_content": "Dispositions transitoires",
            "hierarchy": None,
        }
    ]

    report = await use_case.ingest_articles(
        session=fake_session,
        articles_data=sample,
        compute_embeddings=False,
    )

    assert report.total_articles == 1
    assert fake_session.articles[0].structure_id is None
