import argparse
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.ai.embeddings import embed_texts
from app.core.config import settings

COLLECTION_NAME = "policies"


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    text: str
    source: str
    category: str
    title: str
    section: str


def clean_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (document title, [(section heading, section body), ...])."""
    title = ""
    sections: list[tuple[str, list[str]]] = []
    for line in text.split("\n"):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif line.startswith("# ") and not title:
            title = line[2:].strip()
        elif sections:
            sections[-1][1].append(line)
    return title, [(heading, "\n".join(body).strip()) for heading, body in sections]


def split_body(body: str, max_chars: int, overlap_chars: int) -> list[str]:
    """Split a section at line boundaries, repeating trailing lines as overlap."""
    lines = [line for line in body.split("\n") if line.strip()]
    parts: list[str] = []
    current: list[str] = []
    for line in lines:
        if current and len("\n".join(current + [line])) > max_chars:
            parts.append("\n".join(current))
            carry: list[str] = []
            size = 0
            for previous in reversed(current):
                if size + len(previous) > overlap_chars:
                    break
                carry.insert(0, previous)
                size += len(previous)
            current = carry
        current.append(line)
    if current:
        parts.append("\n".join(current))
    return parts


def chunk_document(path: Path) -> list[Chunk]:
    text = clean_text(path.read_text(encoding="utf-8-sig"))
    title, sections = parse_sections(text)
    category = path.stem.removesuffix("_policy")
    chunks: list[Chunk] = []
    for section_index, (heading, body) in enumerate(sections):
        parts = split_body(body, settings.chunk_max_chars, settings.chunk_overlap_chars)
        for part_index, part in enumerate(parts):
            chunks.append(
                Chunk(
                    chunk_id=f"{path.stem}-{section_index:02d}-{part_index}",
                    text=f"{title} - {heading}\n{part}",
                    source=path.name,
                    category=category,
                    title=title,
                    section=heading,
                )
            )
    return chunks


def load_all_chunks() -> list[Chunk]:
    policies_dir = settings.policies_dir

    unexpected = [
        p.name
        for p in policies_dir.iterdir()
        if p.is_file() and p.suffix != ".md" and p.name != ".gitkeep"
    ]
    if unexpected:
        raise ValueError(f"Non-Markdown files in {policies_dir}: {unexpected}. Fix the filename.")

    files = sorted(policies_dir.glob("*.md"))
    if not files:
        raise FileNotFoundError(f"No policy files found in {policies_dir}")

    chunks: list[Chunk] = []
    for file in files:
        file_chunks = chunk_document(file)
        if not file_chunks:
            raise ValueError(f"{file.name} produced no chunks (empty file or no '## ' sections).")
        chunks.extend(file_chunks)
    return chunks


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(settings.chroma_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_collection():
    return get_client().get_or_create_collection(name=COLLECTION_NAME)


def ingest(rebuild: bool = False) -> dict[str, int]:
    chunks = load_all_chunks()
    client = get_client()

    if rebuild:
        existing = {c if isinstance(c, str) else c.name for c in client.list_collections()}
        if COLLECTION_NAME in existing:
            client.delete_collection(COLLECTION_NAME)

    collection = get_collection()
    collection.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embed_texts([c.text for c in chunks]).tolist(),
        metadatas=[
            {"source": c.source, "category": c.category, "title": c.title, "section": c.section}
            for c in chunks
        ],
    )

    current_ids = {c.chunk_id for c in chunks}
    stale = [i for i in collection.get()["ids"] if i not in current_ids]
    if stale:
        collection.delete(ids=stale)

    return {"chunks": len(chunks), "stale_removed": len(stale), "total_in_store": collection.count()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest policy documents into ChromaDB.")
    parser.add_argument("--rebuild", action="store_true", help="Drop the collection and rebuild it.")
    args = parser.parse_args()
    print(ingest(rebuild=args.rebuild))


if __name__ == "__main__":
    main()