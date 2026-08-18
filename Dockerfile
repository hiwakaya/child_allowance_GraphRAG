FROM python:3.12-slim

WORKDIR /app

COPY webapp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY retriever/ ./retriever/
COPY vector_kb/chunks.jsonl vector_kb/embeddings.jsonl ./vector_kb/
COPY webapp/ ./webapp/

ENV PORT=8080
CMD ["python", "-m", "uvicorn", "webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
