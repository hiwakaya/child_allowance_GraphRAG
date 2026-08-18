"""Phase4: deploy the Vector Search index onto its endpoint.
This is a long-running operation and, once deployed, incurs hourly cost."""
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

    index = aiplatform.MatchingEngineIndex(index_name)
    endpoint = aiplatform.MatchingEngineIndexEndpoint(endpoint_name)

    print(f"Deploying index {index_name} to endpoint {endpoint_name}...")
    endpoint.deploy_index(
        index=index,
        deployed_index_id=DEPLOYED_INDEX_ID,
        display_name=DEPLOYED_INDEX_ID,
        min_replica_count=1,
        max_replica_count=1,
    )
    print(f"Deployed. deployed_index_id={DEPLOYED_INDEX_ID}")

    out_path = REPO_ROOT / "vector_kb" / "index_resource_names.txt"
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(f"DEPLOYED_INDEX_ID={DEPLOYED_INDEX_ID}\n")


if __name__ == "__main__":
    main()
