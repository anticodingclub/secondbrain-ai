"""RAG chat.

Runs against a scripted LLM rather than a real one. That is not a compromise:
the behaviour worth testing here is *ours* — which sources get retrieved, what
the model is told, which citations survive, what happens when the provider
dies — and a real model would make every one of those assertions
non-deterministic while proving nothing extra.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import pytest
from httpx import AsyncClient

from app.services.llm.base import CompletionChunk, LLMProvider, LLMUnavailableError, Message

pytestmark = [pytest.mark.integration, pytest.mark.slow]

PREFIX = "/api/v1"

NOTES = b"""# Engineering Notes

## Authentication

We chose OAuth 2.0 with PKCE for the mobile client.

## Deployment

The Dockerfile builds on python:3.11-slim.
"""


class ScriptedProvider(LLMProvider):
    """Returns a fixed answer, recording what it was asked."""

    def __init__(self, answer: str = "The Dockerfile builds on python:3.11-slim [1].") -> None:
        self.model = "scripted-test-model"
        self._answer = answer
        self.received: list[Message] = []

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        self.received = list(messages)
        # Word by word, so the streaming path is genuinely exercised.
        for word in self._answer.split(" "):
            yield CompletionChunk(text=word + " ")
        yield CompletionChunk(text="", done=True)

    async def health(self) -> bool:
        return True


class BrokenProvider(LLMProvider):
    def __init__(self) -> None:
        self.model = "broken"

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        raise LLMUnavailableError("ollama", "connection refused")
        yield  # pragma: no cover - unreachable, satisfies the generator protocol

    async def health(self) -> bool:
        return False


@pytest.fixture
def scripted(app) -> ScriptedProvider:
    provider = ScriptedProvider()
    app.state.container.llm_provider = provider
    return provider


async def sign_up(client: AsyncClient, email: str = "ada@example.com") -> str:
    response = await client.post(
        f"{PREFIX}/auth/register",
        json={"email": email, "password": "correct-horse-battery", "display_name": "Ada"},
    )
    return str(response.json()["access_token"])


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def seed(client: AsyncClient, token: str) -> None:
    await client.post(
        f"{PREFIX}/documents/upload",
        headers=bearer(token),
        files={"file": ("notes.md", NOTES, "text/markdown")},
    )


def parse_events(body: str) -> list[tuple[str, dict]]:
    """Decode a Server-Sent Events stream into (event, data) pairs."""
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name and data is not None:
            events.append((name, data))
    return events


async def ask(client: AsyncClient, token: str, question: str, **extra: object):
    response = await client.post(
        f"{PREFIX}/chat/ask", headers=bearer(token), json={"question": question, **extra}
    )
    assert response.status_code == 200, response.text
    return parse_events(response.text)


# ── Answering ────────────────────────────────────────────────────────────────


async def test_answer_streams_tokens_then_citations(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    token = await sign_up(client)
    await seed(client, token)

    events = await ask(client, token, "How is the container built?")
    names = [name for name, _ in events]

    assert names[0] == "start"
    assert "token" in names
    assert names.index("citations") > names.index("token")
    assert names[-1] == "done"

    text = "".join(data["text"] for name, data in events if name == "token")
    assert "Dockerfile" in text


async def test_the_model_is_given_the_retrieved_sources(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    """Grounding is the whole point: if the passages never reach the prompt,
    the answer is invention no matter how good it sounds."""
    token = await sign_up(client)
    await seed(client, token)

    await ask(client, token, "How is the container built?")

    prompt = scripted.received[-1].content
    assert "Sources:" in prompt
    assert "Dockerfile" in prompt
    assert "python:3.11-slim" in prompt


async def test_the_system_prompt_forbids_outside_knowledge(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    token = await sign_up(client)
    await seed(client, token)

    await ask(client, token, "How is the container built?")

    system = scripted.received[0].content
    assert "ONLY the numbered sources" in system
    assert "Do not use outside knowledge" in system


async def test_citations_carry_the_anchors_needed_to_open_the_source(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    token = await sign_up(client)
    await seed(client, token)

    events = await ask(client, token, "How is the container built?")
    citations = next(data["citations"] for name, data in events if name == "citations")

    assert citations
    first = citations[0]
    assert first["document_id"]
    assert first["document_title"]
    assert first["snippet"]
    assert first["number"] == 1


async def test_only_cited_sources_are_returned(client: AsyncClient, app) -> None:
    """Listing all eight sources when the answer used one turns citations
    into decoration and teaches the user to ignore them."""
    app.state.container.llm_provider = ScriptedProvider("Only the first source matters [1].")

    token = await sign_up(client)
    await seed(client, token)

    events = await ask(client, token, "What did we choose for auth?")
    citations = next(data["citations"] for name, data in events if name == "citations")

    assert [citation["number"] for citation in citations] == [1]


# ── Grounding failures ───────────────────────────────────────────────────────


async def test_no_matching_documents_refuses_instead_of_inventing(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    """With nothing retrieved there is nothing to ground an answer in, so the
    model is never asked — calling it anyway invites confident invention."""
    token = await sign_up(client)

    events = await ask(client, token, "What is my blood type?")

    text = "".join(data["text"] for name, data in events if name == "token")
    assert "could not find anything" in text.lower()
    assert scripted.received == [], "the model should not have been called"


async def test_provider_failure_is_reported_as_an_event(client: AsyncClient, app) -> None:
    """The response has already begun by the time the model fails, so the
    status line is long gone and the error must travel in-band."""
    app.state.container.llm_provider = BrokenProvider()

    token = await sign_up(client)
    await seed(client, token)

    events = await ask(client, token, "How is the container built?")
    errors = [data for name, data in events if name == "error"]

    assert errors
    assert errors[0]["provider"] == "ollama"
    assert "unavailable" in errors[0]["message"].lower()


# ── Conversations ────────────────────────────────────────────────────────────


async def test_a_conversation_is_created_and_titled_from_the_question(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    token = await sign_up(client)
    await seed(client, token)

    await ask(client, token, "How is the container built?")
    conversations = (await client.get(f"{PREFIX}/chat/conversations", headers=bearer(token))).json()

    assert len(conversations) == 1
    assert conversations[0]["title"] == "How is the container built?"


async def test_both_turns_are_persisted_with_their_citations(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    token = await sign_up(client)
    await seed(client, token)

    events = await ask(client, token, "How is the container built?")
    conversation_id = next(data["conversation_id"] for name, data in events if name == "done")

    detail = (
        await client.get(f"{PREFIX}/chat/conversations/{conversation_id}", headers=bearer(token))
    ).json()

    roles = [message["role"] for message in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["citations"]
    assert detail["messages"][1]["model"] == "scripted-test-model"
    assert detail["messages"][1]["latency_ms"] is not None


async def test_follow_up_questions_receive_prior_turns(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    """Without history, "and what about auth?" has no referent."""
    token = await sign_up(client)
    await seed(client, token)

    first = await ask(client, token, "How is the container built?")
    conversation_id = next(data["conversation_id"] for name, data in first if name == "done")

    await ask(client, token, "And what about authentication?", conversation_id=conversation_id)

    replayed = [message.content for message in scripted.received]
    assert any("How is the container built?" in content for content in replayed)


async def test_chat_can_be_scoped_to_chosen_documents(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    token = await sign_up(client)
    await seed(client, token)
    await client.post(
        f"{PREFIX}/documents/upload",
        headers=bearer(token),
        files={"file": ("recipes.md", b"# Recipes\n\nWhisk three eggs.\n", "text/markdown")},
    )

    listing = (await client.get(f"{PREFIX}/documents", headers=bearer(token))).json()
    recipes = next(item for item in listing["items"] if item["original_filename"] == "recipes.md")

    await ask(client, token, "What is here?", document_ids=[recipes["id"]])

    prompt = scripted.received[-1].content
    assert "eggs" in prompt
    assert "Dockerfile" not in prompt


# ── Isolation ────────────────────────────────────────────────────────────────


async def test_chat_only_sees_the_askers_documents(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    await seed(client, ada)

    events = await ask(client, grace, "How is the container built?")

    text = "".join(data["text"] for name, data in events if name == "token")
    assert "could not find anything" in text.lower()


async def test_another_user_cannot_read_a_conversation(
    client: AsyncClient, scripted: ScriptedProvider
) -> None:
    ada = await sign_up(client, "ada@example.com")
    grace = await sign_up(client, "grace@example.com")
    await seed(client, ada)

    events = await ask(client, ada, "How is the container built?")
    conversation_id = next(data["conversation_id"] for name, data in events if name == "done")

    response = await client.get(
        f"{PREFIX}/chat/conversations/{conversation_id}", headers=bearer(grace)
    )

    assert response.status_code == 404


async def test_chat_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(f"{PREFIX}/chat/ask", json={"question": "hello"})
    assert response.status_code == 401
