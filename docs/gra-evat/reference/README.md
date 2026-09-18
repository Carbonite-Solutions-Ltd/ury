# reference/ — source material

Copies of everything the planning pack is based on, so nothing depends on an
external page staying online. **Do not edit these files**; re-fetch them
instead (commands below).

| File | What it is | Source | Fetched |
|---|---|---|---|
| `postman-collection-v8.2.json` | The official collection "For Taxpayers-GRA E-VAT API - VER 8.2": 13 folders, 20 requests, every description, body and sample response | `https://documenter.gw.postman.com/api/collections/29809098/2sBXVeGCzK?segregateAuth=true&versionTag=latest` (the data behind <https://documenter.getpostman.com/view/29809098/2sBXVeGCzK>) | 2026-09-17 (unchanged since 2026-09-07) |
| `postman-collection-v8.2.txt` | The same collection flattened to plain text for reading and `grep` | generated from the JSON | 2026-09-17 |
| `tax-calculation-template.xlsx` | GRA's tax-calculation workbook (10 scenarios, exclusive and inclusive) linked from the docs | Google Sheets export of `1PHctBuGkW6KG_O4id_1PYLPnirfC6ouo` | 2026-09-17 |
| `tax-calculation-template.txt` | The workbook flattened (row, column, value) | generated from the xlsx | 2026-09-17 |
| `supported-currencies.csv` | GRA's 16 supported currencies | Google Sheets export of `1geCW7gk-LvHiAXQsigNDObDsFYCXS-pSGGBKQx78JkI` | 2026-09-17 |
| `sample-receipt-pos.png` | GRA's sample thermal (POS) receipt | `https://content.pstmn.io/36f82f30-62d8-4de4-88bc-019379a496e5/cG9zIHNhbXBsZS5wbmc=` | 2026-09-17 |
| `sample-receipt-a4.png` | GRA's sample A4 VAT invoice | `https://content.pstmn.io/2c4e828a-22ec-411e-8ee0-ab34849d1f86/U2FtcGxlIGludm9pY2UucG5n` | 2026-09-17 |
| `sandbox-probes-2026-09-17.jsonl` | Every `POST` made to the staging sandbox on 2026-09-17 — one JSON object per line: `label`, `path`, `request`, `http`, `seconds`, `response`. No keys. | our probes | 2026-09-17 |
| `sandbox_probe.py` | The probe harness used to make those calls (contains GRA's **public** staging keys only) | ours | 2026-09-17 |

## Checksums (SHA-256, first 16 hex)

Use these to tell whether GRA has changed the published material. Google's
xlsx export can change bytes between downloads even when nothing changed, so
for the workbook compare the flattened `.txt` instead.

```
ebdc8bf7ca085bbe  postman-collection-v8.2.json
bdbbe22ad5bed7fc  tax-calculation-template.xlsx
c42481e62de18532  supported-currencies.csv
972cc473f08ec91e  sample-receipt-pos.png
532ef1b682fdacc8  sample-receipt-a4.png
```

## Re-fetching

```bash
UA="Mozilla/5.0"
curl -s -A "$UA" "https://documenter.gw.postman.com/api/collections/29809098/2sBXVeGCzK?segregateAuth=true&versionTag=latest" -o postman-collection-v8.2.json
curl -sL -A "$UA" "https://docs.google.com/spreadsheets/d/1PHctBuGkW6KG_O4id_1PYLPnirfC6ouo/export?format=xlsx" -o tax-calculation-template.xlsx
curl -sL -A "$UA" "https://docs.google.com/spreadsheets/d/1geCW7gk-LvHiAXQsigNDObDsFYCXS-pSGGBKQx78JkI/export?format=csv" -o supported-currencies.csv
```
If a checksum changes, diff the new collection against the old one and update
[01-api-reference.md](../01-api-reference.md) and
[03-errors-and-responses.md](../03-errors-and-responses.md).

## Querying the sandbox log

```bash
# every rejected call, with its code
python3 -c "
import json
for l in open('sandbox-probes-2026-09-17.jsonl'):
    r = json.loads(l); resp = r['response']
    if not (isinstance(resp, dict) and resp.get('response')):
        print(r['http'], r['label'], '->', resp.get('code') if isinstance(resp, dict) else resp)
"
```
