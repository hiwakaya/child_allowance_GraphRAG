"""One-off migration: apply the Japanese label rename + 当事者 (Person)
carve-out directly to the live Neo4j graph, preserving node ids and all
existing relationships (SET new label / REMOVE old label on the same
node, rather than re-loading via MERGE which would create duplicates).
"""
import subprocess

from neo4j import GraphDatabase

PROJECT = "driven-backbone-479003-v3"

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

PERSON_MOVES = [
    ("ELIG-CL01", "Eligibility"), ("ELIG-CL02", "Eligibility"), ("ELIG-CL03", "Eligibility"),
    ("ELIG-SP01", "Eligibility"), ("CON-06", "Concept"), ("CON-08", "Concept"), ("CON-11", "Concept"),
]

NEW_CHILD = {
    "id": "PER-CHILD01", "name": "児童",
    "description": "支給対象となる児童。18歳に達する日以後の最初の3月31日まで、又は20歳未満で障害の状態にある者",
    "source": "manual", "page": "3", "category": "対象児童",
}


def get_secret(name):
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={name}", f"--project={PROJECT}"],
        capture_output=True, text=True, check=True, shell=True,
    )
    return result.stdout.strip()


def main():
    uri = get_secret("neo4j-aura-uri")
    user = get_secret("neo4j-aura-username")
    password = get_secret("neo4j-aura-password")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        print("Carving out 当事者 (Person) label...")
        for node_id, old_label in PERSON_MOVES:
            session.run(
                f"MATCH (n:`{old_label}` {{id: $id}}) SET n:当事者 REMOVE n:`{old_label}`",
                id=node_id,
            )
        print(f"  moved {len(PERSON_MOVES)} nodes to 当事者")

        print("Adding new child node 児童...")
        session.run(
            "CREATE (n:当事者 $props)",
            props=NEW_CHILD,
        )

        print("Renaming remaining labels to Japanese...")
        for old_label, new_label in LABEL_MAP.items():
            result = session.run(
                f"MATCH (n:`{old_label}`) SET n:`{new_label}` REMOVE n:`{old_label}` RETURN count(n) AS c"
            )
            count = result.single()["c"]
            print(f"  {old_label} -> {new_label}: {count} nodes")

        print("Recreating uniqueness constraints under new label names...")
        all_labels = list(LABEL_MAP.values()) + ["当事者"]
        for label in all_labels:
            session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.name IS UNIQUE")

        print("Dropping stale constraints on old English label names...")
        result = session.run("SHOW CONSTRAINTS YIELD name, labelsOrTypes RETURN name, labelsOrTypes")
        for row in result:
            labels = row["labelsOrTypes"] or []
            if any(l in LABEL_MAP for l in labels):
                session.run(f"DROP CONSTRAINT `{row['name']}` IF EXISTS")
                print(f"  dropped {row['name']} ({labels})")

        print("\nFinal label counts:")
        result = session.run("MATCH (n) WHERE n.id IS NOT NULL RETURN labels(n) AS l, count(n) AS c")
        for row in result:
            print(f"  {row['l']}: {row['c']}")

    driver.close()


if __name__ == "__main__":
    main()
