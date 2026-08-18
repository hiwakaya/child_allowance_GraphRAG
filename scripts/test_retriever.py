"""Phase8: exercise the Graph Retriever with example questions and print
the structured context it assembles (Concepts / Paths / Evidence / Laws / Chunks)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.graph_retriever import GraphRetriever

TEST_QUERIES = [
    "事実婚をしている場合、児童扶養手当は支給されますか",
    "所得が限度額を超えるとどうなりますか",
    "差止はどのような場合に行われますか",
]


def main():
    retriever = GraphRetriever()
    try:
        for query in TEST_QUERIES:
            print(f"\n{'=' * 60}\nQuery: {query}\n{'=' * 60}")
            ctx = retriever.retrieve(query)

            print(f"\n[Concepts] ({len(ctx['concepts'])})")
            for c in ctx["concepts"]:
                print(f"  - {c['id']} [{c['label']}] {c['name']}")

            print(f"\n[Paths] ({len(ctx['paths'])}, showing first 5)")
            for path in ctx["paths"][:5]:
                path_str = " -> ".join(
                    f"{s['from']} -[{s['relation']}]-> {s['to']}" if i == 0 else f"-[{s['relation']}]-> {s['to']}"
                    for i, s in enumerate(path)
                )
                print(f"  {path_str}")

            print(f"\n[Laws] ({len(ctx['laws'])})")
            for law in ctx["laws"]:
                print(f"  - {law['name']} (page {law['page']})")

            print(f"\n[Chunks] ({len(ctx['chunks'])})")
            for ch in ctx["chunks"]:
                src = ch["source"]
                score = f" score={ch['score']:.3f}" if "score" in ch else ""
                print(f"  - {ch['chunk_id']} [{src}{score}] page={ch['page']} section={ch['section']}")
                print(f"      {ch['text'][:100]}...")
    finally:
        retriever.close()


if __name__ == "__main__":
    main()
