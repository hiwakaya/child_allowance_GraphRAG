"""Debug: for sample nodes, check whether the matched chunk genuinely
contains the node name substring (full text, not a truncated preview),
and show how many chunks in total contain that substring plus their pages,
so we can judge match quality properly."""
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main():
    with open(REPO_ROOT / "vector_kb" / "chunks.jsonl", encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]
    with open(REPO_ROOT / "ontology" / "nodes.csv", encoding="utf-8") as f:
        nodes = {n["id"]: n for n in csv.DictReader(f)}

    sample_ids = ["ELIG-PR01", "CON-05", "INC-04", "BEN-03", "DEC-04"]
    for nid in sample_ids:
        name = nodes[nid]["name"]
        node_page = nodes[nid]["page"]
        print(f"=== {nid} [{name}] (nodes.csv page={node_page}) ===")
        hits = [c for c in chunks if name in c["text"]]
        print(f"  chunks containing literal '{name}': {[ (c['chunk_id'], c['page']) for c in hits ]}")


if __name__ == "__main__":
    main()
