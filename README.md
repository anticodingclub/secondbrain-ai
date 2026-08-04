# SecondBrain AI

A local-first personal search engine. Index everything you own — documents,
code, notes, images — then ask questions in plain language and get answers
grounded in your own files, with citations back to the exact page.

> **Status: Phase 3 of 10 complete.** Architecture, persistence, dependency
> injection, provider interfaces, the application shell, authentication and
> file uploads are built, tested and running. See the [roadmap](#roadmap).

---

## Quick start

No Docker, PostgreSQL or Qdrant installation required. The stack runs on
SQLite plus an embedded Qdrant out of the box.

**Requirements:** Python 3.11 or 3.12, Node.js 20.9+.

```bash
cp .env.example .env
```

```bash
./scripts/tasks.ps1 setup
```

On macOS or Linux use `make setup` instead. Then in two terminals:

```bash
./scripts/tasks.ps1 dev-backend
```

```bash
./scripts/tasks.ps1 dev-frontend
```

The API is at http://localhost:8000 (interactive docs at `/docs`) and the app
at http://localhost:3000.

---

## Why this architecture

### The core decision: two stores, one identity

Chunk **text and metadata** live in a relational database; chunk **vectors**
live in Qdrant. They are joined by `DocumentChunk.id`.

This is the decision everything else follows from. Relational storage gives
exact filters, joins, transactional consistency and the page/paragraph anchors
that make citations possible. A vector database gives approximate
nearest-neighbour search over millions of embeddings. Neither does the other's
job well, and duplicating the data in both guarantees they drift. Instead each
holds exactly what it is good at, keyed by a shared id.

### Technology choices

| Choice | Why |
| --- | --- |
| **FastAPI** | Document parsing and LLM calls are I/O-bound, so an async framework keeps throughput high without a thread per request. Pydantic models double as the OpenAPI schema, so the frontend contract cannot silently drift. |
| **PostgreSQL** | Needed for JSONB metadata filters, full-text search in the hybrid retrieval path, and real concurrency once background workers index alongside live queries. |
| **SQLAlchemy 2.0 + Alembic** | Typed ORM with a genuine async driver. `Uuid` and `JSON.with_variant` let one model definition target both SQLite (dev) and Postgres (prod) without a compatibility shim. |
| **Qdrant** | Applies payload filters *inside* the HNSW traversal rather than after it. Post-filtering would let another user's chunks consume the top-k budget — so pre-filtering is what makes per-user isolation correct, not just a UI nicety. Runs embedded for dev, clustered for prod. |
| **BGE embeddings** | Strong retrieval quality per parameter. `fastembed` (ONNX, ~130 MB) is the default; `bge-large-en-v1.5` via sentence-transformers is one config change away. |
| **Next.js App Router** | Server Components keep the document list and viewer off the client bundle, while the search and chat surfaces stay fully interactive. |
| **React Query** | Search results, indexing status and chat history are server state with different freshness needs. Cache invalidation belongs in a library that specialises in it, not in `useEffect`. |
| **Self-hosted JWT auth** | A local-first tool must work offline. Hosted auth would put a network round-trip to a third party in the login path of an app whose entire premise is that your data never leaves your machine. |

### Layering

Dependencies point inward. `api` may import `services`; `services` may import
`repositories`; nothing imports `api`.

```
app/api/          HTTP only — status codes, request parsing, DI wiring
app/services/     Business logic and external integrations
app/repositories/ Persistence — the only layer that emits SQL
app/models/       ORM entities
app/core/         Cross-cutting: config, logging, errors, retry, container
app/workers/      Background jobs (parsing, embedding, folder sync)
```

Three rules make this hold up:

**Services raise domain exceptions, never `HTTPException`.** `app/core/exceptions.py`
defines the hierarchy and `app/api/errors.py` is the single place that maps it
onto HTTP. The same service can then be called from a worker or a CLI, where
HTTP status codes would be meaningless.

**Concrete classes are named in exactly one file.** `app/core/container.py` is
the composition root. Swapping fastembed for bge-large, or Qdrant for another
store, is a change there and nowhere else.

**Transactions are owned by the caller.** No repository method commits. The
request (via the `get_session` dependency) or the worker job defines the
boundary, so several repositories can participate in one atomic unit of work.

---

## Development

| Task | Command |
| --- | --- |
| Run tests | `./scripts/tasks.ps1 test` |
| Lint | `./scripts/tasks.ps1 lint` |
| Format | `./scripts/tasks.ps1 fmt` |
| Type-check | `./scripts/tasks.ps1 typecheck` |
| Everything CI runs | `./scripts/tasks.ps1 check` |
| New migration | `./scripts/tasks.ps1 migration -Message "add chat tables"` |
| Apply migrations | `./scripts/tasks.ps1 migrate` |

Every task has a `make` equivalent with the same name.

### Configuration

All settings are `SECONDBRAIN_`-prefixed environment variables, defined and
validated in `backend/app/core/config.py`. See `.env.example`.

Production configuration is validated at startup, not discovered at runtime:
booting with `ENVIRONMENT=production` while still holding the placeholder
secret key, or a SQLite URL, fails immediately with a clear message.

### Moving to the production stack

```bash
docker compose -f docker/docker-compose.yml up -d
```

Then point the backend at those services and re-run migrations:

```bash
SECONDBRAIN_DATABASE_URL=postgresql+asyncpg://secondbrain:secondbrain@localhost:5432/secondbrain
SECONDBRAIN_QDRANT_URL=http://localhost:6333
```

No application code changes — the dual-dialect models and the URL-driven Qdrant
client already handle both.

### Upgrading embedding quality

```bash
SECONDBRAIN_EMBEDDING_PROVIDER=sentence_transformers
SECONDBRAIN_EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
SECONDBRAIN_EMBEDDING_DIMENSIONS=1024
```

Install the extra with `pip install -e "backend[embeddings-torch]"`. Vectors
from different models are not comparable, so this requires a re-index —
`DocumentChunk.embedding_model` records which model produced each vector
precisely so stale chunks can be found.

---

## Testing

```
tests/unit/         Config validation, retry policy, repository behaviour
tests/integration/  The real ASGI app through httpx, middleware and all
```

Integration tests exercise the actual application via `ASGITransport` rather
than a mocked client, so middleware, exception handlers and DI wiring are all
covered. Each test gets an isolated database and Qdrant directory via `tmp_path`,
which keeps them order-independent and parallel-safe.

---

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Architecture, persistence, DI, provider interfaces, app shell | **Done** |
| 2 | Authentication — argon2, rotating JWT refresh, tenant isolation | **Done** |
| 3 | File uploads — drag-and-drop, streaming, dedupe, storage abstraction | **Done** |
| 4 | Parsing — PDF, DOCX, PPTX, XLSX, HTML, code, plus OCR | |
| 5 | Chunking and embeddings — recursive and semantic strategies, incremental re-index | |
| 6 | Search — semantic, hybrid (BM25 + dense), metadata filters, reranking | |
| 7 | Chat — streaming RAG with citations, scoped conversations, history | |
| 8 | Dashboard — storage, vector counts, search analytics | |
| 9 | GitHub — clone, structure-aware code indexing, symbol search | |
| 10 | Production — containers, migrations, observability, deployment | |

---

## Project layout

```
secondbrain-ai/
├── backend/
│   ├── app/
│   │   ├── api/            HTTP layer, DI, middleware, error mapping
│   │   ├── core/           Config, logging, exceptions, retry, container
│   │   ├── db/             Engine, session, declarative base
│   │   ├── models/         ORM entities
│   │   ├── repositories/   Persistence
│   │   ├── schemas/        Request/response contracts
│   │   ├── services/       Business logic, embeddings, vector store
│   │   └── workers/        Background jobs
│   ├── alembic/            Migrations
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/            App Router pages
│       ├── components/     UI primitives and app shell
│       ├── hooks/          React Query hooks
│       └── lib/            API client, query client, navigation, utils
├── docker/                 Compose stack and Dockerfiles
└── scripts/                Task runner
```
