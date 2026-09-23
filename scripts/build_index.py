import sys
from pathlib import Path

# Allow imports from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag_core import force_rebuild_index

collection = force_rebuild_index()
print("Index rebuilt successfully with", collection.count(), "chunks")
