"""Shared RAG pipeline: load → chunk → embed → query."""

import logging
import re
from pathlib import Path
import chromadb
from sentence_transformers import SentenceTransformer

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CHROMA_DIR = str(BASE_DIR / "chroma_db")

EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
COLLECTION_NAME = "scheme_docs_e5"
MAX_CHUNK_LENGTH = 1500
MIN_CHUNK_LENGTH = 50

logger = logging.getLogger(__name__)

_SECTION_DELIM_RE = re.compile(r"^={3,}\s*$")
_SUBSECTION_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+)$")
_HEADER_FIELDS = {"Level": "level", "Category": "category", "Key Benefit": "key_benefit"}

# Lazy-loaded model singleton
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    """Load the embedding model (cached after first call)."""
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _embed(texts: list[str], prefix: str, show_progress: bool = False) -> list[list[float]]:
    """Embed texts with the given E5 prefix ('passage: ' or 'query: ')."""
    model = _get_model()
    prefixed = [f"{prefix}{t}" for t in texts]
    return model.encode(
        prefixed,
        batch_size=32,
        show_progress_bar=show_progress,
        normalize_embeddings=True,
    ).tolist()


def _get_client() -> chromadb.ClientAPI:
    """Return a persistent ChromaDB client."""
    return chromadb.PersistentClient(path=CHROMA_DIR)


# ---------------------------------------------------------------------------
# Structural document parsing
# ---------------------------------------------------------------------------

def _parse_header(lines: list[str]) -> tuple[dict, int]:
    """Parse the header block at the top of a scheme file.

    Returns (metadata dict, index of first body line).
    """
    metadata: dict[str, str] = {}
    if not lines:
        return metadata, 0

    metadata["scheme_name"] = lines[0].strip()
    body_start = 1

    for i in range(1, len(lines)):
        line = lines[i].strip()
        if _SECTION_DELIM_RE.match(line):
            body_start = i
            break
        if not line:
            body_start = i + 1
            continue
        for prefix, key in _HEADER_FIELDS.items():
            if line.startswith(f"{prefix}:"):
                metadata[key] = line[len(prefix) + 1 :].strip()
                break
        body_start = i + 1

    return metadata, body_start


def _split_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Split body lines on ``===`` delimited section titles.

    Returns a list of ``(section_title, content_lines)`` tuples.
    """
    sections: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        if _SECTION_DELIM_RE.match(lines[i].strip()):
            if i + 2 < len(lines) and _SECTION_DELIM_RE.match(lines[i + 2].strip()):
                title = lines[i + 1].strip()
                i += 3
                content: list[str] = []
                while i < len(lines) and not _SECTION_DELIM_RE.match(lines[i].strip()):
                    content.append(lines[i])
                    i += 1
                sections.append((title, content))
            else:
                i += 1
        else:
            i += 1
    return sections


def _chunk_section(
    section_title: str,
    content_lines: list[str],
    max_length: int = MAX_CHUNK_LENGTH,
) -> list[dict]:
    """Chunk a single section, splitting at subsection boundaries if too long.

    Returns a list of ``{"section_title": ..., "text": ...}`` dicts.
    """
    full_text = "\n".join(line.rstrip() for line in content_lines).strip()

    # Short enough → keep as one chunk
    if len(full_text) <= max_length:
        return [{"section_title": section_title, "text": full_text}]

    # Find numbered-subsection boundary lines (e.g. "5.1 Working Capital …")
    boundaries = [
        i for i, line in enumerate(content_lines) if _SUBSECTION_RE.match(line.strip())
    ]

    if not boundaries:
        # No subsection markers to split on → return as one (oversized) chunk
        return [{"section_title": section_title, "text": full_text}]

    # Build ordered text blocks: pre-subsection intro, then each subsection
    blocks: list[tuple[str, str, str]] = []  # (num, title, text)

    if boundaries[0] > 0:
        pre_text = "\n".join(
            line.rstrip() for line in content_lines[: boundaries[0]]
        ).strip()
        if pre_text:
            blocks.append(("", "", pre_text))

    for j, start in enumerate(boundaries):
        end = boundaries[j + 1] if j + 1 < len(boundaries) else len(content_lines)
        m = _SUBSECTION_RE.match(content_lines[start].strip())
        num, title = m.group(1), m.group(2)
        block_text = "\n".join(
            line.rstrip() for line in content_lines[start:end]
        ).strip()
        blocks.append((num, title, block_text))

    # Group blocks into chunks that stay under max_length
    chunks: list[dict] = []
    current_parts: list[str] = []
    current_length = 0

    for _num, _title, text in blocks:
        if current_length + len(text) > max_length and current_parts:
            chunk_text = f"{section_title}\n\n" + "\n\n".join(current_parts)
            chunks.append({"section_title": section_title, "text": chunk_text})
            current_parts = []
            current_length = 0
        current_parts.append(text)
        current_length += len(text)

    if current_parts:
        chunk_text = f"{section_title}\n\n" + "\n\n".join(current_parts)
        chunks.append({"section_title": section_title, "text": chunk_text})

    return chunks


def _parse_file(filepath: Path) -> list[dict]:
    """Parse one ``.txt`` scheme file into structured chunks.

    Returns a list of ``{"text": ..., "metadata": {...}}`` dicts.
    Falls back to treating the whole file as one chunk if the expected
    header or section delimiters are not found.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    metadata, body_start = _parse_header(lines)

    try:
        source_rel = str(filepath.relative_to(DATA_DIR)).replace("\\", "/")
    except ValueError:
        source_rel = filepath.name

    if not metadata.get("scheme_name"):
        logger.warning(
            "No scheme name found in %s, treating as single chunk", filepath.name
        )
        return [{"text": content.strip(), "metadata": {"source_file": source_rel}}]

    sections = _split_sections(lines[body_start:])

    if not sections:
        logger.warning(
            "No === sections found in %s, treating as single chunk", filepath.name
        )
        return [
            {
                "text": content.strip(),
                "metadata": {**metadata, "source_file": source_rel},
            }
        ]

    chunks: list[dict] = []
    for section_title, section_lines in sections:
        for sc in _chunk_section(section_title, section_lines):
            if len(sc["text"]) >= MIN_CHUNK_LENGTH:
                chunk_meta = {
                    **metadata,
                    "section_title": sc["section_title"],
                    "source_file": source_rel,
                }
                chunks.append({"text": sc["text"], "metadata": chunk_meta})

    return chunks


