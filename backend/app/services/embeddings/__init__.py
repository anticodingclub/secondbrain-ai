"""Embedding providers behind a single interface."""

from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.factory import build_embedding_provider

__all__ = ["EmbeddingProvider", "build_embedding_provider"]
