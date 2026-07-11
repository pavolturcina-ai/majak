"""Embedding provider seam.

pgvector columns are dimension 1024. A real deployment can wire Voyage AI
(Anthropic's recommended embeddings) or any 1024-dim model here. Offline, this
returns None so vectors are simply skipped — semantic dedup degrades to lexical,
nothing breaks.
"""

from __future__ import annotations

import logging

from majak.config import settings

logger = logging.getLogger(__name__)


class Embedder:
    @property
    def available(self) -> bool:
        # No embedding backend is configured by default; wire one here.
        return False

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        if not self.available:
            return [None for _ in texts]
        raise NotImplementedError("Configure an embedding backend (e.g. Voyage AI) here.")

    async def embed_one(self, text: str) -> list[float] | None:
        return (await self.embed([text]))[0]

    @property
    def dim(self) -> int:
        return settings.embedding_dim


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        _embedder = Embedder()
    return _embedder
