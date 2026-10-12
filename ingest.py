"""Load the dataset, chunk it, embed it and store it in ChromaDB (PRD 6.2).

    python ingest.py

Four collections, rebuilt from scratch on every run (safe to re-run):

    signed_contracts      Data/signed_contracts/*.md
    negotiation_history   Data/negotiation_notes.md + Data/meeting_notes/*.md
    principles            Data/principles.md + Data/atliq_entities.md
    commitments           Data/commitments.json (one document per entry)

Incoming drafts are NOT indexed: they are read in full at review time.
Every chunk carries source_file, source_type, counterparty and section.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

import config
import rules


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """Local all-MiniLM-L6-v2: free, no API key, nothing leaves the machine."""
    return HuggingFaceEmbeddings(
        model_name=config.EMBEDDING_MODEL,
        encode_kwargs={"normalize_embeddings": True},
    )


def get_store(name: str) -> Chroma:
    return Chroma(
        collection_name=name,
        embedding_function=get_embeddings(),
        persist_directory=str(config.CHROMA_DIR),
    )


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n## ", "\n\n", "\n", ". ", " "],
    )


_HEADING = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
_CLAUSE = re.compile(r"^\s*(?:\*\*)?(\d+(?:\.\d+)*)[.)]?\s", re.MULTILINE)


def _section_for(full_text: str, chunk: str) -> str:
    """The heading in force where the chunk starts, plus its first clause number."""
    start = full_text.find(chunk[:80])
    before = full_text[: max(start, 0)]
    own = _HEADING.match(chunk.lstrip())
    headings = _HEADING.findall(before)
    if own:
        heading = own.group(1).strip(" *")
    else:
        heading = headings[-1].strip(" *") if headings else ""
    clause = _CLAUSE.search(chunk)
    if clause and heading:
        return f"{heading} / clause {clause.group(1)}"
    if clause:
        return f"clause {clause.group(1)}"
    return heading or "preamble"


def _counterparty_from_filename(name: str, tracker: list[dict[str, str]]) -> str:
    lowered = name.lower()
    for row in tracker:
        key = rules.counterparty_key(row["counterparty"]).replace(" ", "_")
        if key and len(key) >= 4 and key in lowered:
            return row["counterparty"]
    return ""


def _chunk_file(path: Path, source_type: str, counterparty: str) -> list[Document]:
    text = path.read_text(encoding="utf-8")
    documents = []
    for chunk in _splitter().split_text(text):
        documents.append(Document(
            page_content=chunk,
            metadata={
                "source_file": path.name,
                "source_type": source_type,
                "counterparty": counterparty,
                "section": _section_for(text, chunk),
            },
        ))
    return documents


def load_signed(tracker) -> list[Document]:
    documents = []
    for path in sorted(config.SIGNED_DIR.glob("*.md")):
        documents += _chunk_file(path, "signed_contract", _counterparty_from_filename(path.name, tracker))
    return documents


def load_history(tracker) -> list[Document]:
    """Negotiation notes split per counterparty entry, plus meeting notes."""
    documents = []
    text = config.NEGOTIATION_NOTES.read_text(encoding="utf-8")
    entries = re.split(r"\n(?=\*\*[^*\n]+\*\*\s*\n)", text)
    for entry in entries:
        header = re.match(r"\*\*([^*\n]+)\*\*", entry.strip())
        section = header.group(1).strip() if header else "introduction"
        counterparty = ""
        if header:
            name = re.split(r"\s+[—(-]", section)[0]
            counterparty = next(
                (row["counterparty"] for row in tracker if rules.same_counterparty(row["counterparty"], name)),
                name,
            )
        for chunk in _splitter().split_text(entry.strip()):
            documents.append(Document(
                page_content=chunk,
                metadata={
                    "source_file": config.NEGOTIATION_NOTES.name,
                    "source_type": "negotiation_note",
                    "counterparty": counterparty,
                    "section": section,
                },
            ))
    for path in sorted(config.MEETING_NOTES_DIR.glob("*.md")):
        documents += _chunk_file(path, "meeting_note", _counterparty_from_filename(path.name, tracker))
    return documents


def load_principles() -> list[Document]:
    return (
        _chunk_file(config.PRINCIPLES_FILE, "principles", "")
        + _chunk_file(config.ENTITIES_FILE, "entities", "")
    )


def commitment_documents(entries: list[dict]) -> list[Document]:
    documents = []
    for entry in entries:
        waivers = "; ".join(f"{w['covers']} ({w['source_file']})" for w in entry.get("waivers", [])) or "none"
        status = "confirmed by a person" if entry.get("confirmed_by_human") else "UNCONFIRMED proposal (not used in reviews)"
        content = (
            f"Commitment {entry['id']} ({status}). Type: {entry['type']}. "
            f"Counterparty: {entry['counterparty']}. AtliQ entity: {entry.get('atliq_entity')}. "
            f"Source: {entry['source_file']} clause {entry['clause']}.\n"
            f"Summary: {entry['summary']}\n"
            f"Clause text: {entry.get('clause_text', '')}\n"
            f"Regions: {', '.join(entry.get('regions', [])) or 'no region limit'}. "
            f"Applies to affiliates: {entry.get('applies_to_affiliates')}. "
            f"Ends: {entry.get('end_date') or 'no end date'}. Waivers: {waivers}."
        )
        documents.append(Document(
            page_content=content,
            metadata={
                "source_file": entry["source_file"],
                "source_type": "commitment",
                "counterparty": entry["counterparty"],
                "section": f"{entry['id']} / clause {entry['clause']}",
            },
        ))
    return documents


def rebuild(name: str, documents: list[Document]) -> int:
    store = get_store(name)
    existing = store.get(include=[])["ids"]
    if existing:
        store.delete(ids=existing)
    if documents:
        store.add_documents(documents, ids=[f"{name}-{i}" for i in range(len(documents))])
    return len(documents)


def ingest_commitments() -> int:
    """Re-index only the register (after Rebuild register / Confirm in the UI)."""
    return rebuild(config.COLLECTION_COMMITMENTS, commitment_documents(rules.load_register()))


def collection_counts() -> dict[str, int]:
    if not config.CHROMA_DIR.exists():
        return {}
    return {name: len(get_store(name).get(include=[])["ids"]) for name in config.COLLECTIONS}


def main() -> None:
    tracker = rules.load_tracker()
    counts = {
        config.COLLECTION_SIGNED: rebuild(config.COLLECTION_SIGNED, load_signed(tracker)),
        config.COLLECTION_HISTORY: rebuild(config.COLLECTION_HISTORY, load_history(tracker)),
        config.COLLECTION_PRINCIPLES: rebuild(config.COLLECTION_PRINCIPLES, load_principles()),
        config.COLLECTION_COMMITMENTS: ingest_commitments(),
    }
    print(f"Vector store: {config.CHROMA_DIR}")
    for name, count in counts.items():
        print(f"  {name:<20} {count:>4} chunks")


if __name__ == "__main__":
    main()
