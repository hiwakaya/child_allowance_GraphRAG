"""Undo Phase4's Vertex AI Vector Search deployment: undeploy the index,
then delete the endpoint and the index. Superseded by in-process brute-force
search over vector_kb/embeddings.jsonl inside the future Cloud Run Graph
Retriever API (Phase8) - see project decision after cost review.
"""
from pathlib import Path

from google.cloud import aiplatform

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
DEPLOYED_INDEX_ID = "jido_fuyo_teate_deployed"


def read_resource_names():
    path = REPO_ROOT / "vector_kb" / "index_resource_names.txt"
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values["INDEX"], values["ENDPOINT"]


def main():
    aiplatform.init(project=PROJECT, location=REGION)
    index_name, endpoint_name = read_resource_names()

    endpoint = aiplatform.MatchingEngineIndexEndpoint(endpoint_name)
    print(f"Undeploying {DEPLOYED_INDEX_ID} from endpoint...")
    endpoint.undeploy_index(deployed_index_id=DEPLOYED_INDEX_ID)
    print("Undeployed.")

    print("Deleting endpoint...")
    endpoint.delete()
    print("Endpoint deleted.")

    index = aiplatform.MatchingEngineIndex(index_name)
    print("Deleting index...")
    index.delete()
    print("Index deleted.")


if __name__ == "__main__":
    main()
