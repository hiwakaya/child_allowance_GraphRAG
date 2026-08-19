# CLAUDE.md

# 児童扶養手当 GraphRAG on Google Cloud

## PRIMARY OBJECTIVE

児童扶養手当事務処理マニュアル、法令、通知、QAを基に、Google Cloud上でExplainable GraphRAG基盤を構築する。

GraphRAGの責務:

* 制度知識管理
* 判定根拠探索
* 推論経路提示
* 法令根拠提示
* イベント履歴追跡
* 説明責任支援

GraphRAGは行政判断を行わない。
GraphRAGは金額計算を行わない。

\---

# TARGET ARCHITECTURE (Google Cloud)

Users
-> Agent UI
-> AI Orchestrator (Cloud Run)
-> Graph Retriever API (Cloud Run)

Knowledge Sources

* Cloud Storage

  * PDF
  * DOCX
  * Markdown
  * CSV
  * Rules

Graph Layer

* Neo4j Aura または Neo4j on GCE/GKE

Vector Layer

* Google Cloud Vector Search Service

AI Layer

* Gemini / Generative AI Service

Security

* Secret Manager
* IAM
* Audit Logs

Observability

* Cloud Logging
* Cloud Monitoring

\---

# DESIGN PRINCIPLES

## Explainability First

必ず以下を出力可能とする。

* 回答
* 理由
* 根拠文書
* 推論経路
* 関連法令
* 確認事項

## Decision-Centered Ontology

書類中心設計は禁止。

主ノード:

* Eligibility
* Decision
* Income
* Benefit
* Rule
* Event
* Person（当事者。母・父・養育者・扶養義務者・里親・児童等。2026-08-18追加、後述の実装ノート参照）

## Event Sourcing

状態ではなくイベントを保持する。

\---

# PHASE0 DECISION MODELING

出力:

* decision\_tree.yaml
* eligibility\_rules.yaml
* benefit\_rules.yaml

判定木を先に定義する。

\---

# PHASE1 MARKDOWN NORMALIZATION

入力:

* PDF
* DOCX

出力:

* Markdown

保持:

* page
* heading
* source
* revision
* law\_reference

\---

# PHASE2 ONTOLOGY GENERATION

出力:

* ontology/nodes.csv
* ontology/relations.csv

nodes.csv
id,label,name,description,source,page,category

relations.csv
source,target,relation,source\_doc,page

目標:
150〜300ノード

\---

# ONTOLOGY DOMAINS

Eligibility

* 監護要件
* 生計維持要件
* 婚姻要件
* 居住要件
* 認定
* 受給権

Income

* 給与所得
* 事業所得
* 養育費
* 所得算定額
* 所得制限

Benefit

* 全部支給
* 一部支給
* 全部停止
* 手当額

Event

* 認定
* 差止
* 解除
* 額改定
* 所得変更
* 年金開始
* 年金終了
* 債権発生

Law

* 法
* 施行令
* 施行規則
* 通知

\---

# PHASE3 NEO4J GRAPH CONSTRUCTION

Neo4jへ投入する。

Labels（2026-08-18よりラベル名を日本語化、後述の実装ノート参照）:

* 概念（Concept）
* 支給要件（Eligibility）
* 所得（Income）
* 支給（Benefit）
* 判定（Decision）
* ルール（Rule）
* イベント（Event）
* 法令（Law）
* 当事者（Person。母・父・養育者・扶養義務者・里親・児童等。Eligibility/Conceptから独立させた9番目のラベル）
* Chunk
* Evidence

制約:
name一意（ラベルごと）

検証経路:
当事者（受給資格者）→支給要件→判定（認定）→支給要件（受給権）
所得→ルール→支給区分

\---

## IMPLEMENTATION NOTE（2026-08-18）

オントロジーのラベル名を英語から日本語に変更し、「当事者」ラベルをEligibility/Conceptから
切り出して9番目のラベルとして新設した（ユーザーの明示的な指示による）。

理由・背景:

* 人が見て直感的に分かりやすいことを優先し、ラベル名を日本語化
* 「母・父・養育者・扶養義務者・里親・児童」等の当事者概念は、判定ロジックに直結するため
  Eligibility内の「受給資格者類型」として、または用語解説としてConceptに埋め込まれていたが、
  独立した概念として見えづらいという指摘を受け、Personに相当する「当事者」ラベルを新設した

留意点:

* 「手続・申請」「書類・様式」は依然としてノード化していない（書類中心設計は禁止の原則を維持）
* Decision/Rule/Eventの構造（判定中心オントロジーの中核）は変更していない
* 当事者ノードは実在の個人データではなく、制度上の役割・要件定義（母とは戸籍上の親子関係にある女性、等）
  であることに変わりはなく、MCP分離ルールとの整合は維持されている

\---

# PHASE4 VECTOR KNOWLEDGE BASE

Chunk:
500〜1000文字

Overlap:
100文字

Metadata:

* chunk\_id
* source
* page
* section
* category
* revision

\---

# PHASE5 CONCEPT-CHUNK LINKING

Concept
-> Chunk
-> Document
-> Page

全Conceptは最低1つ以上のChunkに接続すること。

\---

# PHASE6 EVENT GRAPH

イベント:

* 認定
* 資格喪失
* 差止
* 差止解除
* 所得変更
* 額改定
* 年金開始
* 年金終了
* 債権発生
* 返還

タイムライン管理必須。

\---

# PHASE7 RULE GRAPH

rules.yamlで管理。

例:
IF 所得算定額 > 限度額
THEN 全部停止

全DecisionはRuleへ接続すること。

\---

# PHASE8 GRAPH RETRIEVER

1. Concept Search
2. Path Discovery
3. Evidence Discovery
4. Chunk Retrieval
5. Vector Retrieval
6. Context Assembly

出力:

* Concepts
* Paths
* Evidence
* Laws
* Chunks

\---

# EXPLAINABILITY POLICY

根拠の無い回答は禁止。

必ず:

* 回答
* 理由
* 根拠
* 推論経路
* 法令
* 確認事項

を返却可能とする。

\---

# MCP SEPARATION RULE

GraphRAGに個人情報を保存しない。

GraphRAG:

* 制度知識
* ルール
* 概念
* イベント

MCP:

* 住民情報
* 所得情報
* 年金情報
* 申請情報

\---

# TESTING

* Ontology Validation
* Graph Validation
* Event Validation
* Rule Validation
* Path Validation
* Retriever Validation
* Explainability Validation

\---

# SUCCESS CRITERIA

GraphRAG単独で以下を説明できること。

* なぜ認定か
* なぜ却下か
* なぜ全部停止か
* なぜ返還金が発生したか
* 根拠法令は何か
* 根拠マニュアルはどこか

GraphRAGは説明責任基盤として機能すること。

