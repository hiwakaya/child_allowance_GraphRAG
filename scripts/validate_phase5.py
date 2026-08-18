"""Phase5 spot-check: sample a few node->chunk evidence links."""
import subprocess

from neo4j import GraphDatabase

PROJECT = "driven-backbone-479003-v3"


def get_secret(name):
    result = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         f"--secret={name}", f"--project={PROJECT}"],
        capture_output=True, text=True, check=True, shell=True
    )
    return result.stdout.strip()


def main():
    uri = get_secret("neo4j-aura-uri")
    user = get_secret("neo4j-aura-username")
    password = get_secret("neo4j-aura-password")
    driver = GraphDatabase.driver(uri, auth=(user, password))

    sample_ids = ["ELIG-PR01", "CON-05", "INC-04", "BEN-03", "LAW-08", "RULE-BC01", "DEC-04"]
    with driver.session() as session:
        for nid in sample_ids:
            result = session.run("""
                MATCH (n {id: $id})-[:EVIDENCED_BY]->(ch:Chunk)
                RETURN n.name AS name, ch.chunk_id AS chunk_id, ch.page AS page, left(ch.text, 80) AS snippet
            """, id=nid)
            for r in result:
                print(f"{nid} [{r['name']}] -> {r['chunk_id']} (page {r['page']})")
                print(f"    {r['snippet']}...")

        print("\n=== Full chain check: Concept -> Chunk -> Document ===")
        result = session.run("""
            MATCH (c:Concept {id: 'CON-01'})-[:EVIDENCED_BY]->(ch:Chunk)-[:PART_OF]->(d:Document)
            RETURN c.name AS concept, ch.chunk_id AS chunk, ch.page AS page, d.name AS document
        """)
        for r in result:
            print(f"{r['concept']} -> {r['chunk']} (page {r['page']}) -> {r['document']}")

    driver.close()


if __name__ == "__main__":
    main()
