"""Phase3: load ontology/nodes.csv and ontology/relations.csv into Neo4j Aura.

Credentials are read from GCP Secret Manager (neo4j-aura-uri, neo4j-aura-username,
neo4j-aura-password) rather than stored locally. Requires: pip install neo4j
"""
import csv
import subprocess
from pathlib import Path

from neo4j import GraphDatabase

PROJECT = "driven-backbone-479003-v3"
REPO_ROOT = Path(__file__).resolve().parent.parent


def get_secret(name):
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={name}", f"--project={PROJECT}"],
        capture_output=True, text=True, check=True, shell=True
    )
    return result.stdout.strip()


def load_nodes_by_label(session, label, rows):
    query = f"""
    UNWIND $rows AS row
    MERGE (n:`{label}` {{name: row.name}})
    SET n.id = row.id,
        n.description = row.description,
        n.source = row.source,
        n.page = row.page,
        n.category = row.category
    """
    session.run(query, rows=rows)


def load_relations(session, rel_type, rows):
    query = f"""
    UNWIND $rows AS row
    MATCH (s {{id: row.source}})
    MATCH (t {{id: row.target}})
    MERGE (s)-[r:`{rel_type}` {{source_doc: row.source_doc, page: row.page}}]->(t)
    """
    session.run(query, rows=rows)


def main():
    uri = get_secret("neo4j-aura-uri")
    user = get_secret("neo4j-aura-username")
    password = get_secret("neo4j-aura-password")

    driver = GraphDatabase.driver(uri, auth=(user, password))

    with driver.session() as session:
        print("Creating uniqueness constraints (name unique per label)...")
        with open(REPO_ROOT / "ontology" / "nodes.csv", encoding="utf-8") as f:
            nodes = list(csv.DictReader(f))
        labels = sorted(set(n["label"] for n in nodes))
        for label in labels:
            session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:`{label}`) REQUIRE n.name IS UNIQUE")
        print(f"  constraints created for labels: {labels}")

        print("Loading nodes...")
        by_label = {}
        for n in nodes:
            by_label.setdefault(n["label"], []).append(n)
        for label, rows in by_label.items():
            load_nodes_by_label(session, label, rows)
            print(f"  {label}: {len(rows)} nodes")

        print("Loading relations...")
        with open(REPO_ROOT / "ontology" / "relations.csv", encoding="utf-8") as f:
            rels = list(csv.DictReader(f))
        by_type = {}
        for r in rels:
            by_type.setdefault(r["relation"], []).append(r)
        for rel_type, rows in by_type.items():
            load_relations(session, rel_type, rows)
            print(f"  {rel_type}: {len(rows)} relations")

        result = session.run("MATCH (n) RETURN count(n) AS c")
        print("Total nodes in graph:", result.single()["c"])
        result = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
        print("Total relationships in graph:", result.single()["c"])

    driver.close()


if __name__ == "__main__":
    main()
