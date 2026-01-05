# embedding_service.py
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

try:
    from sentence_transformers import SentenceTransformer
except Exception as e:
    SentenceTransformer = None  # type: ignore


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@dataclass(frozen=True)
class EmbeddingConfig:
    model_name: str = DEFAULT_MODEL_NAME
    batch_size: int = 32
    max_chars: int = 10_000  # guardrail for huge bios


class EmbeddingService:
    """
    Production-minded wrapper:
    - lazy-load model once (thread-safe)
    - batch encoding
    - returns unit vectors (cosine similarity becomes dot product)
    """

    def __init__(self, cfg: Optional[EmbeddingConfig] = None):
        self.cfg = cfg or EmbeddingConfig()
        self._lock = threading.RLock()
        self._model: Optional[SentenceTransformer] = None

        if SentenceTransformer is None:
            raise RuntimeError(
                "sentence-transformers is not installed. Run: pip install sentence-transformers"
            )

    @property
    def model_name(self) -> str:
        return self.cfg.model_name

    def _get_model(self) -> SentenceTransformer:
        with self._lock:
            if self._model is None:
                self._model = SentenceTransformer(self.cfg.model_name)
            return self._model

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        model = self._get_model()

        cleaned = []
        for t in texts:
            t = (t or "").strip()
            if len(t) > self.cfg.max_chars:
                t = t[: self.cfg.max_chars]
            cleaned.append(t)

        vectors: List[List[float]] = []
        for i in range(0, len(cleaned), self.cfg.batch_size):
            batch = cleaned[i : i + self.cfg.batch_size]
            emb = model.encode(
                batch,
                normalize_embeddings=True,  # IMPORTANT: unit vectors
                show_progress_bar=False,
            )
            # ensure python floats (jsonable)
            vectors.extend(emb.astype(float).tolist())
        return vectors

    def embed_text(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]


def cosine_sim_unit(a: List[float], b: List[float]) -> float:
    """
    If embeddings are unit-normalized, cosine = dot(a,b).
    """
    av = np.asarray(a, dtype=np.float32)
    bv = np.asarray(b, dtype=np.float32)
    return float(np.dot(av, bv))


def dumps_embedding(vec: List[float]) -> str:
    return json.dumps(vec, separators=(",", ":"))


def loads_embedding(s: str) -> List[float]:
    return json.loads(s)
