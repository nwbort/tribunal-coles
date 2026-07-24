#!/usr/bin/env python3
"""
Parse the documents table out of a saved current-matters page.

The tribunal publishes each matter's filings as a simple HTML table:

    | Date filed | Filed by | Description (link) | Confidentiality |

parse_documents() turns that table into a list of dicts with only the keys
that are available on the page, plus a repo-relative ``url_gh`` pointing at
where the downloaded file lives:

    {
      "date": "2026-07-21",
      "filed_by": "-",
      "description": "Directions",
      "confidentiality": "Non-confidential",
      "url": "https://www.competitiontribunal.gov.au/.../Directions.pdf",
      "url_gh": "/documents/Directions.pdf"
    }

Run standalone to parse a saved HTML file and print the JSON:

    parse_documents.py page.html [DOCS_DIR]
"""

import json
import sys
from datetime import datetime
from html import unescape
from html.parser import HTMLParser

DEFAULT_DOCS_DIR = "documents"


def normalize_date(text: str) -> str:
    """'21 July 2026' -> '2026-07-21'; leave unrecognised text untouched."""
    text = text.strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text


class _DocTableParser(HTMLParser):
    """Collect the rows of every bordered table on the page.

    Each cell becomes ``{"text": ..., "href": ...}`` where ``text`` excludes
    the ``<em>(PDF, 231.0 KB)</em>`` size hint so the description comes out
    clean, and ``href`` is the first link in the cell (or None)."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[dict]] = []
        self._in_table = False
        self._in_cell = False
        self._in_em = False
        self._row: list[dict] | None = None
        self._row_has_th = False
        self._cell_text: list[str] = []
        self._cell_href: str | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "table":
            if "table-bordered" in (attrs.get("class") or ""):
                self._in_table = True
        elif self._in_table and tag == "tr":
            self._row = []
            self._row_has_th = False
        elif self._row is not None and tag in ("td", "th"):
            self._in_cell = True
            self._cell_text = []
            self._cell_href = None
            if tag == "th":
                self._row_has_th = True
        elif self._in_cell and tag == "a" and self._cell_href is None:
            self._cell_href = attrs.get("href")
        elif self._in_cell and tag == "em":
            self._in_em = True

    def handle_endtag(self, tag):
        if tag == "table" and self._in_table:
            self._in_table = False
        elif tag == "tr" and self._row is not None:
            if self._row and not self._row_has_th:
                self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._in_cell:
            self._in_cell = False
            text = unescape("".join(self._cell_text)).strip()
            if self._row is not None:
                self._row.append({"text": text, "href": self._cell_href})
        elif tag == "em" and self._in_em:
            self._in_em = False

    def handle_data(self, data):
        if self._in_cell and not self._in_em:
            self._cell_text.append(data)


def parse_documents(html: str, docs_dir: str = DEFAULT_DOCS_DIR) -> list[dict]:
    parser = _DocTableParser()
    parser.feed(html)

    documents = []
    for row in parser.rows:
        if len(row) < 4:
            continue
        url = row[2]["href"]
        if not url:
            continue
        filename = url.rstrip("/").split("/")[-1]
        documents.append(
            {
                "date": normalize_date(row[0]["text"]),
                "filed_by": row[1]["text"],
                "description": row[2]["text"],
                "confidentiality": row[3]["text"],
                "url": url,
                "url_gh": f"/{docs_dir}/{filename}",
            }
        )
    return documents


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: parse_documents.py page.html [DOCS_DIR]", file=sys.stderr)
        return 1
    with open(sys.argv[1], encoding="utf-8") as f:
        html = f.read()
    docs_dir = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_DOCS_DIR
    documents = parse_documents(html, docs_dir=docs_dir)
    print(json.dumps({"documents": documents}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
