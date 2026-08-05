# SecondBrain AI

A local-first personal search engine. Index everything you own — documents,
code, notes, images — then ask questions in plain language and get answers
grounded in your own files, with citations back to the exact page.

[![CI](https://github.com/USERNAME/secondbrain-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/USERNAME/secondbrain-ai/actions/workflows/ci.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%20%E2%80%93%203.14-blue.svg)](https://www.python.org/)

> **This is a work in progress: 6 of 10 phases are built.** Being upfront so
> you know what you are cloning.

### What works today

- **Accounts** — register and sign in. Documents are private per user, and
  that boundary is enforced server-side and tested.
- **Uploads** — drag and drop, progress bars, and 60+ file types. Identical
  files are detected by content hash and stored once.
- **Library** — browse, filter, download and delete your documents.
- **Text extraction** — PDF, Word, PowerPoint, Excel, EPUB, ODT, RTF, HTML,
  Markdown, CSV, code and images (OCR). Page numbers, headings and slide
  numbers are preserved so answers can cite an exact location.
- **Search** — ask in plain language. Hybrid retrieval fuses semantic meaning
  with exact term matching, so both "where is my offer letter" and a literal
  identifier work in the same box.

### What does not work yet

**Chat is not built.** Search returns the right passages, but nothing yet
composes them into a written answer with citations. That is Phase 7.

---

## Quick start

No Docker, PostgreSQL or Qdrant installation needed. It runs on SQLite plus an
embedded Qdrant, so setup is two commands and everything stays on your machine.

**Requirements:** Python 3.11–3.14 and Node.js 20.9+.

```bash
git clone https://github.com/USERNAME/secondbrain-ai.git && cd secondbrain-ai
```

```bash
cp .env.example .env
```

```bash
make setup
```

On Windows without `make`, use `./scripts/tasks.ps1 setup` — every task has the
same name in both. Setup creates a virtualenv, installs both stacks and applies
migrations. Expect it to take a few minutes.

Then in two terminals:

```bash
make dev-backend
```

```bash
make dev-frontend
```

Open http://localhost:3000 and create an account. The API is at
http://localhost:8000 with interactive docs at `/docs`.

> On first upload the app downloads the embedding model (~130 MB) once. That
> is the only network call it makes, and it is cached afterwards — everything
> else runs offline.

### Something not working?

| Symptom | Cause |
| --- | --- |
| `requires a different Python` | Your default `python` is outside 3.11–3.14. Create the venv with a supported one: `python3.12 -m venv backend/.venv`. |
| Port 3000 already in use | Next.js picks the next free port and prints it. Set `NEXT_PUBLIC_API_URL` if you also move the backend. |
| Login succeeds then immediately logs out | The refresh cookie was rejected. Check `SECONDBRAIN_ENVIRONMENT=development` in `.env`, since secure cookies are dropped over plain HTTP. |

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
| Run tests | `make test` |
| Lint | `make lint` |
| Format | `make fmt` |
| Type-check | `make typecheck` |
| Everything CI runs | `make check` |
| New migration | `make migration m="add chat tables"` |
| Apply migrations | `make migrate` |

On Windows without `make`, every task has the same name under
`./scripts/tasks.ps1` — for example `./scripts/tasks.ps1 check`, or
`./scripts/tasks.ps1 migration -Message "add chat tables"`.

Tests that load a real embedding model are marked `slow` and skipped by
default. Run them with `pytest -m slow` from `backend/`.

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
| 4 | Parsing — PDF, DOCX, PPTX, XLSX, HTML, code, plus OCR | **Done** |
| 5 | Chunking and embeddings — recursive chunking, batched embedding, incremental re-index | **Done** |
| 6 | Search — hybrid dense + keyword with reciprocal rank fusion, filters | **Done** |
| 7 | Chat — streaming RAG with citations, scoped conversations, history | Next |
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

---

## Contributing

Pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup
steps and the conventions the codebase follows.

Run `make check` before opening a PR — it runs exactly what CI runs.

## Licence

[MIT](LICENSE). Use it, fork it, build on it.
