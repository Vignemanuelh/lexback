# AGENTS.md — Backend FastAPI & Moteur RAG Juridique (lexback)

> Guide de développement et règles non-négociables pour le backend `lexback`.
> L'agent doit lire ce fichier avant toute intervention sur le code Python.

---

## 1. Vue d'ensemble du Backend

**Rôle** : Cœur d'ingestion, de recherche hybride, de génération contrainte et d'exposition API/Webhooks pour l'Assistant Numérique Citoyen sur le Code du numérique béninois.

**Stack officielle** :
* **Langage & Runtime** : Python 3.12 (standard LTS)
* **Framework Web** : FastAPI 0.143.0 avec cycle de vie `lifespan`
* **Base de données** : PostgreSQL 18 avec extension `pgvector` (image `pgvector/pgvector:pg18`)
* **ORM & Migrations** : SQLAlchemy 2.1.4 (asyncpg 0.30+ pour API, sync_engine pour SQLAdmin) + Alembic
* **Cache & Files asynchrones** : Redis 8.4-alpine + ARQ 0.28.0 (worker asynchrone pour audio/vision/WhatsApp)
* **IA & RAG** : Google Gemini 2.0 Flash (SDK `google-genai`), embeddings `text-embedding-004`
* **Audio & Vision** : Voxtral/Whisper (ASR), Kokoro-82M/Google (TTS), Gemini Multimodal (Vision/OCR)
* **Observabilité** : Langfuse Python SDK (>= 4.56.0) avec `@observe` et logging JSON `structlog` (>= 26.1.0)
* **Back-Office Juriste** : SQLAdmin (intégré à FastAPI avec SQLAlchemy)

### Virtual Environment (Règle absolue)

```bash
# Dans le dossier lexback/
source venv/bin/activate   # Activer le venv avant TOUTE commande Python
```

> **Interdiction absolue** : Jamais de `pip install`, `pytest`, `ruff`, `mypy`, `alembic` ou `uvicorn` hors venv.

---

## 2. Architecture interne — Layered Clean Architecture

```
lexback/
├── src/
│   ├── main.py                     # Lifespan FastAPI, CORS, montage routes et SQLAdmin
│   │
│   ├── core/                       # Socle transverse
│   │   ├── config.py               # Settings Pydantic v2 (BaseSettings), zéro valeur hardcodée
│   │   ├── database.py             # async_engine, sync_engine, Base déclarative, get_db_session
│   │   └── logging.py              # Configuration structlog JSON
│   │
│   ├── domain/                     # Métier pur (indépendant des frameworks)
│   │   ├── entities/               # LawVersion, LegalStructure, LegalArticle, CitizenInteraction
│   │   ├── schemas/                # LegalStatus, LegalResponseSchema, Requests/Responses
│   │   └── guardrails/             # CitationGuardrail (vérification déterministe)
│   │
│   ├── services/                   # Adaptateurs et moteurs externes
│   │   ├── rag/                    # HybridSearchEngine (RRF BM25 tsvector + pgvector)
│   │   ├── llm/                    # GeminiClient (génération structurée & embeddings)
│   │   ├── audio/                  # Transcriber (ASR) & Synthesizer (TTS)
│   │   ├── vision/                 # ImageAnalyzer (OCR & détection risques image)
│   │   ├── whatsapp/               # Webhook Meta, sender & vérification signature
│   │   └── queue/                  # Worker ARQ & gestion tâches asynchrones
│   │
│   ├── application/                # Cas d'usage métier orchestrés
│   │   ├── ask_legal_question.py   # RAG complet : recherche -> Gemini -> guardrail -> DB/Langfuse
│   │   └── ingest_law.py           # Découpage par article complet et indexation vectorielle
│   │
│   └── presentation/               # Contrôleurs HTTP et vues
│       ├── api/v1/                 # Endpoints REST publics, FAQ, signalements, escalades
│       ├── webhooks/               # Réception événements WhatsApp Cloud API
│       └── admin/                  # Vues d'administration SQLAdmin
│
└── tests/
    ├── conftest.py                 # Mocks obligatoires (Gemini, WhatsApp, ASR, TTS)
    ├── unit/                       # Tests unitaires isolés par composant
    ├── integration/                # Tests d'intégration DB réelle & API
    └── golden_dataset/             # 20+ cas officiels de test juridique (vérité terrain)
```

### Règles d'imports et dépendances :
1. **Dépendances descendantes strictes** : `presentation/` $\rightarrow$ `application/` $\rightarrow$ `services/` $\rightarrow$ `domain/` $\rightarrow$ `core/`. Jamais l'inverse.
2. **Pas d'import circulaire** : extraire les contrats partagés dans `core/` ou `domain/`.
3. **Zéro `os.getenv()` hors de `core/config.py`**.
4. **Logging structuré obligatoire avec `structlog`** sur chaque action importante (`user_hash`, `action`, `latence_ms`, `statut`).

---

## 3. Conventions de nommage

