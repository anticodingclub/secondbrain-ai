"""Plain text, Markdown, source code and HTML."""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from charset_normalizer import from_bytes
from selectolax.parser import HTMLParser

from app.core.exceptions import DocumentParseError
from app.core.logging import get_logger
from app.services.parsing.base import (
    DocumentParser,
    ParseContext,
    ParsedDocument,
    TextBlock,
)

logger = get_logger(__name__)

#: Beyond this a single "block" stops being a citable location. Long files are
#: split on blank lines first and only then hard-split at this size.
MAX_BLOCK_CHARS = 4000


def read_text(path: Path) -> str:
    """Decode a text file without assuming UTF-8.

    Real archives contain Windows-1252 exports, UTF-16 logs and files with a
    BOM. Guessing UTF-8 and raising on failure would reject exactly the old
    documents a personal search engine exists to rescue, so the encoding is
    detected and undecodable bytes are replaced rather than fatal.

    Known limitation: the single-byte encodings (cp1252, mac-roman, latin-1)
    overlap in the 0x80-0xFF range, so a short sample is genuinely ambiguous
    and detection may pick a sibling. Words still decode correctly — only
    punctuation codepoints can differ, which costs nothing for retrieval since
    nobody searches for an em dash.
    """
    raw = path.read_bytes()
    if not raw:
        return ""

    # utf-8 first: it is the overwhelmingly common case and detection is not free.
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass

    if (best := from_bytes(raw).best()) is not None:
        return str(best)

    logger.warning("undecodable_text_file", path=path.name)
    return raw.decode("utf-8", errors="replace")


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines, then hard-split anything still oversized."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        stripped = paragraph.strip()
        if not stripped:
            continue
        while len(stripped) > MAX_BLOCK_CHARS:
            pieces.append(stripped[:MAX_BLOCK_CHARS])
            stripped = stripped[MAX_BLOCK_CHARS:]
        if stripped:
            pieces.append(stripped)
    return pieces


class PlainTextParser(DocumentParser):
    extensions = frozenset({"txt", "log", "rst", "org", "ini"})

    def parse(self, context: ParseContext) -> ParsedDocument:
        text = read_text(context.path)
        blocks = [TextBlock(text=paragraph) for paragraph in split_paragraphs(text)]
        return ParsedDocument(blocks=blocks)


class MarkdownParser(DocumentParser):
    """Markdown, keeping headings as section anchors.

    Headings are tracked rather than stripped so a citation can say "under
    *Installation*" instead of quoting a line number nobody can act on.
    """

    extensions = frozenset({"md", "markdown"})

    _HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
    _FENCE = re.compile(r"^\s*(```|~~~)")

    def parse(self, context: ParseContext) -> ParsedDocument:
        text = read_text(context.path)

        blocks: list[TextBlock] = []
        section: str | None = None
        level: int | None = None
        buffer: list[str] = []
        in_fence = False

        def flush() -> None:
            if not buffer:
                return
            body = "\n".join(buffer).strip()
            buffer.clear()
            if not body:
                return
            for piece in split_paragraphs(body):
                blocks.append(TextBlock(text=piece, section_title=section, heading_level=level))

        for line in text.splitlines():
            # A '#' inside a fenced code block is a comment, not a heading.
            if self._FENCE.match(line):
                in_fence = not in_fence
                buffer.append(line)
                continue

            heading = None if in_fence else self._HEADING.match(line)
            if heading:
                flush()
                level = len(heading.group(1))
                section = heading.group(2).strip()
                # The heading is content too — it is often the best answer to
                # "what is this section called".
                blocks.append(TextBlock(text=section, section_title=section, heading_level=level))
            else:
                buffer.append(line)

        flush()

        title = next((b.text for b in blocks if b.heading_level == 1), None)
        return ParsedDocument(blocks=blocks, metadata={"title": title} if title else {})


