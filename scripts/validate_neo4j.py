"""Phase3 Graph/Path Validation: checks CLAUDE.md's two verification paths
(受給資格者->支給要件->認定->受給権, 所得->支給区分->手当額) and reports orphan nodes.
"""
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
        print("=== Path 1: 受給資格者 -> 支給要件 -> 認定 -> 受給権 ===")
        result = session.run("""
            MATCH p = (claimant:当事者 {category: '受給資格者類型'})
                      -[:LEADS_TO]->(decision:判定 {name: '認定'})
                      -[:RESULTS_IN]->(right:支給要件 {name: '受給権'})
            RETURN claimant.name AS claimant, decision.name AS decision, right.name AS right
        """)
        for r in result:
            print(f"  {r['claimant']} -> {r['decision']} -> {r['right']}")

        print("=== Path 2: 所得 -> 支給区分 -> 手当額 ===")
        result = session.run("""
            MATCH p = (income:所得 {name: '所得算定額'})
                      -[:APPLIES_TO]->(rule:ルール)
                      -[:DETERMINES]->(benefit:支給)
            MATCH (benefit)<-[:PART_OF]-(amount:支給 {name: '手当額'})
            RETURN rule.name AS rule, benefit.name AS benefit, amount.name AS amount
        """)
        for r in result:
            print(f"  所得算定額 -> {r['rule']} -> {r['benefit']} -> {r['amount']}")

        print("=== Orphan check: nodes with zero relationships ===")
        result = session.run("MATCH (n) WHERE NOT (n)--() RETURN n.id AS id, n.name AS name")
        orphans = list(result)
        print(f"  orphan count: {len(orphans)}")
        for r in orphans:
            print(f"  ORPHAN: {r['id']} {r['name']}")

    driver.close()


if __name__ == "__main__":
    main()
