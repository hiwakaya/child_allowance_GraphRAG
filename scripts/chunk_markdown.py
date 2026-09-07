"""Phase4: chunk normalized markdown into 500-1000 char chunks (100 char overlap)
with metadata (chunk_id, source, page, section, category, revision) for the
Vector Knowledge Base (Google Cloud Vector Search).

Processes every markdown file listed in INPUT_MD_FILES (each with its own
front-matter source/revision), numbering chunk_id continuously across all of
them, and writes the combined result to OUTPUT_JSONL.
"""
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKDOWN_DIR = REPO_ROOT / "markdown"
INPUT_MD_FILES = [
    MARKDOWN_DIR / "sapporo_jido_fuyo_teate_manual.md",
    MARKDOWN_DIR / "leaflet_hattei_keisan.md",
    MARKDOWN_DIR / "form_a03.md",
    MARKDOWN_DIR / "form_a04.md",
    MARKDOWN_DIR / "form_a07.md",
    MARKDOWN_DIR / "form_a09.md",
    MARKDOWN_DIR / "form_a08.md",
]
OUTPUT_JSONL = REPO_ROOT / "vector_kb" / "chunks.jsonl"

CHUNK_MIN = 500
CHUNK_MAX = 1000
OVERLAP = 100

# coarse section-name -> ontology domain category, based on the manual's
# table of contents structure (see ontology/nodes.csv for the detailed mapping)
CATEGORY_KEYWORDS = [
    (("支給要件", "用語解説", "認定までの流れ", "外国人に係る認定請求", "遺棄の基準",
      "資格喪失", "施設入所", "住所変更", "住登同一", "異住登", "別居監護",
      "その他の届出", "申立書の証明", "職権処理", "障がいの判定基準", "有期認定",
      "一部支給停止適用除外事由届"), "Eligibility"),
    (("所得制限", "生計維持児童", "生計別", "養育費"), "Income"),
    (("災害特例", "年金併給"), "Benefit"),
    (("支払・時効", "現況届２年間未提出者の取扱い", "差止", "債権（返還金）",
      "支払調整", "適正受給", "額改定請求書"), "Event"),
    (("マイナンバー制度", "ＤＶ被害者への対応", "システム入力", "主な出力リスト一覧",
      "通報時の対応", "ＪＲ通勤定期の特別割引制度", "Ｑ＆Ａ", "不備書類や書類の補正",
      "認定請求（添付書類）", "認定請求（留意事項）"), "General"),
    # リーフレット（児扶手制度（手当額計算方法等）.pdf）・様式4件（2026-09-05取込）
    (("支給額表", "一部支給の手当額計算", "手当額の算出方法", "支給区分の判定"), "Benefit"),
    (("扶養義務者の所得の計算", "所得とは"), "Income"),
    (("別居の母（父）が児童を監護している旨の申立書",
      "事実婚解消申立書",
      "父(母)が児童を遺棄している旨の申立書",
      "住民登録上の住所と現住所が異なる旨の申立書",
      "世帯分離申立書"), "Eligibility"),
]


def categorize(section):
    for keywords, category in CATEGORY_KEYWORDS:
        if any(section.startswith(k) for k in keywords):
            return category
    return "General"


def parse_front_matter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    revision = "unknown"
    source = "sapporo_jido_fuyo_teate_manual"
    body_start = 0
    if m:
        fm = m.group(1)
        rev_match = re.search(r"^revision:\s*(.+)$", fm, re.MULTILINE)
        src_match = re.search(r"^source:\s*(.+)$", fm, re.MULTILINE)
        if rev_match:
            revision = rev_match.group(1).strip()
        if src_match:
            source = src_match.group(1).strip()
        body_start = m.end()
    return source, revision, text[body_start:]


def parse_blocks(body):
    """Walk the markdown line by line, yielding (text, page, section) tuples
    for each non-empty paragraph block, tracking the current page marker and
    the most recent ## heading."""
    page = 1
    section = "はじめに"
    in_toc = False
    blocks = []
    for raw_line in body.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        page_match = re.match(r"^<!-- page: (\d+) -->$", line)
        if page_match:
            page = int(page_match.group(1))
            continue
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            in_toc = False
            section = heading_match.group(1).strip()
            continue
        if line == "目次":
            in_toc = True
            continue
        if in_toc:
            if "…" in line:
                # still a dot-leader TOC entry ("見出し…………12"): keep skipping
                continue
            in_toc = False
            # fall through: this line is real content, process normally
        if line.startswith("### "):
            # keep sub-heading text as part of the flowing content, not a new section
            blocks.append((line[4:].strip(), page, section))
            continue
        blocks.append((line, page, section))
    return blocks


def make_chunks(blocks, source, revision, start_num=0):
    """Returns (chunks, next_start_num) so chunk_id numbering can continue
    across multiple source documents (see main())."""
    chunks = []
    buf = ""
    buf_page = None
    buf_section = None
    chunk_num = start_num

    def flush(next_overlap_text=""):
        nonlocal buf, buf_page, buf_section, chunk_num
        if not buf.strip():
            return next_overlap_text
        chunk_num += 1
        chunks.append({
            "chunk_id": f"CHUNK-{chunk_num:04d}",
            "text": buf.strip(),
            "source": source,
            "page": buf_page,
            "section": buf_section,
            "category": categorize(buf_section),
            "revision": revision,
        })
        # carry the tail as overlap into the next chunk
        tail = buf[-OVERLAP:] if len(buf) > OVERLAP else buf
        return tail

    for text, page, section in blocks:
        if buf_page is None:
            buf_page = page
            buf_section = section

        candidate = (buf + "\n" + text) if buf else text

        if len(candidate) > CHUNK_MAX and len(buf) >= CHUNK_MIN:
            overlap_tail = flush()
            buf = (overlap_tail + "\n" + text) if overlap_tail else text
            buf_page = page
            buf_section = section
        else:
            buf = candidate

        if len(buf) >= CHUNK_MAX:
            overlap_tail = flush()
            buf = overlap_tail
            buf_page = page
            buf_section = section

    flush()
    return chunks, chunk_num


def main():
    chunks = []
    next_num = 0
    for md_path in INPUT_MD_FILES:
        text = md_path.read_text(encoding="utf-8-sig")
        source, revision, body = parse_front_matter(text)
        blocks = parse_blocks(body)
        doc_chunks, next_num = make_chunks(blocks, source, revision, start_num=next_num)
        chunks.extend(doc_chunks)
        print(f"{md_path.name}: {len(doc_chunks)} chunks (source={source})")

    OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    sizes = [len(c["text"]) for c in chunks]
    print(f"Total chunks: {len(chunks)}")
    print(f"Size min/max/avg: {min(sizes)}/{max(sizes)}/{sum(sizes)//len(sizes)}")
    under_min = sum(1 for s in sizes if s < CHUNK_MIN)
    over_max = sum(1 for s in sizes if s > CHUNK_MAX)
    print(f"Chunks under {CHUNK_MIN} chars: {under_min} (last chunk of doc is expected to be short)")
    print(f"Chunks over {CHUNK_MAX} chars: {over_max}")
    from collections import Counter
    cat_counts = Counter(c["category"] for c in chunks)
    print("Category distribution:", dict(cat_counts))
    print(f"Wrote: {OUTPUT_JSONL}")


if __name__ == "__main__":
    main()
