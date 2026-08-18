"""AI Orchestrator + Agent UI backend (Cloud Run).

Wraps retriever.graph_retriever.GraphRetriever with a Gemini call that
synthesizes a Japanese answer strictly grounded in the retrieved context,
following CLAUDE.md's EXPLAINABILITY POLICY (回答/理由/根拠/推論経路/法令/確認事項)
and PRIMARY OBJECTIVE constraints (GraphRAGは行政判断・金額計算を行わない).
"""
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retriever.graph_retriever import GraphRetriever  # noqa: E402

PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
GEMINI_MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = """あなたは「児童扶養手当制度 説明支援アシスタント」です。
以下のルールを厳守してください。

1. 回答は、与えられた検索結果（概念・推論経路・根拠チャンク・法令）に記載されている内容のみに基づいて生成すること。検索結果に無い情報を生成してはならない。
2. 個別の行政判断（認定の可否、支給区分の決定等）は行わないこと。あくまで制度の一般的な説明にとどめること。
3. 手当額等の金額計算は行わないこと。
4. 検索結果だけでは十分に答えられない場合は、その旨を明記し、手当給付係等の担当窓口へ確認するよう案内すること。
5. 回答は必ず次のJSON形式で出力すること（説明文やコードブロックは付けない）:
{
  "answer": "質問への直接的な回答（1〜3文程度）",
  "reason": "なぜその回答になるかの理由",
  "evidence": ["根拠となる原文の引用（ページ番号付き）を1件以上"],
  "reasoning_path": "概念間の推論経路を短く説明（例: 事実婚 → 消極的要件 → 支給されない）",
  "laws": ["関連する法令・条文名"],
  "confirmations": ["利用者が確認すべき事項や、担当窓口に相談すべき事項"]
}
"""


class AskRequest(BaseModel):
    question: str


app = FastAPI(title="児童扶養手当 GraphRAG")

_retriever = None
_genai_client = None


def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = GraphRetriever()
    return _retriever


def get_genai_client():
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(vertexai=True, project=PROJECT, location=REGION)
    return _genai_client


def build_user_prompt(question, context):
    # Internal ontology IDs (e.g. "LAW-41") are implementation details for
    # graph traversal only - they must never reach the model's input, or it
    # may echo them back as if they were law/concept names the user can
    # search for themselves.
    return json.dumps({
        "question": question,
        "search_results": {
            "concepts": [
                {"name": c["name"], "label": c["label"],
                 "description": c.get("description"), "category": c.get("category")}
                for c in context["concepts"]
            ],
            "paths": [
                [{"from": s["from"], "relation": s["relation"], "to": s["to"]} for s in path]
                for path in context["paths"][:15]
            ],
            "laws": [
                {"name": l["name"], "description": l.get("description"), "page": l.get("page")}
                for l in context["laws"]
            ],
            "chunks": [
                {"text": c["text"], "page": c["page"], "section": c["section"]}
                for c in context["chunks"]
            ],
        },
    }, ensure_ascii=False)


def generate_answer(question, context):
    client = get_genai_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[SYSTEM_PROMPT, build_user_prompt(question, context)],
        config={"response_mime_type": "application/json"},
    )
    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        return {"answer": response.text, "reason": "", "evidence": [],
                "reasoning_path": "", "laws": [], "confirmations": []}


@app.post("/api/ask")
def ask(req: AskRequest):
    retriever = get_retriever()
    context = retriever.retrieve(req.question)
    structured = generate_answer(req.question, context)

    return JSONResponse({
        "result": structured,
        "raw_context": {
            "concept_count": len(context["concepts"]),
            "chunk_count": len(context["chunks"]),
        },
    })


@app.post("/api/compare")
def compare(req: AskRequest):
    retriever = get_retriever()

    vector_ctx = retriever.retrieve_vector_only(req.question)
    vector_answer = generate_answer(req.question, vector_ctx)

    graph_ctx = retriever.retrieve(req.question)
    graph_answer = generate_answer(req.question, graph_ctx)

    return JSONResponse({
        "vector_only": {
            "result": vector_answer,
            "concept_count": 0,
            "chunk_count": len(vector_ctx["chunks"]),
        },
        "graph_rag": {
            "result": graph_answer,
            "concept_count": len(graph_ctx["concepts"]),
            "chunk_count": len(graph_ctx["chunks"]),
        },
    })


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
