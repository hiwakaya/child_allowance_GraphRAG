"""AI Orchestrator + Agent UI backend (Cloud Run).

Wraps retriever.graph_retriever.GraphRetriever with a Gemini call that
synthesizes a Japanese answer strictly grounded in the retrieved context,
following CLAUDE.md's EXPLAINABILITY POLICY (回答/理由/根拠/推論経路/法令/確認事項)
and PRIMARY OBJECTIVE constraints (GraphRAGは行政判断・金額計算を行わない).
"""
import json
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from google.auth.transport import requests as google_auth_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from retriever.graph_retriever import GraphRetriever  # noqa: E402
from retriever.secrets_util import get_secret  # noqa: E402

PROJECT = "driven-backbone-479003-v3"
REGION = "asia-northeast1"
GEMINI_MODEL = "gemini-2.5-flash"

# Public OAuth client identifier (not a secret) - the "Web application" OAuth
# client created for the former IAP setup, reused here for Google Identity
# Services sign-in now that the LB/IAP stack has been retired to cut its
# flat ~$18/month forwarding-rule cost. Access control is now enforced at
# the application layer instead of the network layer (see require_login()).
OAUTH_CLIENT_ID = "390463753824-jkcfq6j42b3fgqthbi9mm0f0hel2575o.apps.googleusercontent.com"

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


CHECK_SYSTEM_PROMPT = """あなたは「児童扶養手当 申請書チェック支援アシスタント」です。
以下のルールを厳守してください。

1. アップロードされたPDF（記入済みの申請書等）の内容と、与えられた検索結果（必要書類・支給要件に関する制度知識）を照らし合わせ、記入漏れ・添付書類の不足・記載内容の不整合の可能性を指摘すること。
2. 支給の可否や認定の可否についての最終判断は行わないこと。あくまで「確認すべき点」の指摘にとどめ、最終判断は窓口担当者に委ねること。
3. 手当額の計算は行わないこと。
4. 個人情報（氏名・住所・所得額・生年月日等）は、指摘に必要な最小限を除き、回答内でそのまま複製しないこと。「氏名欄」「所得欄」のように項目名で言及し、実際の記載値の引用は避けること。
5. 検索結果や申請書に無い情報を生成しないこと。
6. 回答は必ず次のJSON形式で出力すること（説明文やコードブロックは付けない）:
{
  "summary": "全体の確認結果の要約（1〜2文）",
  "issues": [
    {"item": "指摘対象の項目・添付書類名", "issue": "具体的な問題点", "reference": "根拠となる制度知識（ページ番号付き）"}
  ],
  "missing_attachments": ["不足している可能性のある添付書類"],
  "confirmations": ["担当窓口に確認すべき事項"]
}
"""


class AskRequest(BaseModel):
    question: str


class GoogleLoginRequest(BaseModel):
    credential: str


app = FastAPI(title="児童扶養手当 GraphRAG")
app.add_middleware(SessionMiddleware, secret_key=get_secret("webapp-session-secret"),
                    same_site="lax", https_only=True)

_retriever = None
_genai_client = None
_allowed_emails = None
_keepalive_token = None


def get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = GraphRetriever()
    return _retriever


def get_allowed_emails():
    global _allowed_emails
    if _allowed_emails is None:
        _allowed_emails = {e.strip().lower() for e in get_secret("webapp-allowed-emails").split(",") if e.strip()}
    return _allowed_emails


def get_keepalive_token():
    global _keepalive_token
    if _keepalive_token is None:
        _keepalive_token = get_secret("webapp-keepalive-token")
    return _keepalive_token


def require_login(request: Request):
    email = request.session.get("email")
    if not email or email not in get_allowed_emails():
        raise HTTPException(status_code=401, detail="ログインが必要です。")
    return email


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


@app.post("/api/auth/google")
def auth_google(req: GoogleLoginRequest, request: Request):
    try:
        payload = google_id_token.verify_oauth2_token(
            req.credential, google_auth_requests.Request(), OAUTH_CLIENT_ID)
    except ValueError:
        raise HTTPException(status_code=401, detail="トークンの検証に失敗しました。")

    email = (payload.get("email") or "").lower()
    if not payload.get("email_verified") or email not in get_allowed_emails():
        raise HTTPException(status_code=403, detail="このアカウントにはアクセス権がありません。")

    request.session["email"] = email
    return JSONResponse({"email": email})


@app.get("/api/auth/me")
def auth_me(request: Request):
    email = request.session.get("email")
    if not email or email not in get_allowed_emails():
        return JSONResponse({"email": None})
    return JSONResponse({"email": email})


@app.post("/api/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return JSONResponse({"status": "ok"})


@app.post("/api/ask")
def ask(req: AskRequest, _email: str = Depends(require_login)):
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
def compare(req: AskRequest, _email: str = Depends(require_login)):
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


def build_check_prompt(note, context):
    return json.dumps({
        "note": note,
        "search_results": {
            "chunks": [
                {"text": c["text"], "page": c["page"], "section": c["section"]}
                for c in context["chunks"]
            ],
        },
    }, ensure_ascii=False)


@app.post("/api/check-application")
async def check_application(file: UploadFile = File(...), note: str = Form(""),
                             _email: str = Depends(require_login)):
    if file.content_type != "application/pdf":
        return JSONResponse({"error": "PDFファイルのみ対応しています。"}, status_code=400)

    # Read into memory only - never written to disk, never logged, never
    # passed to the retriever/graph/vector store. Goes out of scope (and is
    # garbage collected) once this request finishes. See CLAUDE.md's MCP
    # SEPARATION RULE: GraphRAG must not persist personal/application data.
    pdf_bytes = await file.read()

    retriever = get_retriever()
    context = retriever.retrieve("認定請求に必要な添付書類 支給要件 確認事項")

    client = get_genai_client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            CHECK_SYSTEM_PROMPT,
            build_check_prompt(note, context),
        ],
        config={"response_mime_type": "application/json"},
    )

    try:
        structured = json.loads(response.text)
    except json.JSONDecodeError:
        structured = {"summary": response.text, "issues": [],
                      "missing_attachments": [], "confirmations": []}

    return JSONResponse({"result": structured})


@app.get("/api/keepalive")
def keepalive(request: Request):
    """Touched periodically by Cloud Scheduler so the Neo4j Aura Free
    instance never sits idle long enough to auto-pause (see project memory:
    Aura Free paused after inactivity on 2026-08-24, requiring manual resume).

    Now that the LB/IAP stack is gone, Cloud Run's IAM invoker check no
    longer restricts callers (allUsers has roles/run.invoker so the app is
    network-reachable by anyone) - this endpoint is unauthenticated at the
    transport layer, so it checks a shared-secret header instead to stop
    randoms from spinning up Neo4j sessions."""
    if request.headers.get("X-Keepalive-Token") != get_keepalive_token():
        raise HTTPException(status_code=403, detail="forbidden")
    retriever = get_retriever()
    with retriever.driver.session() as session:
        session.run("RETURN 1").consume()
    return JSONResponse({"status": "ok"})


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
