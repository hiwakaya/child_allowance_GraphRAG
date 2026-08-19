"""One-off migration: rename ontology labels to Japanese and carve out a
new 当事者 (Person) label from Eligibility/Concept, per user request
(2026-08-18). Rewrites ontology/nodes.csv; ontology/relations.csv needs no
change since relations are keyed by node id, not label.
"""
import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NODES_PATH = REPO_ROOT / "ontology" / "nodes.csv"

LABEL_MAP = {
    "Law": "法令",
    "Eligibility": "支給要件",
    "Income": "所得",
    "Benefit": "支給",
    "Decision": "判定",
    "Rule": "ルール",
    "Event": "イベント",
    "Concept": "概念",
}

PERSON_IDS = {"ELIG-CL01", "ELIG-CL02", "ELIG-CL03", "ELIG-SP01", "CON-06", "CON-08", "CON-11"}

NEW_CHILD_ROW = {
    "id": "PER-CHILD01",
    "label": "当事者",
    "name": "児童",
    "description": "支給対象となる児童。18歳に達する日以後の最初の3月31日まで、又は20歳未満で障害の状態にある者",
    "source": "manual",
    "page": "3",
    "category": "対象児童",
}


def main():
    with open(NODES_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        if row["id"] in PERSON_IDS:
            row["label"] = "当事者"
        else:
            row["label"] = LABEL_MAP[row["label"]]

    rows.append(NEW_CHILD_ROW)

    with open(NODES_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "label", "name", "description", "source", "page", "category"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Updated {len(rows)} rows in {NODES_PATH}")
    label_counts = {}
    for row in rows:
        label_counts[row["label"]] = label_counts.get(row["label"], 0) + 1
    for label, count in sorted(label_counts.items()):
        print(f"  {label}: {count}")


if __name__ == "__main__":
    main()
