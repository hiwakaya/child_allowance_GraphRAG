"""Compare answer quality: pure Vector RAG (chunk similarity only) vs the
full GraphRAG pipeline (concept search + path discovery + evidence + laws
+ vector retrieval combined).

Questions are chosen to include both simple factual lookups (where a
single relevant chunk likely suffices) and multi-hop questions that span
several non-adjacent sections of the manual (where GraphRAG's graph
traversal should out-perform chunk similarity alone, since the relevant
passages don't share much surface-level wording).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retriever.graph_retriever import GraphRetriever  # noqa: E402
from webapp.app import generate_answer  # noqa: E402

TEST_QUESTIONS = [
    # simple factual lookup - a single chunk likely covers it
    {"question": "所得制限とは何ですか", "type": "単純事実照会"},
    # multi-hop: 差止 -> 資格喪失(時効) -> 債権発生 -> 返還 is a 4-node chain
    # spread across pages 94-98, worded very differently from the question
    {"question": "住所変更の届出をしなかった場合、最終的にどうなる可能性がありますか", "type": "複数ステップ推論"},
    # multi-hop: pension start -> retroactive receipt -> debt (EVT-07 -> EVT-09)
    {"question": "年金を遡って受給できることになった場合、児童扶養手当はどうなりますか", "type": "複数ステップ推論"},
    # simple lookup
    {"question": "事実婚とはどのような状態ですか", "type": "単純事実照会"},
    # multi-hop: claimant type -> requirement -> decision -> right (認定 chain)
    {"question": "祖父母が孫を養育している場合、児童扶養手当を受け取れますか", "type": "複数ステップ推論"},
]


def run_comparison():
    retriever = GraphRetriever()
    results = []
    try:
        for item in TEST_QUESTIONS:
            q = item["question"]
            print(f"\n{'=' * 70}\n[{item['type']}] {q}\n{'=' * 70}")

            vec_ctx = retriever.retrieve_vector_only(q)
            vec_answer = generate_answer(q, vec_ctx)

            graph_ctx = retriever.retrieve(q)
            graph_answer = generate_answer(q, graph_ctx)

            print("\n--- Vector RAG only ---")
            print(f"回答: {vec_answer.get('answer')}")
            print(f"法令: {vec_answer.get('laws')}")
            print(f"根拠チャンク数: {len(vec_ctx['chunks'])}")

            print("\n--- GraphRAG (concept+path+evidence+vector) ---")
            print(f"回答: {graph_answer.get('answer')}")
            print(f"法令: {graph_answer.get('laws')}")
            print(f"推論経路: {graph_answer.get('reasoning_path')}")
            print(f"概念ヒット数: {len(graph_ctx['concepts'])} / 根拠チャンク数: {len(graph_ctx['chunks'])}")

            results.append({
                "question": q, "type": item["type"],
                "vector_only": vec_answer, "graph_rag": graph_answer,
                "vector_chunk_count": len(vec_ctx["chunks"]),
                "graph_chunk_count": len(graph_ctx["chunks"]),
                "graph_concept_count": len(graph_ctx["concepts"]),
            })
    finally:
        retriever.close()

    out_path = Path(__file__).resolve().parent.parent / "vector_kb" / "vector_vs_graph_comparison.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n\nSaved full comparison to {out_path}")


if __name__ == "__main__":
    run_comparison()
