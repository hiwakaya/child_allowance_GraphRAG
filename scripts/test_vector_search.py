"""Phase4: test query against the deployed Vector Search index."""
import json
from pathlib import Path

import vertexai
from google.cloud import aiplatform
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
MODEL_NAME = "text-multilingual-embedding-002"
DEPLOYED_INDEX_ID = "jido_fuyo_teate_deployed"

TEST_QUERY = "事実婚とはどのような状態を指しますか"


def read_resource_names():
    path = REPO_ROOT / "vector_kb" / "index_resource_names.txt"
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values["ENDPOINT"]


def main():
    vertexai.init(project=PROJECT, location=REGION)
    model = TextEmbeddingModel.from_pretrained(MODEL_NAME)
    query_embedding = model.get_embeddings(
        [TextEmbeddingInput(text=TEST_QUERY, task_type="RETRIEVAL_QUERY")]
    )[0].values

    aiplatform.init(project=PROJECT, location=REGION)
    endpoint_name = read_resource_names()
    endpoint = aiplatform.MatchingEngineIndexEndpoint(endpoint_name)

    response = endpoint.find_neighbors(
        deployed_index_id=DEPLOYED_INDEX_ID,
        queries=[query_embedding],
        num_neighbors=3,
    )

    chunks_by_id = {}
    with open(REPO_ROOT / "vector_kb" / "chunks.jsonl", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            chunks_by_id[c["chunk_id"]] = c

    print(f"Query: {TEST_QUERY}\n")
    for neighbor in response[0]:
        chunk = chunks_by_id.get(neighbor.id, {})
        print(f"  [{neighbor.id}] distance={neighbor.distance:.4f} section={chunk.get('section')}")
        print(f"    {chunk.get('text', '')[:150]}...")
        print()


if __name__ == "__main__":
    main()
