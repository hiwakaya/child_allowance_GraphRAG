"""Phase4: create a Vertex AI Vector Search index from vector_kb/embeddings.jsonl
and a public index endpoint. Index creation is a long-running operation
(historically 30-60+ minutes even for small datasets).
"""
from pathlib import Path

from google.cloud import aiplatform

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
GCS_URI = "gs://driven-backbone-479003-v3-jido-fuyo-teate-vectors/embeddings/"
INDEX_DISPLAY_NAME = "jido-fuyo-teate-index"
ENDPOINT_DISPLAY_NAME = "jido-fuyo-teate-endpoint"
DIMENSIONS = 768


def main():
    aiplatform.init(project=PROJECT, location=REGION)

    print("Creating index (this is a long-running operation)...")
    index = aiplatform.MatchingEngineIndex.create_tree_ah_index(
        display_name=INDEX_DISPLAY_NAME,
        contents_delta_uri=GCS_URI,
        dimensions=DIMENSIONS,
        approximate_neighbors_count=10,
        distance_measure_type="COSINE_DISTANCE",
        leaf_node_embedding_count=500,
        leaf_nodes_to_search_percent=10,
        description="児童扶養手当事務処理マニュアル chunk embeddings (Phase4)",
    )
    print("Index created:", index.resource_name)

    print("Creating index endpoint (public)...")
    endpoint = aiplatform.MatchingEngineIndexEndpoint.create(
        display_name=ENDPOINT_DISPLAY_NAME,
        public_endpoint_enabled=True,
        description="児童扶養手当 GraphRAG vector endpoint (Phase4)",
    )
    print("Endpoint created:", endpoint.resource_name)

    out_path = REPO_ROOT / "vector_kb" / "index_resource_names.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"INDEX={index.resource_name}\n")
        f.write(f"ENDPOINT={endpoint.resource_name}\n")
    print(f"Resource names saved to {out_path}")


if __name__ == "__main__":
    main()
