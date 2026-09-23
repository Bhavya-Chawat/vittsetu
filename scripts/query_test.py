import sys
from pathlib import Path

# Allow imports from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from rag_core import build_vector_store, _embed

collection = build_vector_store()

# Now the actual test: ask a question
query = "I need a loan of 3 lakh rupees for my small shop, which category do I fall under?"

query_embedding = _embed([query], "query: ")
results = collection.query(query_embeddings=query_embedding, n_results=3)

print("QUERY:", query)
print("\nTOP MATCHING CHUNKS:\n")
for i, doc in enumerate(results["documents"][0]):
    print(f"--- Match {i+1} ---")
    print(doc[:400])
    print()