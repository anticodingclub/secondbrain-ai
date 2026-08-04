"""Upload ingestion."""

from app.services.uploads.file_types import (
    SUPPORTED_EXTENSIONS,
    FileCategory,
    FileType,
    detect,
    signature_matches,
)
from app.services.uploads.service import UploadResult, UploadService

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "FileCategory",
    "FileType",
    "UploadResult",
    "UploadService",
    "detect",
    "signature_matches",
]
