"""Phase8: Graph Retriever.

Implements the 6-step retrieval pipeline from CLAUDE.md:
  1. Concept Search   - keyword-match the query against ontology node names
  2. Path Discovery   - traverse the graph from matched nodes (<=2 hops)
  3. Evidence Discovery - follow EVIDENCED_BY from matched/path nodes to Chunks
  4. Chunk Retrieval  - fetch full text/metadata for those chunks
  5. Vector Retrieval - brute-force cosine similarity over vector_kb/embeddings.jsonl
  6. Context Assembly - merge everything into {concepts, paths, evidence, laws, chunks}

This module does NOT generate a natural-language answer - that is the
AI Orchestrator's job (a downstream LLM call using this structured
context). GraphRAG's responsibility stops at retrieval + explainability
grounding, per CLAUDE.md's PRIMARY OBJECTIVE (GraphRAGは行政判断・金額計算を行わない).
"""
import json
import re
from pathlib import Path

import numpy as np
import vertexai
from neo4j import GraphDatabase
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

from retriever.secrets_util import get_secret

PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
EMBEDDING_MODEL = "text-multilingual-embedding-002"
REPO_ROOT = Path(__file__).resolve().parent.parent

VECTOR_TOP_K = 5
PATH_MAX_HOPS = 2
PATH_LIMIT = 30


