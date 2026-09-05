"""Phase5: Concept-Chunk Linking.

Loads vector_kb/chunks.jsonl into Neo4j as :Chunk nodes attached to a
:Document node, then links every ontology node (all labels, not just
:Concept - see project rationale) to the chunk(s) that best evidence it,
via (node)-[:EVIDENCED_BY]->(:Chunk).

Matching strategy (first hit wins):
  1. node.name (or name with trailing parenthetical stripped) appears
     verbatim in chunk.text
  2. same page number as recorded on the node
  3. nearest page number, as a fallback so every node gets >=1 link
"""
import csv
import json
import re
import subprocess
from pathlib import Path

from neo4j import GraphDatabase

PROJECT = "driven-backbone-479003-v3"
REPO_ROOT = Path(__file__).resolve().parent.parent
DOCUMENT_NAME = "札幌市児童扶養手当事務処理マニュアル"

# ontology/nodes.csv の source 列は歴史的に "manual" 固定（実データの唯一のソースが
# マニュアルのみだった頃の名残）。chunks.jsonl 側の source は文書の正式名称のため、
# ページベースのフォールバック（find_evidence_chunk のstep2/3）で文書を跨いで誤ヒット
# しないよう、node.source をchunkの実際のsource値へ解決するためのエイリアス。
# 2026-09-05・リーフレット/様式取込で複数文書対応。
SOURCE_ALIASES = {
    "manual": DOCUMENT_NAME,
}

# マニュアル冒頭の概要ページ（「はじめに」）は多くの概念名を列挙的に含むため、
# 部分文字列マッチのハブ化を招く（2026-09-05判明・T6監査）。除外候補が0件になる
# 場合のみフォールバックとして許容する（全ノード最低1件の根拠、という制約は壊さない）。
_GENERIC_SECTIONS = {"はじめに"}


def get_secret(name):
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={name}", f"--project={PROJECT}"],
        capture_output=True, text=True, check=True, shell=True
    )
    return result.stdout.strip()


def load_chunks():
    with open(REPO_ROOT / "vector_kb" / "chunks.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def load_nodes():
    with open(REPO_ROOT / "ontology" / "nodes.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_pages(page_field):
    """'3-4' -> [3, 4], '40-48' -> [40, 48], '65' -> [65]"""
    nums = [int(n) for n in re.findall(r"\d+", page_field)]
    if len(nums) >= 2:
        return list(range(nums[0], nums[-1] + 1))
    return nums or [1]


def find_evidence_chunk(node_name, node_pages, node_source, chunks_by_source_page, chunks):
    stripped_name = re.sub(r"[（(].*?[）)]", "", node_name).strip()
    target_page = node_pages[0]
    for candidate in (node_name, stripped_name):
        if not candidate:
            continue
        hits = [c for c in chunks if candidate in c["text"]]
        if not hits:
            continue
        # 「はじめに」等の概要ページはハブ化するため候補から除外する。
        # 除外後に0件ならフォールバックとしてそのまま使う（無根拠ノードを作らない）。
        specific_hits = [c for c in hits if c["section"] not in _GENERIC_SECTIONS]
        hits = specific_hits or hits
        best = min(hits, key=lambda c: abs(c["page"] - target_page))
        return best["chunk_id"]

    resolved_source = SOURCE_ALIASES.get(node_source, node_source)
    for p in node_pages:
        candidates = chunks_by_source_page.get((resolved_source, p))
        if candidates:
            return candidates[0]["chunk_id"]

    same_source_pages = sorted(
        p for (src, p) in chunks_by_source_page if src == resolved_source
    )
    if same_source_pages:
        target = node_pages[0]
        nearest = min(same_source_pages, key=lambda p: abs(p - target))
        return chunks_by_source_page[(resolved_source, nearest)][0]["chunk_id"]

    # resolved_source に一致するチャンクが無い場合（想定外）は全文書から最近傍を探す。
    all_pages = sorted({p for (_src, p) in chunks_by_source_page})
    target = node_pages[0]
    nearest = min(all_pages, key=lambda p: abs(p - target))
    any_source = next(src for (src, p) in chunks_by_source_page if p == nearest)
    return chunks_by_source_page[(any_source, nearest)][0]["chunk_id"]


def main():
    chunks = load_chunks()
    nodes = load_nodes()

    chunks_by_source_page = {}
    for c in chunks:
        chunks_by_source_page.setdefault((c["source"], c["page"]), []).append(c)
    document_names = sorted({c["source"] for c in chunks})

    uri = get_secret("neo4j-aura-uri")
    user = get_secret("neo4j-aura-username")
    password = get_secret("neo4j-aura-password")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        print(f"Creating {len(document_names)} :Document node(s)...")
        session.run(
            "UNWIND $names AS name MERGE (d:Document {name: name})",
            names=document_names,
        )

        print(f"Loading {len(chunks)} :Chunk nodes and linking to :Document...")
        session.run("""
            UNWIND $chunks AS c
            MERGE (ch:Chunk {chunk_id: c.chunk_id})
            SET ch.text = c.text, ch.source = c.source, ch.page = c.page,
                ch.section = c.section, ch.category = c.category, ch.revision = c.revision
            WITH ch, c
            MATCH (d:Document {name: c.source})
            MERGE (ch)-[:PART_OF]->(d)
        """, chunks=chunks)

        print("Clearing any stale EVIDENCED_BY links from a previous run...")
        session.run("MATCH ()-[r:EVIDENCED_BY]->() DELETE r")

        print(f"Linking {len(nodes)} ontology nodes to evidence chunks...")
        links = []
        for n in nodes:
            node_pages = parse_pages(n["page"])
            chunk_id = find_evidence_chunk(
                n["name"], node_pages, n["source"], chunks_by_source_page, chunks
            )
            links.append({"id": n["id"], "chunk_id": chunk_id})

        session.run("""
            UNWIND $links AS l
            MATCH (n {id: l.id})
            MATCH (ch:Chunk {chunk_id: l.chunk_id})
            MERGE (n)-[:EVIDENCED_BY]->(ch)
        """, links=links)

        print("Validating: ontology nodes with zero EVIDENCED_BY chunk links...")
        result = session.run("""
            MATCH (n) WHERE n.id IS NOT NULL AND NOT (n)-[:EVIDENCED_BY]->(:Chunk)
            RETURN n.id AS id, n.name AS name, labels(n) AS labels
        """)
        missing = list(result)
        print(f"  unlinked count: {len(missing)}")
        for m in missing:
            print(f"  MISSING: {m['id']} {m['name']} {m['labels']}")

        result = session.run("MATCH (n) RETURN count(n) AS c")
        print("Total nodes in graph:", result.single()["c"])
        result = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
        print("Total relationships in graph:", result.single()["c"])

        print("Checking はじめに hub links (2026-09-05 fix)...")
        result = session.run("""
            MATCH (n)-[:EVIDENCED_BY]->(ch:Chunk) WHERE ch.section = 'はじめに'
            RETURN count(n) AS c
        """)
        print("  nodes still linked to はじめに:", result.single()["c"])

    driver.close()


if __name__ == "__main__":
    main()
