"""What we accept, and how we decide.

A browser-supplied ``Content-Type`` is a hint from the client and nothing more —
trivially spoofed, and frequently just wrong (``application/octet-stream`` for
anything unusual). So the extension decides what a file *claims* to be, and for
formats with a reliable signature the leading bytes decide whether that claim
holds.

libmagic would do this more thoroughly, but it is a native dependency that
breaks the zero-install development story on Windows; a table covering the
formats we actually accept is worth more than a dependency covering thousands
we do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class FileCategory(StrEnum):
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    IMAGE = "image"
    TEXT = "text"
    CODE = "code"
    ARCHIVE = "archive"
    AUDIO = "audio"


@dataclass(frozen=True, slots=True)
class FileType:
    extension: str
    mime_type: str
    category: FileCategory
    #: Leading-byte signatures. Empty for formats that genuinely have none
    #: (plain text, source code), where there is nothing to verify.
    signatures: tuple[bytes, ...] = ()


#: ZIP-based Office formats all share the PK signature; the distinction between
#: them lives inside the archive, which is the parser's problem in Phase 4.
_ZIP = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

_TYPES: tuple[FileType, ...] = (
    # Documents
    FileType(".pdf", "application/pdf", FileCategory.DOCUMENT, (b"%PDF-",)),
    FileType(
        ".docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        FileCategory.DOCUMENT,
        _ZIP,
    ),
    FileType(".odt", "application/vnd.oasis.opendocument.text", FileCategory.DOCUMENT, _ZIP),
    FileType(".rtf", "application/rtf", FileCategory.DOCUMENT, (b"{\\rtf",)),
    FileType(".epub", "application/epub+zip", FileCategory.DOCUMENT, _ZIP),
    # Spreadsheets
    FileType(
        ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        FileCategory.SPREADSHEET,
        _ZIP,
    ),
    FileType(".csv", "text/csv", FileCategory.SPREADSHEET),
    FileType(".tsv", "text/tab-separated-values", FileCategory.SPREADSHEET),
    # Presentations
    FileType(
        ".pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        FileCategory.PRESENTATION,
        _ZIP,
    ),
    # Images (OCR in Phase 4)
    FileType(".png", "image/png", FileCategory.IMAGE, (b"\x89PNG\r\n\x1a\n",)),
    FileType(".jpg", "image/jpeg", FileCategory.IMAGE, (b"\xff\xd8\xff",)),
    FileType(".jpeg", "image/jpeg", FileCategory.IMAGE, (b"\xff\xd8\xff",)),
    FileType(".webp", "image/webp", FileCategory.IMAGE, (b"RIFF",)),
    FileType(".gif", "image/gif", FileCategory.IMAGE, (b"GIF87a", b"GIF89a")),
    FileType(".bmp", "image/bmp", FileCategory.IMAGE, (b"BM",)),
    FileType(".tiff", "image/tiff", FileCategory.IMAGE, (b"II*\x00", b"MM\x00*")),
    # Text and markup
    FileType(".txt", "text/plain", FileCategory.TEXT),
    FileType(".md", "text/markdown", FileCategory.TEXT),
    FileType(".markdown", "text/markdown", FileCategory.TEXT),
    FileType(".rst", "text/x-rst", FileCategory.TEXT),
    FileType(".org", "text/x-org", FileCategory.TEXT),
    FileType(".html", "text/html", FileCategory.TEXT),
    FileType(".htm", "text/html", FileCategory.TEXT),
    FileType(".xml", "application/xml", FileCategory.TEXT),
    FileType(".json", "application/json", FileCategory.TEXT),
    FileType(".yaml", "application/yaml", FileCategory.TEXT),
    FileType(".yml", "application/yaml", FileCategory.TEXT),
    FileType(".toml", "application/toml", FileCategory.TEXT),
    FileType(".ini", "text/plain", FileCategory.TEXT),
    FileType(".log", "text/plain", FileCategory.TEXT),
    # Code
    *(
        FileType(ext, "text/plain", FileCategory.CODE)
        for ext in (
            ".py",
            ".pyi",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            ".java",
            ".kt",
            ".go",
            ".rs",
            ".rb",
            ".php",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".cc",
            ".cs",
            ".swift",
            ".scala",
            ".sh",
            ".bash",
            ".zsh",
            ".ps1",
            ".sql",
            ".r",
            ".lua",
            ".pl",
            ".ex",
            ".exs",
            ".erl",
            ".hs",
            ".clj",
            ".dart",
            ".vue",
            ".svelte",
            ".css",
            ".scss",
            ".less",
            ".graphql",
            ".proto",
            ".tf",
            ".dockerfile",
            ".gradle",
            ".cmake",
            ".m",
            ".mm",
            ".vb",
            ".asm",
        )
    ),
    # Archives (expanded in Phase 3 follow-up / repo import)
    FileType(".zip", "application/zip", FileCategory.ARCHIVE, _ZIP),
    # Audio (transcription is a later phase; accepted so it can be queued)
    FileType(".mp3", "audio/mpeg", FileCategory.AUDIO, (b"ID3", b"\xff\xfb")),
    FileType(".wav", "audio/wav", FileCategory.AUDIO, (b"RIFF",)),
    FileType(".m4a", "audio/mp4", FileCategory.AUDIO),
    FileType(".flac", "audio/flac", FileCategory.AUDIO, (b"fLaC",)),
    FileType(".ogg", "audio/ogg", FileCategory.AUDIO, (b"OggS",)),
)

#: Formats deliberately refused, with what to do instead. The legacy binary
#: Office formats need native tooling (antiword, LibreOffice) that would break
#: the two-command setup. Accepting a file nothing can read is worse than
#: refusing it: it uploads happily and then never becomes searchable, and the
#: user has no way to find out why.
UNSUPPORTED_HINTS: dict[str, str] = {
    ".doc": "Legacy .doc is not supported. Save it as .docx and upload again.",
    ".xls": "Legacy .xls is not supported. Save it as .xlsx and upload again.",
    ".ppt": "Legacy .ppt is not supported. Save it as .pptx and upload again.",
    ".pages": "Apple Pages is not supported. Export it as .docx or PDF.",
    ".numbers": "Apple Numbers is not supported. Export it as .xlsx or CSV.",
    ".key": "Apple Keynote is not supported. Export it as .pptx or PDF.",
}

BY_EXTENSION: dict[str, FileType] = {file_type.extension: file_type for file_type in _TYPES}

#: Enough for every signature above with room to spare.
SIGNATURE_PROBE_BYTES = 32

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(BY_EXTENSION)


def detect(filename: str) -> FileType | None:
    """Resolve a filename to a supported type, or None.

    Extensionless files named exactly like known tooling (``Dockerfile``,
    ``Makefile``) are treated as code, since a repository import will meet
    plenty of them.
    """
    path = Path(filename)
    if found := BY_EXTENSION.get(path.suffix.lower()):
        return found

    stem = path.name.lower()
    if stem in {"dockerfile", "makefile", "rakefile", "gemfile", "procfile", "justfile"}:
        return FileType(f".{stem}", "text/plain", FileCategory.CODE)
    return None


def signature_matches(file_type: FileType, head: bytes) -> bool:
    """Whether the leading bytes are consistent with the claimed type.

    Types without signatures always pass — plain text has no magic number, and
    inventing a heuristic for it would reject legitimate files.
    """
    if not file_type.signatures:
        return True
    return any(head.startswith(signature) for signature in file_type.signatures)
