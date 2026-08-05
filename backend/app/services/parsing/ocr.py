"""Optical character recognition for images.

OCR is the one capability here that needs a *native* binary — Tesseract — which
cannot be installed by pip and will be absent on most machines that clone this
project. Everything in this module is built around that fact.

An image uploaded without Tesseract present is still stored, still listed and
still deduplicated; it is simply marked as having no extractable text, with a
warning saying what to install. Making the upload fail instead would punish the
user for a dependency they were never told about, and hard-failing at import
time would take the whole application down over an optional feature.
"""

from __future__ import annotations

import functools
import shutil

from app.core.logging import get_logger
from app.services.parsing.base import (
    DocumentParser,
    ParseContext,
    ParsedDocument,
    TextBlock,
)

logger = get_logger(__name__)

INSTALL_HINT = (
    "OCR is unavailable because Tesseract is not installed. "
    "Install it from https://github.com/UB-Mannheim/tesseract/wiki on Windows, "
    "`brew install tesseract` on macOS, or `apt install tesseract-ocr` on Linux, "
    'then install the Python extra with `pip install -e "backend[ocr]"`.'
)


@functools.lru_cache(maxsize=1)
def ocr_availability() -> tuple[bool, str | None]:
    """Whether OCR can run, and why not if it cannot.

    Cached because it shells out to locate a binary, and the answer cannot
    change while the process is alive. Returns a reason rather than a bare
    bool so the user is told which of the two halves is missing — the Python
    package or the native binary — since the fix differs.
    """
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False, (
            'The OCR extra is not installed. Run: pip install -e "backend[ocr]" '
            "(Tesseract itself is also required)."
        )

    if shutil.which("tesseract") is None:
        import pytesseract as _pytesseract

        # pytesseract can be pointed at an explicit path, so honour that before
        # concluding the binary is missing.
        configured = _pytesseract.pytesseract.tesseract_cmd
        if configured and shutil.which(configured) is None and configured != "tesseract":
            return False, INSTALL_HINT
        if not configured or configured == "tesseract":
            return False, INSTALL_HINT

    return True, None


class ImageParser(DocumentParser):
    """Extracts text from images, when OCR is available."""

    extensions = frozenset({"png", "jpg", "jpeg", "webp", "gif", "bmp", "tiff"})

    #: Tesseract's own confidence, 0-100. Below this the "text" is usually
    #: noise from textures and edges, which is worse than nothing: it pollutes
    #: the index with tokens that match nothing a user would ever type.
    MIN_CONFIDENCE = 45.0

    def parse(self, context: ParseContext) -> ParsedDocument:
        available, reason = ocr_availability()
        if not available:
            logger.info("ocr_unavailable", filename=context.filename)
            return ParsedDocument(
                blocks=[],
                metadata={"ocr": "unavailable"},
                warnings=(reason or INSTALL_HINT,),
            )

        import pytesseract
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(context.path) as image:
                # Tesseract expects 8-bit; palette and RGBA images otherwise
                # produce garbage or raise.
                prepared = image.convert("L")
                data = pytesseract.image_to_data(prepared, output_type=pytesseract.Output.DICT)
                width, height = image.size
        except UnidentifiedImageError as exc:
            from app.core.exceptions import DocumentParseError

            raise DocumentParseError(f"{context.filename!r} is not a readable image.") from exc
        except Exception as exc:
            # A Tesseract crash on one image must not fail the whole upload.
            logger.warning("ocr_failed", filename=context.filename, error=str(exc))
            return ParsedDocument(
                blocks=[],
                metadata={"ocr": "failed"},
                warnings=(f"Text extraction failed for this image: {exc}",),
            )

        lines = _group_into_lines(data, self.MIN_CONFIDENCE)
        blocks = [
            TextBlock(text=text, page_number=1, metadata={"ocr_confidence": confidence})
            for text, confidence in lines
        ]

        warnings = () if blocks else ("No readable text was found in this image.",)
        mean = sum(c for _, c in lines) / len(lines) if lines else 0.0

        return ParsedDocument(
            blocks=blocks,
            page_count=1,
            metadata={
                "ocr": "ok",
                "ocr_mean_confidence": round(mean, 1),
                "width": width,
                "height": height,
            },
            warnings=warnings,
        )


def _group_into_lines(
    data: dict[str, list[object]], min_confidence: float
) -> list[tuple[str, float]]:
    """Reassemble Tesseract's per-word output into lines.

    `image_to_data` returns one row per word. Joining every word into one blob
    would destroy the line structure that makes an address or a table readable,
    so words are regrouped by the block/paragraph/line ids Tesseract supplies.
    """
    grouped: dict[tuple[object, object, object], list[tuple[str, float]]] = {}

    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])  # type: ignore[arg-type]
        except (ValueError, TypeError, KeyError, IndexError):
            continue
        if confidence < min_confidence:
            continue

        key = (
            data["block_num"][index],
            data["par_num"][index],
            data["line_num"][index],
        )
        grouped.setdefault(key, []).append((text, confidence))

    lines: list[tuple[str, float]] = []
    for words in grouped.values():
        text = " ".join(word for word, _ in words)
        mean = sum(confidence for _, confidence in words) / len(words)
        lines.append((text, round(mean, 1)))
    return lines
