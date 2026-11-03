import re
from dataclasses import dataclass

from app.ai.embeddings import embed_query
from app.ai.rag import get_collection
from app.core.config import settings

_SMALL_TALK_WORDS = {
    "hi", "hello", "hey", "hiya", "howdy", "good", "morning", "afternoon", "evening",
    "thanks", "thank", "you", "thx", "ok", "okay", "bye", "goodbye", "see", "later",
    "how", "are", "is", "it", "going", "doing", "there", "so", "much", "very", "a",
    "lot", "great", "cool", "nice", "yes", "no", "yep",
}


class KnowledgeBaseEmptyError(RuntimeError):
    pass


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    text: str
    source: str
    category: str
    title: str
    section: str
    similarity: float


def needs_policy_lookup(message: str) -> bool:
    """False only for short messages made entirely of greeting/thanks words."""
    words = re.findall(r"[a-z']+", message.lower())
    is_small_talk = 0 < len(words) <= 6 and all(w in _SMALL_TALK_WORDS for w in words)
    return not is_small_talk


def retrieve(
    question: str,
    top_k: int | None = None,
    min_similarity: float | None = None,
) -> list[RetrievedChunk]:
    """Return up to top_k chunks scoring at least min_similarity, best first."""
    question = question.strip()
    if not question:
        return []

    k = settings.retrieval_top_k if top_k is None else top_k
    threshold = settings.retrieval_min_similarity if min_similarity is None else min_similarity

    collection = get_collection()
    total = collection.count()
    if total == 0:
        raise KnowledgeBaseEmptyError("Knowledge base is empty. Run: python -m app.ai.rag")

    result = collection.query(
        query_embeddings=[embed_query(question).tolist()],
        n_results=min(k, total),
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[RetrievedChunk] = []
    for chunk_id, text, meta, distance in zip(
        result["ids"][0],
        result["documents"][0],
        result["metadatas"][0],
        result["distances"][0],
    ):
        similarity = 1.0 - distance / 2.0
        if similarity < threshold:
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=chunk_id,
                text=text,
                source=meta["source"],
                category=meta["category"],
                title=meta["title"],
                section=meta["section"],
                similarity=round(similarity, 4),
            )
        )
    return chunks