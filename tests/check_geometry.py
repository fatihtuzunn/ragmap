"""Run the chunk-geometry detectors against the passages recorded from the
live AnythingLLM scan, with no network. Ground truth: 900 / 150."""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ragmap.config import ScanConfig
from ragmap.context import Context
from ragmap.model import Chunk
from ragmap.modules.chunking import ChunkOverlap, ChunkSize
from ragmap.transport import Transport

# Defaults to the scan of the live AnythingLLM target that ships with the
# tool, whose chunk geometry is known from the product's own settings.
source = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    ROOT / "examples" / "anythingllm-ollama" / "ragmap.json"
report = json.load(io.open(source, encoding="utf-8"))

config = ScanConfig(url="http://replay.invalid", level=4)
transport = Transport(url="http://replay.invalid", budget=0)
ctx = Context(config, transport)

for c in report["chunks"]:
    ctx.chunks.add(Chunk(text=c["text"], query=c.get("query", ""),
                         doc_id=None, title=c.get("title"),
                         page=c.get("page"), score=c.get("score")))

groups = ctx.chunks.by_document()
print("passages:", len(ctx.chunks.items), "| documents:", len(groups))
for name, items in groups.items():
    print("   ", name, len(items))

size = ChunkSize()
ctx.begin(size)
size.run(ctx)
ctx.end()

overlap = ChunkOverlap()
ctx.begin(overlap)
overlap.run(ctx)
ctx.end()

print()
for key in ("chunk.size", "chunk.overlap"):
    f = ctx.facts.get(key)
    if f is None:
        print(f"{key}: (not set)")
        continue
    print(f"{key:14} {f.display}")
    print(f"{'':14} method:   {f.method}")
    print(f"{'':14} evidence: {f.evidence}")
print()
for note in ctx.notes:
    print("note:", note)