class GraphRetriever:
    def __init__(self):
        uri = get_secret("neo4j-aura-uri")
        user = get_secret("neo4j-aura-username")
        password = get_secret("neo4j-aura-password")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

        vertexai.init(project=PROJECT, location=REGION)
        self.embed_model = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL)

        with open(REPO_ROOT / "vector_kb" / "embeddings.jsonl", encoding="utf-8") as f:
            self._embeddings = [json.loads(line) for line in f]
        self._embedding_matrix = np.array([e["embedding"] for e in self._embeddings])
        self._embedding_ids = [e["id"] for e in self._embeddings]

        with open(REPO_ROOT / "vector_kb" / "chunks.jsonl", encoding="utf-8") as f:
            self._chunks_by_id = {c["chunk_id"]: c for c in (json.loads(l) for l in f)}

        with self.driver.session() as session:
            result = session.run("MATCH (n) WHERE n.id IS NOT NULL RETURN n")
            self._ontology_nodes = [dict(r["n"]) | {"labels": list(r["n"].labels)} for r in result]

        # クエリ結果キャッシュ（(query, top_k)の完全一致でVertex AI埋め込み呼び出しを省く）。
        # 意味的類似度に基づくファジーマッチではなく、同一クエリ文字列の再利用のみを対象とする
        # （2026-09-05・tasks.md T6「セマンティックキャッシュ」）。プロセス内メモリのみで永続化しない。
        self._vector_cache = {}

    def close(self):
        self.driver.close()

    # 1. Concept Search --------------------------------------------------
    def concept_search(self, query):
        matches = []
        for node in self._ontology_nodes:
            name = node["name"]
            stripped = re.sub(r"[（(].*?[）)]", "", name).strip()
            if (stripped and stripped in query) or name in query:
                matches.append(node)
        return matches

    # 2. Path Discovery ----------------------------------------------------
    def path_discovery(self, concept_ids):
        if not concept_ids:
            return []
        with self.driver.session() as session:
            result = session.run(
                f"""
                MATCH (start) WHERE start.id IN $ids
                MATCH p = (start)-[*1..{PATH_MAX_HOPS}]-(other)
                WHERE other.id IS NOT NULL AND other.id <> start.id
                WITH p LIMIT $limit
                RETURN [n IN nodes(p) | {{id: coalesce(n.id, n.chunk_id), name: coalesce(n.name, n.chunk_id), labels: labels(n)}}] AS path_nodes,
                       [r IN relationships(p) | type(r)] AS path_rels
                """,
                ids=concept_ids, limit=PATH_LIMIT,
            )
            paths = []
            for row in result:
                nodes = row["path_nodes"]
                rels = row["path_rels"]
                steps = []
                for i, rel in enumerate(rels):
                    steps.append({
                        "from_id": nodes[i]["id"], "from": nodes[i]["name"],
                        "relation": rel,
                        "to_id": nodes[i + 1]["id"], "to": nodes[i + 1]["name"],
                    })
                paths.append(steps)
            return paths

    # 3. Evidence Discovery + 4. Chunk Retrieval ---------------------------
    def evidence_discovery(self, node_ids):
        if not node_ids:
            return []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n)-[:EVIDENCED_BY]->(ch:Chunk)
                WHERE n.id IN $ids
                RETURN n.id AS node_id, n.name AS node_name, ch.chunk_id AS chunk_id,
                       ch.page AS page, ch.section AS section
                """,
                ids=node_ids,
            )
            evidence = []
            for row in result:
                chunk = self._chunks_by_id.get(row["chunk_id"], {})
                evidence.append({
                    "node_id": row["node_id"],
                    "node_name": row["node_name"],
                    "chunk_id": row["chunk_id"],
                    "text": chunk.get("text", ""),
                    "page": row["page"],
                    "section": row["section"],
                })
            return evidence

    # 5. Vector Retrieval ----------------------------------------------------
    def vector_retrieval(self, query, top_k=VECTOR_TOP_K):
        cache_key = (query, top_k)
        cached = self._vector_cache.get(cache_key)
        if cached is not None:
            return cached

        query_embedding = self.embed_model.get_embeddings(
            [TextEmbeddingInput(text=query, task_type="RETRIEVAL_QUERY")]
        )[0].values
        q = np.array(query_embedding)
        sims = self._embedding_matrix @ q / (
            np.linalg.norm(self._embedding_matrix, axis=1) * np.linalg.norm(q)
        )
        top_idx = np.argsort(-sims)[:top_k]
        results = []
        for i in top_idx:
            chunk_id = self._embedding_ids[i]
            chunk = self._chunks_by_id.get(chunk_id, {})
            results.append({
                "chunk_id": chunk_id,
                "score": float(sims[i]),
                "text": chunk.get("text", ""),
                "page": chunk.get("page"),
                "section": chunk.get("section"),
            })
        self._vector_cache[cache_key] = results
        return results

    # Concept backfill: nodes evidenced by the same passages vector search
    # found relevant, for when concept_search's keyword match finds nothing
    # (e.g. paraphrased queries that don't contain a literal node name) --------
    def concepts_from_chunks(self, chunk_ids):
        if not chunk_ids:
            return []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n)-[:EVIDENCED_BY]->(ch:Chunk)
                WHERE ch.chunk_id IN $chunk_ids
                RETURN DISTINCT n
                """,
                chunk_ids=chunk_ids,
            )
            return [dict(r["n"]) | {"labels": list(r["n"].labels)} for r in result]

    # Laws referenced by matched/path nodes ---------------------------------
    def find_laws(self, node_ids):
        if not node_ids:
            return []
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (n)-[:GOVERNED_BY]->(law:法令)
                WHERE n.id IN $ids
                RETURN DISTINCT law.id AS id, law.name AS name, law.description AS description, law.page AS page
                """,
                ids=node_ids,
            )
            return [dict(r) for r in result]

    # 6. Context Assembly -----------------------------------------------------
    def retrieve(self, query, exclude_node_ids=None):
        """`exclude_node_ids`：制度スコープ外の事由等、呼び出し側の判断で検索対象から除外したい
        オントロジーノードIDの集合（例：本デモが対象外とする積極的要件）。グラフ側
        （concepts／paths／evidence／laws）にのみ適用し、`vector_hits`（生テキストの類似度検索）は
        ノードとの対応を持たないため対象外（呼び出し側で除外ノード名を含むchunkを別途フィルタする
        必要がある場合はchunk側で判断すること）。デフォルト（None）は従来通り除外なし。
        """
        exclude = set(exclude_node_ids or ())

        concepts = [c for c in self.concept_search(query) if c["id"] not in exclude]
        vector_hits = self.vector_retrieval(query)

        backfill = self.concepts_from_chunks([v["chunk_id"] for v in vector_hits])
        seen_ids = {c["id"] for c in concepts}
        for c in backfill:
            if c["id"] not in seen_ids and c["id"] not in exclude:
                concepts.append(c)
                seen_ids.add(c["id"])
        concept_ids = [c["id"] for c in concepts]

        paths = self.path_discovery(concept_ids)
        path_node_ids = {
            n for path in paths for step in path
            for n in (step["from_id"], step["to_id"])
        } - exclude
        evidence_node_ids = list((set(concept_ids) | path_node_ids) - exclude)

        evidence = self.evidence_discovery(evidence_node_ids)
        laws = self.find_laws(evidence_node_ids)

        chunks_by_id = {}
        for e in evidence:
            chunks_by_id[e["chunk_id"]] = {
                "chunk_id": e["chunk_id"], "text": e["text"],
                "page": e["page"], "section": e["section"], "source": "graph_evidence",
            }
        for v in vector_hits:
            if v["chunk_id"] not in chunks_by_id:
                chunks_by_id[v["chunk_id"]] = {
                    "chunk_id": v["chunk_id"], "text": v["text"],
                    "page": v["page"], "section": v["section"], "source": "vector_search",
                    "score": v["score"],
                }

        return {
            "query": query,
            "concepts": [
                {"id": c["id"], "name": c["name"], "label": c["labels"][0],
                 "description": c.get("description"), "category": c.get("category")}
                for c in concepts
            ],
            "paths": paths,
            "evidence": evidence,
            "laws": laws,
            "chunks": list(chunks_by_id.values()),
        }

    # Baseline for comparison: vector similarity only, no graph traversal at
    # all (no concepts/paths/laws/evidence) - see scripts/compare_vector_vs_graph.py
    def retrieve_vector_only(self, query, top_k=10):
        vector_hits = self.vector_retrieval(query, top_k=top_k)
        return {
            "query": query,
            "concepts": [],
            "paths": [],
            "evidence": [],
            "laws": [],
            "chunks": [
                {"chunk_id": v["chunk_id"], "text": v["text"], "page": v["page"],
                 "section": v["section"], "source": "vector_search", "score": v["score"]}
                for v in vector_hits
            ],
        }
