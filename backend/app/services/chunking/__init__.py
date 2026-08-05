"""Turning parsed blocks into retrievable chunks.

A chunk is the unit search returns and the unit an answer cites, which makes
its size a genuine trade-off rather than a tuning knob. Too small and a chunk
loses the context that makes it meaningful — "it was rejected" retrieves for
nothing. Too large and the embedding averages several unrelated topics into a
vector that is close to everything and precise about nothing.

The other constraint is the model: bge-small truncates at 512 tokens, and text
past that is silently dropped. A chunk larger than the window is not a bigger
chunk; it is a chunk with an invisible hole in it.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any

from app.core.config import Settings
from app.services.parsing.base import TextBlock

__all__ = ["Chunk", "ChunkingStrategy", "RecursiveChunker", "build_chunker"]


@dataclass(frozen=True, slots=True)
class Chunk:
    """Retrievable text, with the anchors it inherited from its blocks."""

    text: str
    ordinal: int
    page_number: int | None = None
    section_title: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def approximate_tokens(self) -> int:
        """Rough token count for budgeting a prompt.

        Deliberately an approximation: the exact count needs the model's own
        tokenizer, which differs per provider, and every use here — batching,
        context budgeting, display — tolerates being off by a few percent.
        """
        return max(1, len(self.text) // 4)


class ChunkingStrategy(ABC):
    @abstractmethod
    def split(self, blocks: Sequence[TextBlock]) -> list[Chunk]: ...


#: Split points in descending order of how natural a break they are. Splitting
#: at a paragraph boundary preserves meaning; splitting mid-word destroys it.
_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ")


class RecursiveChunker(ChunkingStrategy):
    """Packs blocks into chunks, splitting only where a break is natural.

    Blocks are accumulated until adding the next would exceed the target, then
    flushed. A block larger than the target on its own is split recursively at
    the most natural separator available, falling back to a hard cut only when
    a single word exceeds the window.

    Two rules shape the packing:

    **A chunk never spans a page break.** Merging text from pages 4 and 5 into
    one chunk makes its citation a lie — it would have to claim one page while
    containing the other.

    **A chunk never spans a change of section.** Sections are the author's own
    statement about what belongs together, and ignoring it merges topics the
    writer deliberately separated.
    """

    def __init__(self, *, chunk_size: int, overlap: int, min_chars: int = 0) -> None:
        if overlap >= chunk_size:
            raise ValueError("Overlap must be smaller than the chunk size.")
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._min_chars = min_chars

    def split(self, blocks: Sequence[TextBlock]) -> list[Chunk]:
        chunks: list[Chunk] = []
        pending: list[TextBlock] = []
        length = 0

        def flush() -> None:
            nonlocal pending, length
            if pending:
                chunks.extend(self._emit(pending, start_ordinal=len(chunks)))
                pending, length = [], 0

        for block in blocks:
            text = block.text.strip()
            if not text:
                continue

            if pending and self._breaks_anchor(pending[-1], block):
                flush()

            # A block bigger than the window can never be packed; split it
            # alone so its own anchors stay attached to every piece.
            if len(text) > self._chunk_size:
                flush()
                for piece in self._split_oversized(text):
                    chunks.extend(self._emit([_with_text(block, piece)], start_ordinal=len(chunks)))
                continue

            if length + len(text) + 2 > self._chunk_size:
                flush()

            pending.append(block)
            length += len(text) + 2  # the "\n\n" joining it to the previous

        flush()
        return [chunk for chunk in chunks if len(chunk.text) >= self._min_chars]

    @staticmethod
    def _breaks_anchor(previous: TextBlock, current: TextBlock) -> bool:
        if previous.page_number != current.page_number:
            return True
        return previous.section_title != current.section_title

    def _emit(self, blocks: list[TextBlock], *, start_ordinal: int) -> list[Chunk]:
        text = "\n\n".join(block.text.strip() for block in blocks)
        head = blocks[0]

        # The heading is prepended to the embedded text, not just stored as
        # metadata: "Docker Setup" in the body is what makes a chunk about
        # build steps retrievable by someone searching for Docker, even when
        # the paragraph itself never says the word.
        if head.section_title and head.section_title not in text:
            text = f"{head.section_title}\n\n{text}"

        return [
            Chunk(
                text=text,
                ordinal=start_ordinal,
                page_number=head.page_number,
                section_title=head.section_title,
                metadata={
                    key: value
                    for key, value in head.metadata.items()
                    if key in {"start_line", "end_line", "row_number", "speaker_notes"}
                },
            )
        ]

    def _split_oversized(self, text: str) -> list[str]:
        """Split one long passage, preferring the most natural separator."""
        pieces = self._split_at_best_separator(text)

        if self._overlap <= 0 or len(pieces) < 2:
            return pieces

        # Carry the tail of each piece into the next so a sentence straddling
        # a boundary remains findable from at least one side.
        overlapped = [pieces[0]]
        for previous, piece in pairwise(pieces):
            tail = previous[-self._overlap :]
            overlapped.append(f"{tail}{piece}" if tail else piece)
        return overlapped

    def _split_at_best_separator(self, text: str) -> list[str]:
        for separator in _SEPARATORS:
            if separator not in text:
                continue

            parts = _split_keeping_separator(text, separator)
            if all(len(part) <= self._chunk_size for part in parts):
                return _greedy_pack(parts, self._chunk_size)

            # This separator helps but is not sufficient; recurse on the parts
            # that are still too long.
            result: list[str] = []
            for part in _greedy_pack(parts, self._chunk_size):
                if len(part) <= self._chunk_size:
                    result.append(part)
                else:
                    result.extend(self._split_at_best_separator(part))
            return result

        # No separator at all — a base64 blob or a minified line. A hard cut is
        # the only option left.
        return [
            text[index : index + self._chunk_size]
            for index in range(0, len(text), self._chunk_size)
        ]


def _split_keeping_separator(text: str, separator: str) -> list[str]:
    """Split without discarding the separator, so text round-trips."""
    parts = text.split(separator)
    return [part + separator for part in parts[:-1]] + [parts[-1]]


def _greedy_pack(parts: list[str], limit: int) -> list[str]:
    packed: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + len(part) > limit:
            packed.append(current)
            current = part
        else:
            current += part
    if current.strip():
        packed.append(current)
    return packed


def _with_text(block: TextBlock, text: str) -> TextBlock:
    return TextBlock(
        text=text,
        page_number=block.page_number,
        section_title=block.section_title,
        heading_level=block.heading_level,
        metadata=block.metadata,
    )


def normalise_whitespace(text: str) -> str:
    """Collapse runs of blank lines and trailing spaces.

    PDF extraction in particular produces ragged whitespace that inflates
    chunk sizes and embeds as noise.
    """
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_chunker(settings: Settings) -> ChunkingStrategy:
    """The one place a chunking strategy is chosen."""
    return RecursiveChunker(
        chunk_size=settings.chunk_size_chars,
        overlap=settings.chunk_overlap_chars,
        min_chars=settings.chunk_min_chars,
    )
