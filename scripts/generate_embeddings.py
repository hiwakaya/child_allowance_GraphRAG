"""Phase4: generate embeddings for vector_kb/chunks.jsonl using Vertex AI's
multilingual text embedding model, and write output in the JSONL format
expected by Vertex AI Vector Search (id, embedding, restricts).
"""
import json
from pathlib import Path

import vertexai
from vertexai.language_models import TextEmbeddingModel, TextEmbeddingInput

PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
MODEL_NAME = "text-multilingual-embedding-002"
BATCH_SIZE = 10

REPO_ROOT = Path(__file__).resolve().parent.parent
CHUNKS_PATH = REPO_ROOT / "vector_kb" / "chunks.jsonl"
OUTPUT_PATH = REPO_ROOT / "vector_kb" / "embeddings.jsonl"


def main():
    vertexai.init(project=PROJECT, location=REGION)
    model = TextEmbeddingModel.from_pretrained(MODEL_NAME)

    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]

    print(f"Embedding {len(chunks)} chunks with {MODEL_NAME}...")

    records = []
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        inputs = [TextEmbeddingInput(text=c["text"], task_type="RETRIEVAL_DOCUMENT") for c in batch]
        embeddings = model.get_embeddings(inputs)
        for chunk, emb in zip(batch, embeddings):
            records.append({
                "id": chunk["chunk_id"],
                "embedding": emb.values,
                "restricts": [
                    {"namespace": "category", "allow": [chunk["category"]]},
                    {"namespace": "section", "allow": [chunk["section"]]},
                ],
            })
        print(f"  {min(i + BATCH_SIZE, len(chunks))}/{len(chunks)}")

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} embeddings to {OUTPUT_PATH}")
    print(f"Embedding dimension: {len(records[0]['embedding'])}")


if __name__ == "__main__":
    main()
