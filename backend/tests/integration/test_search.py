"""Search, end to end.

The headline test is `test_the_questions_from_the_brief_work`: the four
queries the project was specified around, run against uploaded files through
the real API. If those fail, the product does not work regardless of what
every other test says.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration, pytest.mark.slow]

PREFIX = "/api/v1"

CORPUS: dict[str, bytes] = {
    "internship-offer.md": b"""# Internship Offer

Acme Corp is pleased to offer you a software engineering internship.
Your start date is June 3rd and the stipend is 4820 per month.
""",
    "backend-notes.md": b"""# Backend Project Notes

## API Design

The upload endpoint is POST /api/v1/documents/upload and accepts multipart
form data. Authentication uses a bearer token in the Authorization header.
""",
    "meeting-notes.md": b"""# Meeting Notes

## Mobile Client

We discussed OAuth at length and settled on OAuth 2.0 with PKCE, rejecting
the implicit flow as insecure for public clients.
""",
    "deployment.md": b"""# Deployment

## Containers

The Dockerfile builds on python:3.11-slim. Docker Compose brings up Postgres
and Qdrant together for the production stack.
""",
    "recipes.md": b"""# Recipes

## Scrambled Eggs

Whisk three eggs with butter over low heat until softly scrambled.
""",
}


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> str:
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Ada"},
    )
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def seed(client: AsyncClient, token: str) -> None:
    for filename, content in CORPUS.items():
        await client.post(
            f"{PREFIX}/documents/upload",
            headers=bearer(token),
            files={"file": (filename, content, "text/markdown")},
        )


async def run_search(client: AsyncClient, token: str, query: str, **extra: object):
    response = await client.post(
        f"{PREFIX}/search", headers=bearer(token), json={"query": query, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── The brief ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("question", "expected_file"),
    [
        ("Where is my internship offer letter?", "internship-offer.md"),
        ("What was the API endpoint in my backend project?", "backend-notes.md"),
        ("Show notes where I discussed OAuth.", "meeting-notes.md"),
        ("Find every mention of Docker.", "deployment.md"),
    ],
)
async def test_the_questions_from_the_brief_work(
    client: AsyncClient, question: str, expected_file: str
) -> None:
    """The four queries this project was specified around."""
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, question)

    assert body["hits"], f"no results for {question!r}"
    assert body["hits"][0]["filename"] == expected_file, (
        f"{question!r} returned {body['hits'][0]['filename']!r}"
    )


# ── Ranking behaviour ────────────────────────────────────────────────────────


async def test_semantic_match_without_shared_words(client: AsyncClient) -> None:
    """The reason dense retrieval earns its place: none of these query words
    appear in the target text."""
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "how do we build the container image", mode="semantic")

    assert body["hits"][0]["filename"] == "deployment.md"


async def test_exact_identifier_is_found_by_keyword_search(client: AsyncClient) -> None:
    """The reason keyword retrieval earns its place: an embedding blurs an
    exact string into every nearby identifier."""
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "4820", mode="keyword")

    assert body["hits"]
    assert body["hits"][0]["filename"] == "internship-offer.md"


async def test_hybrid_reports_which_retrievers_matched(client: AsyncClient) -> None:
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "OAuth PKCE mobile client")

    assert body["hits"]
    assert any(hit["matched_by"] for hit in body["hits"])
    assert set(body["hits"][0]["matched_by"]) <= {"semantic", "keyword"}


async def test_unrelated_content_does_not_win(client: AsyncClient) -> None:
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "Where is my internship offer letter?")

    assert body["hits"][0]["filename"] != "recipes.md"


# ── Citations ────────────────────────────────────────────────────────────────


async def test_hits_carry_the_anchors_needed_to_cite_them(client: AsyncClient) -> None:
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "Show notes where I discussed OAuth.")
    hit = body["hits"][0]

    assert hit["document_id"]
    assert hit["document_title"]
    assert hit["section_title"] == "Mobile Client"
    assert hit["snippet"]


async def test_snippet_centres_on_the_match(client: AsyncClient) -> None:
    """Showing the head of every chunk would display the same boilerplate for
    every result; a snippet exists to show *why* this one matched."""
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "PKCE")

    assert "PKCE" in body["hits"][0]["snippet"]


# ── Filters and limits ───────────────────────────────────────────────────────


async def test_search_can_be_scoped_to_one_document(client: AsyncClient) -> None:
    """The foundation of "chat with this document"."""
    token = await sign_up(client)
    await seed(client, token)

    listing = await client.get(f"{PREFIX}/documents", headers=bearer(token))
    recipes = next(
        item for item in listing.json()["items"] if item["original_filename"] == "recipes.md"
    )

    body = await run_search(client, token, "Docker", document_ids=[recipes["id"]])

    assert all(hit["document_id"] == recipes["id"] for hit in body["hits"])


async def test_limit_is_respected(client: AsyncClient) -> None:
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "the", limit=2)

    assert len(body["hits"]) <= 2


async def test_reports_how_long_it_took(client: AsyncClient) -> None:
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "Docker")

    assert body["took_ms"] >= 0


# ── Isolation and validation ─────────────────────────────────────────────────


async def test_search_never_crosses_the_tenant_boundary(client: AsyncClient) -> None:
    """The property every other feature depends on."""
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    await seed(client, ada)

    body = await run_search(client, grace, "Where is my internship offer letter?")

    assert body["hits"] == []


async def test_search_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(f"{PREFIX}/search", json={"query": "anything"})
    assert response.status_code == 401


async def test_empty_query_is_rejected(client: AsyncClient) -> None:
    token = await sign_up(client)
    response = await client.post(f"{PREFIX}/search", headers=bearer(token), json={"query": ""})
    assert response.status_code == 422


async def test_query_matching_nothing_returns_empty_not_an_error(
    client: AsyncClient,
) -> None:
    token = await sign_up(client)
    await seed(client, token)

    body = await run_search(client, token, "zzzzqqqq nonexistent term", mode="keyword")

    assert body["hits"] == []
    assert body["total"] == 0


async def test_searching_with_no_documents_returns_empty(client: AsyncClient) -> None:
    token = await sign_up(client)

    body = await run_search(client, token, "anything at all")

    assert body["hits"] == []
