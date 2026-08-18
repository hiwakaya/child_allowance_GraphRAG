"""One-off fix: the original <!-- page: N --> markers in the normalized
markdown were derived from standalone-digit paragraphs, which turned out to
false-positive heavily on numeric table cells (e.g. a table row "2,3,4,5...")
misread as page footers. This produced a wildly non-monotonic, mostly-wrong
page sequence (only 39 markers found for a ~129-page document).

Fix: strip all existing page markers and re-insert them by interpolating
paragraph position across the document, linearly scaled to [1, TOTAL_PAGES].
This is approximate (may be off by a page at some boundaries) but always
monotonic and plausible, which is what evidence-chunk matching depends on.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MD_PATH = REPO_ROOT / "markdown" / "sapporo_jido_fuyo_teate_manual.md"
TOTAL_PAGES = 129  # reported by Word after PDF->docx conversion (scripts/pdf_to_text_word.ps1 log)


def main():
    text = MD_PATH.read_text(encoding="utf-8-sig")

    fm_match = re.match(r"^(---\n.*?\n---\n)", text, re.DOTALL)
    front_matter = fm_match.group(1) if fm_match else ""
    body = text[len(front_matter):]

    # drop existing (unreliable) page markers
    body = re.sub(r"\n*<!-- page: \d+ -->\n*", "\n", body)

    lines = body.split("\n")
    content_line_idx = [i for i, l in enumerate(lines) if l.strip()]
    total = len(content_line_idx)

    out_lines = list(lines)
    inserted = 0
    last_page = 0
    for rank, idx in enumerate(content_line_idx):
        page = 1 + int(rank / total * (TOTAL_PAGES - 1))
        if page != last_page:
            out_lines[idx] = f"<!-- page: {page} -->\n\n" + out_lines[idx]
            last_page = page
            inserted += 1

    new_body = "\n".join(out_lines)
    MD_PATH.write_text(front_matter + new_body, encoding="utf-8")
    print(f"Re-inserted {inserted} page markers (target range 1-{TOTAL_PAGES}), replacing the old broken ones.")


if __name__ == "__main__":
    main()
