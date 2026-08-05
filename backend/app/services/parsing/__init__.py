"""Document parsing: raw bytes in, citable text blocks out."""

from __future__ import annotations

from app.core.exceptions import DocumentParseError
from app.core.logging import get_logger
from app.services.parsing.base import (
    DocumentParser,
    ParseContext,
    ParsedDocument,
    TextBlock,
)
from app.services.parsing.documents import (
    DocxParser,
    PdfParser,
    PptxParser,
    XlsxParser,
)
from app.services.parsing.ocr import ImageParser, ocr_availability
from app.services.parsing.text import (
    CodeParser,
    DelimitedTextParser,
    HtmlParser,
    MarkdownParser,
    PlainTextParser,
)
from app.services.parsing.zipped import EpubParser, OdtParser, RtfParser

logger = get_logger(__name__)

__all__ = [
    "CodeParser",
    "DelimitedTextParser",
    "DocumentParser",
    "DocxParser",
    "EpubParser",
    "HtmlParser",
    "ImageParser",
    "MarkdownParser",
    "OdtParser",
    "ParseContext",
    "ParsedDocument",
    "ParserRegistry",
    "PdfParser",
    "PlainTextParser",
    "PptxParser",
    "RtfParser",
    "TextBlock",
    "XlsxParser",
    "build_parser_registry",
    "ocr_availability",
]


class ParserRegistry:
    """Dispatches a file to the parser that claims its extension."""

    def __init__(self, parsers: list[DocumentParser]) -> None:
        self._by_extension: dict[str, DocumentParser] = {}
        for parser in parsers:
            for extension in parser.extensions:
                if (existing := self._by_extension.get(extension)) is not None:
                    raise ValueError(
                        f"Both {existing.name} and {parser.name} claim {extension!r}. "
                        "Extensions must map to exactly one parser."
                    )
                self._by_extension[extension] = parser

    def for_extension(self, extension: str) -> DocumentParser | None:
        return self._by_extension.get(extension.lower().lstrip("."))

    def parse(self, context: ParseContext) -> ParsedDocument:
        parser = self.for_extension(context.extension)
        if parser is None:
            raise DocumentParseError(f"No parser is available for .{context.extension} files.")

        logger.debug("parsing", parser=parser.name, filename=context.filename)
        try:
            return parser.parse(context)
        except DocumentParseError:
            raise
        except Exception as exc:
            # Any library-specific failure becomes one domain error, so a
            # malformed file is a 422 about the document rather than a 500
            # about us.
            logger.warning(
                "parser_crashed",
                parser=parser.name,
                filename=context.filename,
                error=str(exc),
            )
            raise DocumentParseError(f"{context.filename!r} could not be read: {exc}") from exc

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset(self._by_extension)


def build_parser_registry() -> ParserRegistry:
    """The one place parser implementations are named."""
    return ParserRegistry(
        [
            PdfParser(),
            DocxParser(),
            PptxParser(),
            XlsxParser(),
            EpubParser(),
            OdtParser(),
            RtfParser(),
            MarkdownParser(),
            HtmlParser(),
            DelimitedTextParser(),
            ImageParser(),
            # Last: it claims the largest, least specific set of extensions.
            CodeParser(),
            PlainTextParser(),
        ]
    )
