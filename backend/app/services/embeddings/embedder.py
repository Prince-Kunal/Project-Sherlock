from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.models.company import EMBEDDING_DIM


class Embedder(ABC):
    """Text → L2-normalised vectors. The real bge-small implementation arrives in Phase 3."""

    dim: int = EMBEDDING_DIM

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
