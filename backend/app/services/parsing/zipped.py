"""Formats that are a ZIP of XML, plus RTF.

EPUB and ODT are both archives of markup, so neither needs a dedicated library
— `zipfile` plus the HTML parser already present does the job without adding a
dependency for each.
"""

from __future__ import annotations

import re
import zipfile
from typing import ClassVar
from xml.etree import ElementTree

from selectolax.parser import HTMLParser

from app.core.exceptions import DocumentParseError
from app.core.logging import get_logger
from app.services.parsing.base import (
    DocumentParser,
    ParseContext,
    ParsedDocument,
    TextBlock,
)
from app.services.parsing.text import MAX_BLOCK_CHARS, split_paragraphs

logger = get_logger(__name__)


def _open_archive(context: ParseContext) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(context.path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentParseError(
            f"{context.filename!r} is not a readable {context.extension.upper()} file."
        ) from exc


class EpubParser(DocumentParser):
    """EPUB e-books, one section per chapter document.

    Chapters are read in spine order rather than archive order, because a ZIP
    preserves neither reading order nor any useful ordering at all — taking
    files as they come would shuffle the book.
    """

    extensions = frozenset({"epub"})

    _OPF_NS: ClassVar[dict[str, str]] = {
        "opf": "http://www.idpf.org/2007/opf",
        "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    }

    def parse(self, context: ParseContext) -> ParsedDocument:
        blocks: list[TextBlock] = []
        title: str | None = None

        with _open_archive(context) as archive:
            spine = self._reading_order(archive)

            for number, name in enumerate(spine, start=1):
                try:
                    markup = archive.read(name).decode("utf-8", errors="replace")
                except KeyError:
                    continue

                tree = HTMLParser(markup)
                tree.strip_tags(["script", "style"])

                chapter = tree.css_first("h1, h2, title")
                chapter_title = chapter.text(strip=True) if chapter else None
                title = title or chapter_title

                body = tree.css_first("body") or tree.root
                if body is None:
                    continue

                for node in body.css("p, li, blockquote, h1, h2, h3"):
                    text = node.text(deep=True, strip=True)
                    if text:
                        blocks.append(
                            TextBlock(
                                text=text[:MAX_BLOCK_CHARS],
                                page_number=number,
                                section_title=chapter_title,
                            )
                        )

        return ParsedDocument(
            blocks=blocks,
            page_count=len({b.page_number for b in blocks}) or None,
            metadata={"title": title} if title else {},
        )

    def _reading_order(self, archive: zipfile.ZipFile) -> list[str]:
        """Resolve the spine from the OPF, falling back to any XHTML present."""
        try:
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = container.find(".//container:rootfile", self._OPF_NS)
            opf_path = rootfile.get("full-path") if rootfile is not None else None
            if not opf_path:
                raise KeyError

            opf = ElementTree.fromstring(archive.read(opf_path))
            base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

            manifest = {
                item.get("id"): item.get("href")
                for item in opf.findall(".//opf:manifest/opf:item", self._OPF_NS)
            }
            order = [
                base + href
                for ref in opf.findall(".//opf:spine/opf:itemref", self._OPF_NS)
                if (href := manifest.get(ref.get("idref")))
            ]
            if order:
                return order
        except (KeyError, ElementTree.ParseError, AttributeError) as exc:
            logger.debug("epub_spine_unreadable", error=str(exc))

        return sorted(
            name
            for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
        )


class OdtParser(DocumentParser):
    """OpenDocument text, keeping heading structure."""

    extensions = frozenset({"odt"})

    _TEXT_NS = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"

    def parse(self, context: ParseContext) -> ParsedDocument:
        with _open_archive(context) as archive:
            try:
                content = archive.read("content.xml")
            except KeyError as exc:
                raise DocumentParseError(f"{context.filename!r} is missing its content.") from exc

        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError as exc:
            raise DocumentParseError(f"{context.filename!r} contains malformed content.") from exc

        blocks: list[TextBlock] = []
        section: str | None = None
        level: int | None = None

        for element in root.iter():
            tag = element.tag
            if tag == f"{self._TEXT_NS}h":
                # itertext() rather than .text: ODT splits runs across spans,
                # so .text alone returns only the fragment before the first one.
                heading = "".join(element.itertext()).strip()
                if heading:
                    raw_level = element.get(f"{self._TEXT_NS}outline-level", "1")
                    level = int(raw_level) if raw_level.isdigit() else 1
                    section = heading
                    blocks.append(
                        TextBlock(text=heading, section_title=section, heading_level=level)
                    )
            elif tag == f"{self._TEXT_NS}p":
                text = "".join(element.itertext()).strip()
                if text:
                    blocks.append(
                        TextBlock(
                            text=text[:MAX_BLOCK_CHARS],
                            section_title=section,
                            heading_level=level,
                        )
                    )

        return ParsedDocument(blocks=blocks)


class RtfParser(DocumentParser):
    """Rich Text Format.

    RTF is a control-word language, not markup, and a complete implementation
    is a large undertaking. This strips control words, groups and escapes,
    which covers documents produced by word processors — the realistic case
    for a personal archive. Exotic embedded objects degrade to missing text
    rather than to a crash.
    """

    extensions = frozenset({"rtf"})

    _DESTINATION = re.compile(
        r"\{\\\*?\\(?:fonttbl|colortbl|stylesheet|info|pict|object|header|footer)"
        r"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
        re.DOTALL,
    )
    _UNICODE = re.compile(r"\\u(-?\d+)\??")
    _HEX = re.compile(r"\\'([0-9a-fA-F]{2})")
    _CONTROL = re.compile(r"\\([a-zA-Z]+)(-?\d+)? ?")

    def parse(self, context: ParseContext) -> ParsedDocument:
        raw = context.path.read_bytes().decode("latin-1", errors="replace")
        if not raw.lstrip().startswith(r"{\rtf"):
            raise DocumentParseError(f"{context.filename!r} is not a valid RTF file.")

        text = self._DESTINATION.sub("", raw)
        text = self._UNICODE.sub(lambda m: self._codepoint(m.group(1)), text)
        text = self._HEX.sub(
            lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), text
        )

        # Paragraph breaks must survive control-word stripping, or the entire
        # document collapses into one unciteable block.
        text = re.sub(r"\\(?:par|line|pard)\b ?", "\n\n", text)
        text = re.sub(r"\\tab\b ?", "\t", text)
        text = self._CONTROL.sub("", text)
        text = text.replace("\\{", "{").replace("\\}", "}").replace("\\\\", "\\")
        text = re.sub(r"[{}]", "", text)

        blocks = [TextBlock(text=piece) for piece in split_paragraphs(text)]
        return ParsedDocument(blocks=blocks)

    @staticmethod
    def _codepoint(value: str) -> str:
        try:
            number = int(value)
        except ValueError:
            return ""
        # RTF writes codepoints above 32767 as negative signed 16-bit values.
        if number < 0:
            number += 65536
        return chr(number) if 0 < number < 0x110000 else ""
