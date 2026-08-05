"""What a parser is, and what it produces.

The output type is the important part of this module. Every parser flattens a
wildly different format into the same sequence of `TextBlock`s, each carrying
whatever anchor its format naturally has — a PDF page, a Word heading, a slide
number, a spreadsheet cell range.

Those anchors are the reason this layer exists in the shape it does. A citation
that says "somewhere in this 200-page PDF" is not a citation. Capturing the
anchor at *parse* time is the only opportunity: once text has been concatenated
and chunked, the information is gone for good.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A contiguous run of text with a citable location."""

    text: str

    #: 1-based, as a human counts pages. Also used for slide and sheet numbers,
    #: since all three answer "where in the file do I look?".
    page_number: int | None = None

    #: The nearest enclosing heading, slide title or sheet name.
    section_title: str | None = None

    #: Nesting depth of `section_title` (1 = H1). Lets Phase 5 chunk along
    #: structural boundaries rather than blindly by character count.
    heading_level: int | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    blocks: Sequence[TextBlock]
    page_count: int | None = None
    #: Format-specific extras: PDF author, spreadsheet sheet names, OCR
    #: confidence. Schemaless because every format surfaces different fields.
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Set when a parser succeeded but with caveats worth showing the user —
    #: an image with no detectable text, a PDF whose pages are all scans.
    warnings: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return "\n\n".join(block.text for block in self.blocks if block.text.strip())

    @property
    def word_count(self) -> int:
        return sum(block.word_count for block in self.blocks)

    @property
    def is_empty(self) -> bool:
        return not any(block.text.strip() for block in self.blocks)


@dataclass(frozen=True, slots=True)
class ParseContext:
    """The file to parse, already materialised on local disk.

    A path rather than bytes: pypdf, openpyxl and python-pptx all seek, and
    holding a 500 MB upload in memory to satisfy them would trade a disk read
    for an outage.
    """

    path: Path
    filename: str
    mime_type: str
    extension: str


class DocumentParser(ABC):
    """Extracts text and structure from one family of formats."""

    #: Extensions this parser claims, without the leading dot.
    extensions: frozenset[str] = frozenset()

    @abstractmethod
    def parse(self, context: ParseContext) -> ParsedDocument:
        """Extract content.

        Deliberately synchronous. Every underlying library is blocking and
        CPU-bound, so pretending otherwise with an `async def` that never
        awaits would stall the event loop while looking like it does not.
        The pipeline runs these in a worker thread instead.

        Raises `DocumentParseError` for a file this parser cannot read.
        """

    @property
    def name(self) -> str:
        return type(self).__name__
