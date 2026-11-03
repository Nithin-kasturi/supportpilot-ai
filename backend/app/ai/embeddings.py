from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(settings.embedding_model_name)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return a (len(texts), 384) array of unit-length vectors."""
    return get_model().encode(
        texts,
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    )


def embed_query(text: str) -> np.ndarray:
    return embed_texts([text])[0]