# Contributing

Thanks for taking a look. This is an in-progress project — see the
[roadmap](README.md#roadmap) for what exists and what does not.

## Getting set up

```bash
cp .env.example .env
```

```bash
make setup
```

On Windows without `make`, use `./scripts/tasks.ps1 setup`. Every task has the
same name in both.

## Before you open a pull request

```bash
make check
```

That runs exactly what CI runs: `ruff`, `ruff format --check`, `mypy` on the
backend, and `tsc`, `eslint` and `next build` on the frontend. If it passes
locally it should pass in CI — if it does not, that gap is itself a bug worth
reporting.

## House rules

These are the conventions the existing code follows. They are not arbitrary
preferences; each one exists because ignoring it caused a real problem.

**Services raise domain exceptions, never `HTTPException`.** The mapping to
HTTP lives in `app/api/errors.py` alone, so the same service can be called
from a worker or a CLI where status codes would be meaningless.

**No repository method commits.** The request (via `get_session`) or the
worker job owns the transaction, so several repositories can take part in one
atomic unit of work. The single deliberate exception is documented where it
occurs, in `AuthService._revoke_family_durably`.

**Every query that touches user data is scoped by `owner_id`.** The
`CurrentUser` dependency is the only trustworthy source of that id — never a
value from a request body, which the caller controls.

**Concrete classes are named in `app/core/container.py` and nowhere else.**
That is what makes swapping the embedding provider or vector store a one-file
change.

## Tests

Write the failure cases, not just the happy path. Most of the real bugs found
so far were caught by tests asserting what must *not* happen: a replayed token
must not work, a renamed executable must not be indexed as a PDF, one user
must not see another's documents.

Tests that need a real embedding model are marked `slow` and excluded from the
default run:

```bash
pytest -m "not slow"
```

## Commit messages

Explain why the change was necessary, not what the diff already shows. If a
decision has a non-obvious trade-off, the commit message is the right place
for it.
