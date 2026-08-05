"""Ollama, OpenAI, Anthropic and Gemini.

Each vendor streams differently — Ollama sends newline-delimited JSON, the
other three send Server-Sent Events with incompatible payload shapes — so the
only shared code is the HTTP plumbing. `_StreamingProvider` owns that, and
each subclass declares its request shape and how to read one token out of a
response line.
"""

from __future__ import annotations

import json
from abc import abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.llm.base import (
    CompletionChunk,
    LLMProvider,
    LLMUnavailableError,
    Message,
    Role,
)

logger = get_logger(__name__)

#: Generous: a grounded answer over several documents legitimately takes tens
#: of seconds on a local model, and a timeout that fires mid-answer is worse
#: than a slow one.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0)


class _StreamingProvider(LLMProvider):
    """Shared HTTP streaming, with per-vendor request and parse hooks."""

    name: str = "llm"

    def __init__(self, *, model: str, base_url: str, api_key: str | None = None) -> None:
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> AsyncIterator[CompletionChunk]:
        url, headers, payload = self._request(messages, temperature, max_tokens)

        try:
            async with self._client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")[:500]
                    raise LLMUnavailableError(self.name, f"HTTP {response.status_code}: {body}")

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    for chunk in self._parse_line(line):
                        yield chunk
                        if chunk.done:
                            return
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(self.name, str(exc)) from exc

    @abstractmethod
    def _request(
        self, messages: Sequence[Message], temperature: float, max_tokens: int | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]: ...

    @abstractmethod
    def _parse_line(self, line: str) -> list[CompletionChunk]:
        """Extract zero or more tokens from one line of the response stream."""

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _sse_payload(line: str) -> dict[str, Any] | None:
        """Decode one `data:` line of a Server-Sent Events stream."""
        if not line.startswith("data:"):
            return None
        body = line[5:].strip()
        if not body or body == "[DONE]":
            return None
        try:
            parsed: dict[str, Any] = json.loads(body)
        except json.JSONDecodeError:
            return None
        return parsed


class OllamaProvider(_StreamingProvider):
    """Local models. The default, because it needs no key and no network."""

    name = "ollama"

    def _request(
        self, messages: Sequence[Message], temperature: float, max_tokens: int | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens

        return (
            f"{self._base_url}/api/chat",
            {},
            {
                "model": self.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                "stream": True,
                "options": options,
            },
        )

    def _parse_line(self, line: str) -> list[CompletionChunk]:
        # Newline-delimited JSON, not SSE.
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return []

        text = str(payload.get("message", {}).get("content", ""))
        done = bool(payload.get("done"))
        if not text and not done:
            return []
        return [CompletionChunk(text=text, done=done)]

    async def health(self) -> bool:
        try:
            response = await self._client.get(f"{self._base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False


class OpenAIProvider(_StreamingProvider):
    name = "openai"

    def _request(
        self, messages: Sequence[Message], temperature: float, max_tokens: int | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role.value, "content": m.content} for m in messages],
            "stream": True,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        return (
            f"{self._base_url}/chat/completions",
            {"Authorization": f"Bearer {self._api_key}"},
            payload,
        )

    def _parse_line(self, line: str) -> list[CompletionChunk]:
        payload = self._sse_payload(line)
        if payload is None:
            return [CompletionChunk("", done=True)] if line.strip() == "data: [DONE]" else []

        choices = payload.get("choices") or []
        if not choices:
            return []
        delta = choices[0].get("delta", {})
        text = str(delta.get("content") or "")
        finished = choices[0].get("finish_reason") is not None
        if not text and not finished:
            return []
        return [CompletionChunk(text=text, done=finished)]

    async def health(self) -> bool:
        return bool(self._api_key)


class AnthropicProvider(_StreamingProvider):
    """Claude. The system prompt is a top-level field, not a message."""

    name = "anthropic"

    def _request(
        self, messages: Sequence[Message], temperature: float, max_tokens: int | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        system = "\n\n".join(m.content for m in messages if m.role is Role.SYSTEM)
        conversation = [
            {"role": m.role.value, "content": m.content}
            for m in messages
            if m.role is not Role.SYSTEM
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": conversation,
            "stream": True,
            "temperature": temperature,
            # Required by the API rather than optional, so it always has a value.
            "max_tokens": max_tokens or 4096,
        }
        if system:
            payload["system"] = system

        return (
            f"{self._base_url}/v1/messages",
            {
                "x-api-key": self._api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            payload,
        )

    def _parse_line(self, line: str) -> list[CompletionChunk]:
        payload = self._sse_payload(line)
        if payload is None:
            return []

        event = payload.get("type")
        if event == "content_block_delta":
            text = str(payload.get("delta", {}).get("text") or "")
            return [CompletionChunk(text=text)] if text else []
        if event in {"message_stop", "error"}:
            return [CompletionChunk("", done=True)]
        return []

    async def health(self) -> bool:
        return bool(self._api_key)


class GeminiProvider(_StreamingProvider):
    """Gemini. Roles are `user`/`model`, and there is no system role."""

    name = "gemini"

    def _request(
        self, messages: Sequence[Message], temperature: float, max_tokens: int | None
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        contents = [
            {
                "role": "model" if m.role is Role.ASSISTANT else "user",
                "parts": [{"text": m.content}],
            }
            for m in messages
            if m.role is not Role.SYSTEM
        ]
        system = "\n\n".join(m.content for m in messages if m.role is Role.SYSTEM)

        generation: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            generation["maxOutputTokens"] = max_tokens

        payload: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        return (
            f"{self._base_url}/models/{self.model}:streamGenerateContent"
            f"?alt=sse&key={self._api_key}",
            {"content-type": "application/json"},
            payload,
        )

    def _parse_line(self, line: str) -> list[CompletionChunk]:
        payload = self._sse_payload(line)
        if payload is None:
            return []

        candidates = payload.get("candidates") or []
        if not candidates:
            return []

        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(str(part.get("text") or "") for part in parts)
        finished = candidates[0].get("finishReason") is not None

        if not text and not finished:
            return []
        return [CompletionChunk(text=text, done=finished)]

    async def health(self) -> bool:
        return bool(self._api_key)
