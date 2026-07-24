# Scheduled scraper

For https://www.competitiontribunal.gov.au/current-matters/act-1-of-2026

The scraper drives a real Chrome (via nodriver) to get past Cloudflare's
managed challenge, then:

1. parses the filings table into [`documents.json`](documents.json), and
2. downloads each linked document into [`documents/`](documents/).

## Output

`documents.json` holds only the keys available on the page, plus a
repo-relative `url_gh` pointing at the downloaded copy:

```json
{
  "documents": [
    {
      "date": "2026-07-21",
      "filed_by": "-",
      "description": "Directions",
      "confidentiality": "Non-confidential",
      "url": "https://www.competitiontribunal.gov.au/__data/assets/pdf_file/0020/600284/Directions.pdf",
      "url_gh": "/documents/Directions.pdf"
    }
  ]
}
```

## Running

```bash
./scrape.sh        # scrape + parse + download, as run in CI
```

To parse a saved HTML file without a browser (e.g. for debugging):

```bash
python parse_documents.py page.html            # prints the JSON
```