| Élément | Convention | Exemple |
|---|---|---|
| Fichiers / modules | `snake_case` | `hybrid_search.py`, `citation_guardrail.py` |
| Classes | `PascalCase` | `HybridSearchEngine`, `LegalArticle` |
| Fonctions / variables | `snake_case` | `ask_legal_question()`, `article_number` |
| Constantes | `SCREAMING_SNAKE` | `MAX_AUDIO_SIZE_MB`, `SYSTEM_INSTRUCTION` |
| Fonctions asynchrones | préfixe `async def` | `async def search_articles()` |
| Schémas Pydantic | suffixe `Schema`, `Request` ou `Response` | `LegalResponseSchema`, `LegalQuestionRequest` |
| Tables DB | `snake_case` pluriel | `law_versions`, `legal_articles`, `citizen_interactions` |

---

## 4. Règles Métier & Juridiques Non-Négociables

| Code | Règle | Impact technique |
|---|---|---|
| **RG-JUR1** | **Vérité terrain exclusive** : Réponse strictement issue du Code du numérique béninois. | Prompt contraint + seuil de pertinence RRF minimal. |
| **RG-JUR2** | **Zéro hallucination d'article** : Tout article cité doit être présent dans le contexte extrait. | `CitationGuardrail` déterministe : validation mathématique d'inclusion. |
| **RG-JUR3** | **Découpage par article complet** : Aucun article ne doit être tronqué au milieu d'une phrase. | Parsing regex préservant l'intégrité intégrale de l'article et ses alinéas. |
| **RG-JUR4** | **Statut juridique explicite** : Qualification obligatoire parmi 4 valeurs. | Enum strict : `autorisé`, `interdit`, `à risque`, `zone grise`. |
| **RG-JUR5** | **Escalade obligatoire pour zone grise** : Ne jamais forcer une réponse incertaine. | Si ambiguïté $\rightarrow$ `necessite_escalade=True` + formulaire juriste. |
| **RG-JUR6** | **Avertissement légal systématique** : L'outil informe mais ne remplace pas un avocat. | Présent obligatoirement dans `LegalResponseSchema`. |
| **RG-JUR7** | **Suppression immédiate des médias** : Notes vocales et photos supprimées après traitement. | Pattern `try/finally` obligatoire sur `/tmp/audio_*.ogg` et images. |
| **RG-JUR8** | **Protection de la vie privée (APDP)** : Aucun numéro de téléphone stocké en clair. | Hash SHA-256 (`user_hash`) sur tous les identifiants usagers. |

---

## 5. Gestion des Erreurs & WhatsApp Cloud API

### « Never let an exception reach WhatsApp silently »
```python
# ✅ CORRECT — Webhook Meta toujours 200 OK, gestion et log d'erreur en interne
@router.post("/webhook")
async def receive_whatsapp(request: Request):
    try:
        await process_incoming_message(...)
    except Exception as e:
        logger.error("erreur_webhook_whatsapp", exc_info=True, erreur=str(e))
    return {"status": "ok"}  # Toujours 200 à Meta pour éviter les boucles infinies de retries
```

### Vérification de signature obligatoire
```python
# Toujours vérifier le header X-Hub-Signature-256 avec settings.WHATSAPP_APP_SECRET
signature = request.headers.get("X-Hub-Signature-256", "")
if not verify_signature(payload_bytes, signature):
    logger.warning("signature_invalide_rejetee")
    return {"status": "ignored"}
```

### Cycle de vie des fichiers temporaires
```python
# Pattern try/finally obligatoire pour les fichiers audio/images
with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
    tmp.write(media_bytes)
    tmp_path = tmp.name
try:
    transcription = await transcribe_audio(tmp_path)
finally:
    if os.path.exists(tmp_path):
        os.unlink(tmp_path)
```

---

## 6. Workflow Git & Définition de "Terminé"

### Branches par Skill
Chaque fonctionnalité se développe sur une branche issue de `develop` :
```
skill/<nom-du-skill>

Exemples :
skill/db-pgvector-17
skill/rag-hybrid-search
skill/citation-guardrail
skill/ingestion-code-numerique
skill/webhook-whatsapp
skill/golden-dataset
```

### Validation obligatoire avant tout merge dans `develop`
Un skill n'est fusionné que si **les 4 commandes suivantes sont 100 % vertes** :

```bash
# 1. Tests avec zéro warning et couverture minimale 80%
pytest tests/ -W error --tb=short -q --cov=. --cov-fail-under=80

# 2. Vérification linter stricte
ruff check .

# 3. Vérification des types statiques
mypy . --ignore-missing-imports

# 4. Documentation
# Toutes les fonctions et classes publiques ont une docstring claire.
```

---

## 7. Mocking Obligatoire dans `tests/conftest.py`

* `mock_gemini` : Simule les embeddings (vecteur 768) et la génération JSON structurée.
* `mock_whatsapp` : Intercepte les appels HTTP vers l'API Graph Meta.
* `mock_whisper` / `mock_tts` : Simule la transcription audio et la génération vocale.
