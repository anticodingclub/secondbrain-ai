"""One interface over four LLM vendors.

Implemented directly on httpx rather than each vendor's SDK. Four SDKs would
mean four dependency trees, four retry policies, four timeout defaults and
four exception hierarchies to translate — for what is, in every case, a POST
returning a stream of JSON. The wire formats differ; the work of talking to
them does not.

The cost is that new vendor features need implementing here rather than
arriving with an SDK upgrade. For chat completion — a stable, near-commodity
API — that trade is worth taking.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class CompletionChunk:
    """One increment of a streamed answer."""

    text: str
    done: bool = False


class LLMProvider(ABC):
    """Generates text from a conversation."""

    #: Shown in the UI and recorded on saved messages, so an answer can always
    #: be traced to the model that produced it.
    model: str

    @abstractmethod
    def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        """Stream a completion.

        Streaming is the primary interface, not an optimisation: a grounded
        answer over several documents takes seconds, and a user watching a
        spinner for that long assumes the app has hung.
        """

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """Collect a full completion. Convenience for non-streaming callers."""
        parts: list[str] = []
        async for chunk in self.stream(messages, temperature=temperature, max_tokens=max_tokens):
            parts.append(chunk.text)
        return "".join(parts)

    @abstractmethod
    async def health(self) -> bool:
        """Whether the provider is reachable and configured."""

    async def aclose(self) -> None:
        """Release connections.

        Deliberately concrete and empty rather than abstract: a provider with
        nothing to close — a test double, a future in-process model — should
        not be forced to write a no-op override.
        """
        return None


class LLMUnavailableError(Exception):
    """The provider could not be reached or is not configured.

    Deliberately not a `SecondBrainError`: the API layer turns it into a
    503 with a message naming the provider, because the fix is always
    environmental — start Ollama, set an API key — and never something the
    user can do differently in their question.
    """

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"{provider} is unavailable: {detail}")
        self.provider = provider
        self.detail = detail
