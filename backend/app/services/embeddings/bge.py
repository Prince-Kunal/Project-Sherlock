"""Local bge-small embeddings (free, PLAN.md §3) via fastembed: the same BAAI/bge-small-en-v1.5 weights
as sentence-transformers, run on ONNX Runtime instead of PyTorch (a far smaller install)."""

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.services.embeddings.embedder import Embedder

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class BgeEmbedder(Embedder):
    def __init__(self, model_name: str, cache_dir: str, batch_size: int = 32) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._model: TextEmbedding | None = None
        self._lock = asyncio.Lock()

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._load()
        # CPU-bound: keep it off the event loop.
        return await asyncio.to_thread(self._embed_sync, model, list(texts))

    async def _load(self) -> "TextEmbedding":
        async with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding  # import is slow; only pay it when used

                self._model = await asyncio.to_thread(
                    TextEmbedding, self._model_name, cache_dir=self._cache_dir
                )
            return self._model

    def _embed_sync(self, model: "TextEmbedding", texts: list[str]) -> list[list[float]]:
        # fastembed returns L2-normalised vectors for bge models.
        return [vector.tolist() for vector in model.embed(texts, batch_size=self._batch_size)]
