# RAG Django: Chat with Your PDFs

A production-style **Retrieval-Augmented Generation (RAG)** application. Users sign in, upload PDF documents, and ask questions in a chat UI. Answers are generated **only from the uploaded documents** by an LLM, and every answer is checked for hallucination before it is returned.

The whole stack runs on **AWS ECS Fargate**, deployed automatically from GitHub on every push to `main`.

---

## Table of contents

1. [Features](#features)
2. [Tech stack](#tech-stack)
3. [System architecture](#system-architecture)
4. [How it works](#how-it-works)
   - [Document ingestion pipeline](#document-ingestion-pipeline)
   - [LangGraph orchestration](#langgraph-orchestration)
   - [LLM model fallbacks](#llm-model-fallbacks)
5. [Data model](#data-model)
6. [API reference](#api-reference)
7. [Security](#security)
8. [MLOps and observability](#mlops-and-observability)
9. [CI/CD and deployment](#cicd-and-deployment)
10. [Configuration](#configuration)
11. [Local development](#local-development)
12. [Project structure](#project-structure)
13. [Known limitations and roadmap](#known-limitations-and-roadmap)

---

## Features

- **PDF upload and ingestion:** files are stored in S3, split into chunks, embedded, and indexed in PostgreSQL.
- **Semantic search:** pgvector with an HNSW index and cosine distance.
- **Agentic RAG with LangGraph:** retrieval, relevance grading, query rewriting, generation and hallucination checking, with conditional loops.
- **Hallucination scoring:** each answer gets a 0 to 1 groundedness score, and high scores trigger regeneration.
- **Resilient LLM layer:** an ordered list of Groq models, with automatic fallback if one fails or is unavailable.
- **Free local embeddings:** `all-MiniLM-L6-v2` runs inside the container, with no embedding API and no cost.
- **JWT authentication** with short-lived access tokens and rotating refresh tokens.
- **Rate limiting and input sanitization** middleware.
- **Prometheus metrics** and a health endpoint.
- **Zero-touch deployment:** GitHub Actions builds, pushes to ECR and rolls out to ECS. Migrations run automatically on container start.

---

## Tech stack

| Layer | Technology |
|---|---|
| Web framework | Django 5, Django REST Framework |
| Auth | JWT (`djangorestframework-simplejwt`) |
| Orchestration | LangGraph, LangChain |
| LLM | Groq (`openai/gpt-oss-120b` by default, with fallbacks) |
| Embeddings | `sentence-transformers` / `all-MiniLM-L6-v2` (384 dimensions) |
| Vector store | PostgreSQL + `pgvector` (HNSW index) |
| Cache | Redis (embedding cache, rate limiting) |
| Task queue | Celery (runs inline, see [ingestion](#document-ingestion-pipeline)) |
| File storage | Amazon S3 |
| PDF parsing | `pypdf` |
| Server | Gunicorn on Docker (`python:3.11-slim`) |
| Compute | AWS ECS Fargate |
| Registry / CI/CD | Amazon ECR, GitHub Actions |
| Metrics | `prometheus-client` |
| Sanitization | `bleach` |

---

## System architecture

```mermaid
flowchart LR
    U["User browser<br/>(chat UI)"] -->|"HTTP + JWT"| ECS

    subgraph AWS["AWS (us-east-1)"]
        subgraph ECS["ECS Fargate service: rag-api"]
            direction TB
            MW["Middleware<br/>rate limit + sanitize"] --> API["Django REST API"]
            API --> LG["LangGraph RAG pipeline"]
            API --> ING["Ingestion task<br/>(Celery, eager)"]
            LG --> EMB["Embedder<br/>all-MiniLM-L6-v2"]
            ING --> EMB
        end

        PG[("PostgreSQL<br/>+ pgvector")]
        RD[("Redis<br/>cache + rate limit")]
        S3[("S3 bucket<br/>PDF files")]
        ECR["ECR<br/>Docker images"]
        CW["CloudWatch Logs"]
    end

    GROQ["Groq API<br/>LLM inference"]

    API <--> PG
    API <--> RD
    ING <--> S3
    LG <--> PG
    LG -->|"prompts"| GROQ
    ECS -.->|"logs"| CW
    ECR -.->|"image pull"| ECS
```

A single container runs the web server, the embedding model and the ingestion logic. The model is **baked into the Docker image at build time**, so cold starts don't download anything. State lives in managed services (PostgreSQL, Redis, S3), so tasks are disposable and can be replaced at any time.

---

## How it works

### Document ingestion pipeline

```mermaid
sequenceDiagram
    autonumber
    participant B as Browser
    participant A as Django API
    participant S as S3
    participant T as Ingest task
    participant M as MiniLM embedder
    participant D as PostgreSQL (pgvector)

    B->>A: POST /api/documents/upload/ (PDF, JWT)
    A->>A: Validate .pdf extension
    A->>S: Store file under docs/{uuid}/name.pdf
    A->>D: Create Document row
    A->>T: ingest_document(doc_id)
    T->>S: Download PDF
    T->>T: Extract text (pypdf)
    T->>T: Split into overlapping chunks
    loop each chunk
        T->>M: Embed chunk (384-dim vector)
        M-->>T: vector (cached in Redis for 24h)
    end
    T->>D: Bulk insert DocumentChunk rows
    A-->>B: 201 Created
```

- **Chunking:** the text is split into overlapping word windows, so facts near a boundary aren't lost.
- **Embedding cache:** vectors are cached in Redis by content hash for 24 hours.
- **Index:** an HNSW index (`m=16`, `ef_construction=64`, cosine ops) on the `embedding` column gives fast approximate nearest-neighbour search.
- **Celery mode:** ingestion is a Celery task, but with `CELERY_TASK_ALWAYS_EAGER = True` it runs inside the upload request, so no separate worker container is needed. To scale, remove that flag and run a second ECS service with `celery -A config worker`.

### LangGraph orchestration

The question-answering flow is a **stateful LangGraph graph** with conditional edges, not a fixed chain. The graph state is a typed dictionary (`RAGState`) that carries the question, retrieved documents, graded documents, the generation, the hallucination score and the loop counters.

```mermaid
flowchart TD
    START(["Question"]) --> R["retrieve<br/>embed question, cosine search top-k"]
    R --> G["grade_documents<br/>LLM says relevant: yes/no per chunk"]
    G --> D1{"Any relevant docs?"}
    D1 -->|"No, retries under 2"| RW["rewrite_query<br/>LLM rewrites for semantic search"]
    RW --> R
    D1 -->|"Yes, or retries used up"| GEN["generate<br/>answer ONLY from context"]
    GEN --> H["hallucination_check<br/>LLM scores groundedness 0 to 1"]
    H --> D2{"Score above 0.7<br/>and attempts under 2?"}
    D2 -->|"Yes"| GEN
    D2 -->|"No"| END(["Answer + sources + score"])
```

| Node | What it does |
|---|---|
| `retrieve` | Embeds the question (or the rewritten question on a retry) and runs a pgvector cosine-distance query for the top 5 chunks under a distance cutoff. |
| `grade_documents` | Asks the LLM, chunk by chunk, "is this relevant to the question? yes/no", and keeps only the relevant chunks. This reduces noise in the final prompt. |
| `rewrite_query` | If nothing relevant was found, the LLM rewrites the question into a clearer search query. Loops back to `retrieve` at most twice. |
| `generate` | Answers strictly from the graded context. The prompt instructs the model to reply with a fixed "I don't have enough information" sentence rather than guess. |
| `hallucination_check` | A second LLM call compares the answer against the context and returns a score from 0.0 (fully grounded) to 1.0 (unsupported). If the score is above 0.7, the answer is regenerated, up to twice. |

**Loop safety:** both cycles have counters (`retries`, `gen_attempts`), so the graph always terminates.

**Grounded by design:** the generate prompt restricts the model to the retrieved context, the grader removes irrelevant chunks first, and the hallucination check is a second line of defence.

### LLM model fallbacks

LLM calls go through one factory (`rag_core/llm.py`) that builds an ordered list of Groq models and wraps them with LangChain `.with_fallbacks()`:

```
openai/gpt-oss-120b  ->  qwen/qwen3.6-27b  ->  openai/gpt-oss-20b
```

If the first model returns an error (model retired, project permission blocked, rate limit, outage), the request is retried on the next model automatically. The list is set with the `LLM_MODELS` environment variable, so a model can be swapped without a code change. The models must be enabled in your Groq project.

---

## Data model

```mermaid
erDiagram
    USER ||--o{ DOCUMENT : uploads
    DOCUMENT ||--o{ DOCUMENT_CHUNK : "split into"

    USER {
        int id PK
        string username
    }
    DOCUMENT {
        int id PK
        string title
        string file_key "S3 object key"
        datetime created_at
        int uploaded_by FK
    }
    DOCUMENT_CHUNK {
        int id PK
        int document_id FK
        text content
        int chunk_index
        vector384 embedding "HNSW cosine index"
        datetime created_at
    }
```

Migrations create the `vector` extension first (`VectorExtension()`), then the tables and the HNSW index.

---

## API reference

All `/api/*` endpoints except token endpoints require `Authorization: Bearer <access_token>`.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/token/` | Log in with `username` and `password`; returns `access` and `refresh` tokens. |
| `POST` | `/api/token/refresh/` | Exchange a refresh token for a new access token (refresh tokens rotate). |
| `POST` | `/api/documents/upload/` | Upload a PDF (`multipart/form-data`, field `file`). Returns `201` with the document id. |
| `POST` | `/api/chat/` | Ask a question: `{"question": "..."}` (max 2000 characters). |
| `GET` | `/health/` | Liveness check (no auth). Used by ECS. |
| `GET` | `/health/metrics/` | Prometheus metrics. Requires the `X-Metrics-Token` header. |
| `GET` | `/` | Single-page chat UI. |
| `GET` | `/admin/` | Django admin. |

**Chat response**

```json
{
  "answer": "…",
  "sources": ["resume.pdf"],
  "hallucination_score": 0.1
}
```

**Example**

```bash
TOKEN=$(curl -s -X POST http://<host>:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username":"you","password":"…"}' | python -c "import sys,json;print(json.load(sys.stdin)['access'])")

curl -X POST http://<host>:8000/api/documents/upload/ \
  -H "Authorization: Bearer $TOKEN" -F "file=@document.pdf"

curl -X POST http://<host>:8000/api/chat/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"question":"Summarise this document"}'
```

---

## Security

| Area | What is implemented |
|---|---|
| **Authentication** | JWT via `simplejwt`. Access tokens last 15 minutes; refresh tokens last 7 days and rotate on use. DRF default permission is `IsAuthenticated`, so endpoints are closed unless opened explicitly. |
| **Rate limiting** | Custom middleware limits `/api/*` to 30 requests per minute per user and IP. Counters live in Redis, so the limit is shared across tasks. Over the limit returns `429`. |
| **Input sanitization** | Middleware runs `bleach` over every string in incoming JSON bodies, stripping HTML and script tags. |
| **Input validation** | Questions must be non-empty and at most 2000 characters. Uploads must be `.pdf`. |
| **Prompt-injection posture** | The generation prompt restricts the model to retrieved context and a hallucination check runs on every answer. This reduces the risk but doesn't eliminate it. |
| **Secrets management** | Secrets (`DJANGO_SECRET_KEY`, `DATABASE_URL`, `GROQ_API_KEY`, `REDIS_URL`, `METRICS_TOKEN`) are injected into the ECS task from AWS at runtime and are never committed. `.env` and task-definition dumps are git-ignored. |
| **Least-privilege IAM** | The ECS task role gets S3 access only to the application bucket; GitHub Actions uses a dedicated deploy identity with ECR/ECS permissions. |
| **Metrics protection** | `/health/metrics/` returns `403` without the `X-Metrics-Token` header. |
| **Transport / headers** | Django `SecurityMiddleware` and clickjacking protection are enabled. |
| **Container hygiene** | The image is built from `python:3.11-slim`, the model is baked in at build time, and the container runs a health check. |

> Set a strong `METRICS_TOKEN`. The code default is a placeholder.

---

## MLOps and observability

**Prometheus metrics** (`mlops/metrics.py`), exposed at `/health/metrics/`:

| Metric | Type | Meaning |
|---|---|---|
| `rag_queries_total` | Counter | Questions asked. |
| `rag_errors_total` | Counter | Failed chat requests. |
| `rag_retrievals_total` | Counter | Vector searches performed (includes retries after query rewriting). |
| `rag_node_latency_seconds{node}` | Histogram | Time spent in graph nodes. |
| `rag_hallucination_score` | Histogram | Distribution of groundedness scores (0 good, 1 bad). |

Useful signals to watch:

- **Hallucination score drift:** a rising average means retrieval or prompts are degrading.
- **Retrieval count vs query count:** a ratio well above 1 means many queries need rewriting.
- **Error rate:** spikes usually point to LLM provider issues (retired model, rate limit).

**Health and logging**

- `GET /health/` is used by both the Docker `HEALTHCHECK` and the ECS task health check, with a start period that allows for migrations and model load.
- Logs from gunicorn and Django go to **CloudWatch** (`/ecs/rag-api`). Chat failures are logged with a full traceback.
- Every image is tagged with its **git commit SHA**, so any running task can be traced to a commit and rolled back by redeploying an earlier tag.

**Cost and performance choices**

- Embeddings run locally, so there are no per-token embedding costs.
- Embeddings are cached in Redis.
- The embedding model and LLM clients load lazily to keep startup memory down.
- One gunicorn worker keeps memory low. Scale by adding ECS tasks rather than workers.

---

## CI/CD and deployment

```mermaid
flowchart LR
    DEV["git push to main"] --> GH["GitHub Actions"]
    GH --> BUILD["docker build<br/>(model baked in)"]
    BUILD --> PUSH["Push to ECR<br/>tag = commit SHA + latest"]
    PUSH --> TD["Render new ECS<br/>task definition"]
    TD --> DEP["Deploy to ECS service<br/>wait for stability"]
    DEP --> START["Container starts:<br/>manage.py migrate<br/>then gunicorn"]
```

1. Push to `main` triggers `.github/workflows/deploy.yml`.
2. The workflow builds `docker/Dockerfile`, pushes `rag-app:<sha>` and `rag-app:latest` to ECR.
3. It fetches the current `rag-api` task definition, swaps in the new image, and updates the service.
4. ECS starts the new task, waits for the health check, and then stops the old one.
5. On start, the container runs `python manage.py migrate --noinput` **before** starting gunicorn, so schema changes ship with the code.

**Required GitHub secrets:** `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`.

**Fargate task:** 2 vCPU, 4 GB memory, `awsvpc` networking, port 8000. Fargate assigns a new public IP on each task start, so put an Application Load Balancer in front for a stable address.

### Useful operations

```powershell
# Run a one-off command in the running container (ECS Exec)
$taskArn = (aws ecs list-tasks --cluster rag-cluster --service-name rag-api `
  --desired-status RUNNING --region us-east-1 --query "taskArns[0]" --output text)

aws ecs execute-command --cluster rag-cluster --task $taskArn `
  --container rag-api --interactive `
  --command "python manage.py createsuperuser" --region us-east-1

# Tail logs
aws logs tail /ecs/rag-api --region us-east-1 --since 15m --format short
```

---

## Configuration

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django secret key. |
| `DATABASE_URL` | Yes | PostgreSQL URL, e.g. `postgres://user:pass@host:5432/db`. The database must support `pgvector`. |
| `REDIS_URL` | Yes | Redis URL, e.g. `redis://host:6379/0`. |
| `GROQ_API_KEY` | Yes | Groq API key. |
| `AWS_STORAGE_BUCKET_NAME` | Yes | S3 bucket for uploaded PDFs. |
| `AWS_S3_BUCKET` | No | Alias for the bucket name. |
| `AWS_REGION` | Yes (AWS) | e.g. `us-east-1`. |
| `LLM_MODELS` | No | Comma-separated model list, primary first. Default: `openai/gpt-oss-120b,qwen/qwen3.6-27b,openai/gpt-oss-20b`. |
| `METRICS_TOKEN` | Recommended | Value the metrics endpoint expects in `X-Metrics-Token`. |
| `DEBUG` | No | `false` in production. |

Tunables in `config/settings/base.py`: `EMBEDDING_MODEL`, `RETRIEVAL_TOP_K` (5), JWT lifetimes, and the retrieval distance cutoff in `rag_core/retriever.py`.

---

## Local development

Requirements: Python 3.11, Docker (for PostgreSQL and Redis), and a Groq API key.

```bash
# 1. Databases
docker run -d --name pg -p 5432:5432 -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=rag pgvector/pgvector:pg16
docker run -d --name redis -p 6379:6379 redis:7

# 2. Python environment
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Environment file: create .env in the project root
cat > .env <<'EOF'
DJANGO_SECRET_KEY=change-me
DEBUG=true
DATABASE_URL=postgres://postgres:postgres@localhost:5432/rag
REDIS_URL=redis://localhost:6379/0
GROQ_API_KEY=your-groq-key
AWS_STORAGE_BUCKET_NAME=your-bucket
EOF

# 4. Migrate and run
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Uploads need AWS credentials with access to the bucket (`aws configure` or environment variables). Open `http://localhost:8000`, set the API URL on the login screen, sign in and upload a PDF.

---

## Project structure

```
rag_django/
├── apps/
│   ├── documents/      # Document/DocumentChunk models, upload API, ingest task, migrations
│   ├── chat/           # POST /api/chat/, runs the LangGraph pipeline
│   ├── auth_api/       # Auth app (JWT endpoints are wired in config/urls.py)
│   └── monitoring/     # /health/ and /health/metrics/
├── rag_core/
│   ├── graph.py        # LangGraph state, routing functions, graph assembly
│   ├── nodes.py        # retrieve, grade_documents, rewrite_query, generate
│   ├── hallucination.py# groundedness scoring node
│   ├── llm.py          # Groq model factory with fallbacks
│   ├── retriever.py    # pgvector cosine search
│   └── embedder.py     # MiniLM embeddings, Redis cache, text chunking
├── security/
│   └── middleware.py   # RateLimitMiddleware, InputSanitizationMiddleware
├── mlops/
│   └── metrics.py      # Prometheus metric definitions
├── config/             # Django settings, URLs, WSGI, Celery app
├── templates/index.html# Single-page chat and upload UI
├── docker/             # Dockerfile, docker-compose
├── .github/workflows/deploy.yml   # CI/CD to ECS
└── requirements.txt
```

---

## Known limitations and roadmap

Being upfront about what this project does **not** do yet:

- **Documents are not isolated per user.** Retrieval searches all chunks in the database, so any signed-in user can get answers from any uploaded document. Fix: filter chunks by `document__uploaded_by` in `retriever.py`.
- **No self-service sign-up.** Users are created by an admin (`createsuperuser` or the Django admin).
- **Overly open network settings:** `CORS_ALLOW_ALL_ORIGINS = True` and `ALLOWED_HOSTS = ['*']`. Restrict both to your real domain.
- **No HTTPS.** The service is reachable over plain HTTP on port 8000. Put an ALB with an ACM certificate in front and enable secure-cookie and HSTS settings.
- **Ingestion runs inside the request**, so large PDFs are slow and can hit the gunicorn timeout. Move to a real Celery worker with Redis as the broker.
- **Text-only PDFs.** Scanned or image-only PDFs need OCR, which isn't included.
- **No dashboards or alerts yet.** Metrics are exposed but not scraped. Add Prometheus and Grafana (or CloudWatch alarms) to make use of them.
- **No automated tests.** Adding tests for the graph routing and the ingestion pipeline is a good next step.

**Roadmap ideas:** per-user document isolation, ALB + HTTPS, Celery worker service, OCR for scanned files, streaming responses, RAG evaluation (RAGAS) in CI, Terraform for the AWS infrastructure.

---
