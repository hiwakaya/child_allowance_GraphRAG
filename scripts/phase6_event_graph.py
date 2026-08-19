"""Phase6: Event Graph enrichment.

Adds an `event_role` lifecycle-category property to each :イベント node
(initiating / state_change / suspension / resumption / termination /
financial / financial_settlement), then validates that all 10 event types
are reachable from 認定 (EVT-01) via PRECEDES/FOLLOWED_BY/LEADS_TO edges -
i.e. the event graph forms one connected timeline, not isolated islands.

Design note: this models event TYPES and their temporal/causal ordering
only. Per CLAUDE.md's MCP SEPARATION RULE, GraphRAG does not store
per-recipient event instances (real dates, real people) - that data
belongs in MCP. This graph answers "what can follow what and why", not
"what happened to person X on date Y".
"""
import subprocess

from neo4j import GraphDatabase

PROJECT = "driven-backbone-479003-v3"

EVENT_ROLES = {
    "EVT-01": "initiating",
    "EVT-02": "termination",
    "EVT-03": "suspension",
    "EVT-04": "resumption",
    "EVT-05": "state_change",
    "EVT-06": "state_change",
    "EVT-07": "state_change",
    "EVT-08": "state_change",
    "EVT-09": "financial",
    "EVT-10": "financial_settlement",
}


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
        print("Setting event_role property on :イベント nodes...")
        session.run("""
            UNWIND $rows AS row
            MATCH (n:イベント {id: row.id})
            SET n.event_role = row.role
        """, rows=[{"id": k, "role": v} for k, v in EVENT_ROLES.items()])

        print("\n=== Timeline reachability from 認定 (EVT-01) ===")
        result = session.run("""
            MATCH (root:イベント {id: 'EVT-01'})
            MATCH (target:イベント) WHERE target.id <> 'EVT-01'
            OPTIONAL MATCH path = shortestPath(
                (root)-[:PRECEDES|FOLLOWED_BY|LEADS_TO*1..5]->(target)
            )
            RETURN target.id AS id, target.name AS name, target.event_role AS role,
                   path IS NOT NULL AS reachable,
                   length(path) AS hops
            ORDER BY hops
        """)
        unreachable = []
        for r in result:
            marker = "OK" if r["reachable"] else "UNREACHABLE"
            print(f"  [{marker}] {r['id']} {r['name']} (role={r['role']}, hops={r['hops']})")
            if not r["reachable"]:
                unreachable.append(r["id"])

        print(f"\nUnreachable events: {len(unreachable)} {unreachable}")

        print("\n=== Full event-type timeline edges ===")
        result = session.run("""
            MATCH (a:イベント)-[r:PRECEDES|FOLLOWED_BY|LEADS_TO]->(b:イベント)
            RETURN a.name AS from_event, type(r) AS rel, b.name AS to_event
        """)
        for r in result:
            print(f"  {r['from_event']} -[{r['rel']}]-> {r['to_event']}")

    driver.close()


if __name__ == "__main__":
    main()