def load_and_chunk_documents(data_dir: Path = DATA_DIR) -> list[dict]:
    """Load all .txt files in *data_dir* (including subfolders) and return structured chunks.

    Each element is ``{"text": str, "metadata": dict}``.
    """
    chunks: list[dict] = []
    for f in sorted(data_dir.rglob("*.txt")):
        chunks.extend(_parse_file(f))
    return chunks


# ---------------------------------------------------------------------------
# Vector store operations
# ---------------------------------------------------------------------------

def build_vector_store() -> chromadb.Collection:
    """Return the persisted collection, building it from data/ if it doesn't exist yet."""
    client_db = _get_client()
    existing = client_db.list_collections()
    if COLLECTION_NAME in [c.name for c in existing]:
        return client_db.get_collection(name=COLLECTION_NAME)
    # First run — build from scratch
    print("[INFO] Initializing ChromaDB vector collection...")
    chunks = load_and_chunk_documents()
    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    print(f"[INFO] Loaded {len(texts)} chunks across data/ repository.")
    collection = client_db.create_collection(name=COLLECTION_NAME)
    if texts:
        print(f"[INFO] Computing neural embeddings (model: {EMBEDDING_MODEL})...")
        doc_embeddings = _embed(texts, "passage: ", show_progress=True)
        collection.add(
            documents=texts,
            embeddings=doc_embeddings,
            metadatas=metadatas,
            ids=[f"chunk_{i}" for i in range(len(texts))],
        )
    else:
        print("[WARN] No documents found in data/ — collection created empty. Add scheme .txt files and POST /reindex to populate it.")
    print(f"[SUCCESS] Index built successfully with {collection.count()} chunks.")
    return collection


def force_rebuild_index() -> chromadb.Collection:
    """Delete the existing collection (if any) and rebuild from data/."""
    client_db = _get_client()
    existing = client_db.list_collections()
    if COLLECTION_NAME in [c.name for c in existing]:
        client_db.delete_collection(name=COLLECTION_NAME)
    chunks = load_and_chunk_documents()
    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    print(f"[INFO] Loaded {len(texts)} document chunks from data/ (including subfolders).")
    collection = client_db.create_collection(name=COLLECTION_NAME)
    if texts:
        print(f"[INFO] Computing neural embeddings with {EMBEDDING_MODEL} (CPU/GPU)...")
        doc_embeddings = _embed(texts, "passage: ", show_progress=True)
        collection.add(
            documents=texts,
            embeddings=doc_embeddings,
            metadatas=metadatas,
            ids=[f"chunk_{i}" for i in range(len(texts))],
        )
    else:
        print("[WARN] No documents found in data/ — collection rebuilt empty.")
    print(f"[SUCCESS] Vector store rebuilt! Total chunks indexed: {collection.count()}")
    return collection


def query_vector_store(
    collection: chromadb.Collection, question: str, n_results: int = 2,
    scheme_filter: str | list[str] | None = None,
) -> str:
    """Query the collection and return the top matching chunks as a single string."""
    query_embedding = _embed([question], "query: ")
    kwargs: dict = {"query_embeddings": query_embedding, "n_results": n_results}
    if scheme_filter:
        if isinstance(scheme_filter, list):
            kwargs["where"] = {"scheme_name": {"$in": scheme_filter}}
        else:
            kwargs["where"] = {"scheme_name": scheme_filter}
    results = collection.query(**kwargs, include=["documents", "metadatas"])
    # Log and prefix each chunk with its scheme name
    chunks = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        scheme = meta.get("scheme_name", "Unknown")
        print(f"    [retrieval] chunk scheme_name={scheme}")
        chunks.append(f"[Scheme: {scheme}]\n{doc}")
    return "\n\n".join(chunks)
