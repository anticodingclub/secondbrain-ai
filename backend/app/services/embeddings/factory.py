"""Selects the embedding provider from configuration."""

from __future__ import annotations

from app.core.config import EmbeddingProviderName, Settings
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.fastembed_provider import FastEmbedProvider
from app.services.embeddings.ollama_provider import OllamaEmbeddingProvider
from app.services.embeddings.sentence_transformers_provider import SentenceTransformersProvider


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    match settings.embedding_provider:
        case EmbeddingProviderName.FASTEMBED:
            return FastEmbedProvider(
                settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                batch_size=settings.embedding_batch_size,
            )
        case EmbeddingProviderName.SENTENCE_TRANSFORMERS:
            return SentenceTransformersProvider(
                settings.embedding_model,
                dimensions=settings.embedding_dimensions,
                batch_size=settings.embedding_batch_size,
            )
        case EmbeddingProviderName.OLLAMA:
            return OllamaEmbeddingProvider(
                settings.embedding_model,
                base_url=settings.ollama_base_url,
                dimensions=settings.embedding_dimensions,
                batch_size=settings.embedding_batch_size,
            )
