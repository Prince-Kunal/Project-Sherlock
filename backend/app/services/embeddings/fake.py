import hashlib
import math
import re
from collections.abc import Sequence

from app.services.embeddings.embedder import Embedder

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")


class FakeEmbedder(Embedder):
    """Deterministic hashed bag-of-words vectors: texts sharing words get high cosine similarity,
    which keeps similarity-based tests meaningful without loading a model."""

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]