class CodeParser(DocumentParser):
    """Source files, keeping the enclosing definition as the anchor.

    A deliberately shallow regex rather than a per-language AST: the aim is
    "which function was this in", which a definition line answers for most
    languages, and tree-sitter grammars for forty languages is a Phase 9
    problem rather than a Phase 4 one.
    """

    extensions = frozenset(
        {
            "py",
            "pyi",
            "js",
            "jsx",
            "ts",
            "tsx",
            "java",
            "kt",
            "go",
            "rs",
            "rb",
            "php",
            "c",
            "h",
            "cpp",
            "hpp",
            "cc",
            "cs",
            "swift",
            "scala",
            "sh",
            "bash",
            "zsh",
            "ps1",
            "sql",
            "r",
            "lua",
            "pl",
            "ex",
            "exs",
            "erl",
            "hs",
            "clj",
            "dart",
            "vue",
            "svelte",
            "css",
            "scss",
            "less",
            "graphql",
            "proto",
            "tf",
            "dockerfile",
            "gradle",
            "cmake",
            "m",
            "mm",
            "vb",
            "asm",
            "json",
            "yaml",
            "yml",
            "toml",
            "xml",
        }
    )

    _DEFINITION = re.compile(
        r"^\s*(?:export\s+|public\s+|private\s+|protected\s+|static\s+|async\s+)*"
        r"(?:def|class|func|function|fn|interface|struct|impl|type|const\s+\w+\s*=\s*\()"
        r"\s+?(\w+)",
    )

    def parse(self, context: ParseContext) -> ParsedDocument:
        text = read_text(context.path)
        lines = text.splitlines()

        blocks: list[TextBlock] = []
        definition: str | None = None
        buffer: list[str] = []
        start_line = 1

        def flush(end_line: int) -> None:
            if not buffer:
                return
            body = "\n".join(buffer).strip()
            buffer.clear()
            if body:
                blocks.append(
                    TextBlock(
                        text=body[:MAX_BLOCK_CHARS],
                        section_title=definition,
                        metadata={"start_line": start_line, "end_line": end_line},
                    )
                )

        for number, line in enumerate(lines, start=1):
            if match := self._DEFINITION.match(line):
                flush(number - 1)
                start_line = number
                definition = match.group(1)
            buffer.append(line)

            # Keep blocks citable even inside a very long function.
            if sum(len(item) for item in buffer) > MAX_BLOCK_CHARS:
                flush(number)
                start_line = number + 1

        flush(len(lines))

        return ParsedDocument(
            blocks=blocks,
            metadata={"language": context.extension, "line_count": len(lines)},
        )


class HtmlParser(DocumentParser):
    """HTML, with script/style removed and headings kept."""

    extensions = frozenset({"html", "htm"})

    def parse(self, context: ParseContext) -> ParsedDocument:
        try:
            tree = HTMLParser(read_text(context.path))
        except Exception as exc:  # selectolax raises bare exceptions
            raise DocumentParseError(f"{context.filename!r} is not readable HTML.") from exc

        # Otherwise minified JavaScript becomes the bulk of the "content" and
        # poisons every embedding derived from it.
        tree.strip_tags(["script", "style", "noscript", "iframe", "svg"])

        title = tree.css_first("title")
        blocks: list[TextBlock] = []
        section: str | None = None
        level: int | None = None

        body = tree.css_first("body") or tree.root
        if body is None:
            return ParsedDocument(blocks=[])

        for node in body.traverse(include_text=False):
            tag = node.tag
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                heading = node.text(deep=True, strip=True)
                if heading:
                    level = int(tag[1])
                    section = heading
                    blocks.append(
                        TextBlock(text=heading, section_title=section, heading_level=level)
                    )
            elif tag in {"p", "li", "td", "th", "blockquote", "pre", "figcaption"}:
                content = node.text(deep=True, strip=True)
                if content:
                    blocks.append(
                        TextBlock(
                            text=content[:MAX_BLOCK_CHARS],
                            section_title=section,
                            heading_level=level,
                        )
                    )

        # Some pages are one <div> soup with none of the tags above.
        if not blocks and (fallback := body.text(deep=True, strip=True)):
            blocks = [TextBlock(text=piece) for piece in split_paragraphs(fallback)]

        metadata = {"title": title.text(strip=True)} if title else {}
        return ParsedDocument(blocks=blocks, metadata=metadata)


class DelimitedTextParser(DocumentParser):
    """CSV and TSV.

    Each row becomes one block prefixed with its column names. A bare row of
    values embeds terribly — "2026-03-14, 4820, closed" means nothing without
    its header, whereas "Date: 2026-03-14 | Amount: 4820 | Status: closed"
    retrieves on any of those terms.
    """

    extensions = frozenset({"csv", "tsv"})

    #: A guard against embedding a million-row export one row at a time.
    MAX_ROWS = 5000

    def parse(self, context: ParseContext) -> ParsedDocument:
        text = read_text(context.path)
        if not text.strip():
            return ParsedDocument(blocks=[])

        delimiter = "\t" if context.extension == "tsv" else self._sniff(text)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)

        try:
            rows = list(reader)
        except csv.Error as exc:
            raise DocumentParseError(f"{context.filename!r} is not readable CSV.") from exc

        if not rows:
            return ParsedDocument(blocks=[])

        header = [column.strip() for column in rows[0]]
        blocks = [TextBlock(text=" | ".join(header), section_title="Columns")]

        truncated = len(rows) - 1 > self.MAX_ROWS
        for number, row in enumerate(rows[1 : self.MAX_ROWS + 1], start=2):
            pairs = [
                f"{name}: {value.strip()}"
                for name, value in zip(header, row, strict=False)
                if value.strip()
            ]
            if pairs:
                blocks.append(TextBlock(text=" | ".join(pairs), metadata={"row_number": number}))

        warnings = (f"Only the first {self.MAX_ROWS} rows were indexed.",) if truncated else ()
        return ParsedDocument(
            blocks=blocks,
            metadata={"row_count": len(rows) - 1, "columns": header},
            warnings=warnings,
        )

    @staticmethod
    def _sniff(text: str) -> str:
        try:
            return csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
        except csv.Error:
            return ","
