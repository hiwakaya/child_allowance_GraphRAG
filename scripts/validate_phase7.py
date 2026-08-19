"""Phase7 validation: every :Decision node must be connected to at least
one :Rule node via DETERMINES (CLAUDE.md Phase7 requirement)."""
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

    with driver.session() as session:
        result = session.run("""
            MATCH (d:判定)
            OPTIONAL MATCH (r:ルール)-[:DETERMINES]->(d)
            WITH d, collect(r.name) AS rules
            RETURN d.id AS id, d.name AS name, rules, size(rules) AS rule_count
            ORDER BY rule_count
        """)
        missing = []
        for row in result:
            marker = "OK" if row["rule_count"] > 0 else "MISSING"
            print(f"  [{marker}] {row['id']} {row['name']} <- {row['rules']}")
            if row["rule_count"] == 0:
                missing.append(row["id"])
        print(f"\nDecisions without any Rule: {len(missing)} {missing}")

    driver.close()


if __name__ == "__main__":
    main()
