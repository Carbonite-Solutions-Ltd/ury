# 01 — GRA E-VAT API reference (v8.2)

This is the complete API as documented by GRA, **corrected by what the live
staging sandbox actually does**. Wherever the two disagree, the sandbox wins and
the disagreement is marked **⚠ docs differ**. Evidence for every "verified"
claim is in [04-sandbox-verification.md](04-sandbox-verification.md) and the raw
call log in [reference/](reference/).

Legend: ✅ verified live · 📄 from the docs only (not exercised) · ⚠ docs differ

---

## 1. Concepts

| Term | Meaning |
|---|---|
| **E-VAT** | GRA's electronic VAT invoicing system. |
| **VCIS** | *VAT Certified Invoicing System* — the taxpayer's software (for us: URY / ERPNext + `gra_evat`). |
| **VSDC** | *Virtual Sales Data Controller* — GRA's service that validates and **signs** each transaction. |
| **Stamp** | The signature block returned by the VSDC (`ysdc*` fields + `qr_code`). It must be printed on the receipt. |
| **Company reference** | `{TIN}-{branchCode}`, e.g. `CXX000000YY-001`. It is part of the URL, so **every branch has its own reference and key**. |
| **Security key** | A static secret sent in a header on every call. No expiry, no refresh. |
| **Deployment** | *Cloud* (GRA hosts the VSDC) or *On-Prem* (the taxpayer hosts it: Windows Server 2019+ / Windows 10+, 8 GB RAM, 500 GB disk). GRA recommends on-prem for high invoice volumes. |

## 2. Transport

| Item | Value |
|---|---|
| Base URL (staging) ✅ | `https://vsdcstaging.vat-gh.com/vsdc/api/v1/taxpayer/{companyReference}` |
| Base URL (production) | Issued by GRA at onboarding (cloud) or the on-prem server's address. |
| Auth header ✅ | `security_key: <key>` (header name is case-insensitive; samples use both `security_key` and `Security_Key`). |
| Body format ✅ | JSON (`Content-Type: application/json`). XML is also accepted 📄 (`Accept: application/xml` returns XML). **We use JSON only.** |
| Rate limit ✅ | 50 requests per minute per key → `E990` with **HTTP 429** ⚠ docs say 400. |
| Latency ✅ | Signing: 0.5–5.6 s, median 3.2 s (2026-09-17); ~2 s on 2026-09-07. Callbacks and refunds: 0.4–1.5 s. |
| Clock ✅ | Stamp times are Ghana local time, which is UTC+0. |

## 3. Endpoints

All paths are relative to the base URL.

| Method | Path | Purpose | Status |
|---|---|---|---|
| `GET` | `/health` | Liveness check | ✅ |
| `POST` | `/invoice` | Sign a transaction whose `flag` is `INVOICE`, `REFUND`, `PARTIAL_REFUND`, `PURCHASE` or `PURCHASE_RETURN` | ✅ INVOICE / REFUND / PARTIAL_REFUND · 📄 purchases |
| `POST` | `/cancellation` | `REFUND_CANCELATION` or `PURCHASE_RETURN_CANCELATION` | ✅ refund · 📄 purchase |
| `POST` | `/invoice/callback` | Fetch the stamp of a transaction GRA already signed | ✅ |
| `POST` | `/note` | Credit note / debit note spanning several invoices | 📄 |
| `POST` | `/statment_of_account` | Hospitality folio: one stamped statement over many invoices. **The path really is misspelled.** | 📄 |
| `POST` | `/inventory` | Stock declaration | 📄 |
| `GET` | `/identification/nationalId/{ghanaCardNumber}` | Look up a Ghana Card | ✅ |
| `GET` | `/identification/tin/{tin}` | Look up a TIN. ⚠ **The official collection has this request with an empty URL**; the path was found by probing. | ✅ |

> The collection also defines variables that no request uses: `VSDC_ID`,
> `Vault_Host`, `Inventory_Base_Url` (`https://evat-inventory.persolqa.com`) and
> a **flat-rate taxpayer** (`CXX0000XXXY-001` + key). The flat-rate key passes
> `/health` ✅ but no flat-rate request is documented.

---

## 4. `POST /invoice` — sales, refunds, purchases

One endpoint, five transaction types, selected by `flag`.

### 4.1 Header fields

| Field | Example | Type (docs) | Required | Notes |
|---|---|---|---|---|
| `currency` | `"GHS"` | VARCHAR(20) | yes | One of the 16 supported codes (§9). |
| `exchangeRate` | `1.0` | NUMERIC | yes | `1.0` for GHS. Number or string both accepted ✅. Must be > 0. |
| `invoiceNumber` | `"INV_26_001"` | VARCHAR(100) | yes | Your unique transaction id. For refunds it is the **original sale's** number. ✅ Hard limit **100 chars** — 101 gives `E600` on **HTTP 401**. ✅ `/ _ . space # @` all accepted on staging ⚠ docs say `@`/`!` are rejected (E870). |
| `totalAmount` | `100.0` | NUMERIC | yes | **Strictly Σ(unitPrice × quantity)**, before discounts, regardless of calculation type. Must be > 0 ✅. |
| `totalVat` | `13.04` | NUMERIC | yes | Σ of VAT over all lines. ✅ validated to ±0.50. |
| `totalLevy` | `30.00` | NUMERIC | yes | Σ of levies A–E over all lines (**CST included, excise excluded**). ✅ validated to ±0.50. |
| `totalExciseAmount` | `0.00` | NUMERIC | when excise applies | Σ of line `exciseAmount`. |
| `voucherAmount` | `0.0` | NUMERIC | no | Voucher amount. 📄 |
| `discountType` | `"GENERAL"` | VARCHAR | no | `GENERAL` or `SELECTIVE`. See [02 §5](02-tax-calculation.md#5-discounts). |
| `discountAmount` | `0.0` | NUMERIC | no | Header discount. For `GENERAL` it must equal Σ line discounts ✅. |
| `calculationType` | `"INCLUSIVE"` | VARCHAR(20) | yes | `INCLUSIVE` or `EXCLUSIVE`. Case-sensitive. |
| `flag` | `"INVOICE"` | VARCHAR(20) | yes | `INVOICE`, `REFUND`, `PARTIAL_REFUND`, `PURCHASE`, `PURCHASE_RETURN`. Case-sensitive. |
| `saleType` | `"NORMAL"` | VARCHAR(20) | yes | `NORMAL` or `EXPORT`. |
| `transactionDate` | `"2026-09-17"` | VARCHAR(50) | yes | ✅ `YYYY-MM-DD` or ISO-8601 `YYYY-MM-DDTHH:MM:SSZ`. ✅ **Frappe's `YYYY-MM-DD HH:MM:SS` is rejected** (unparseable body). ✅ Past dates accepted; ✅ **future dates rejected**. ✅ The date selects the **tax regime** (see [02 §2](02-tax-calculation.md#2-two-tax-regimes)). |
| `userName` | `"Kofi Ghana"` | VARCHAR(100) | yes | The cashier / user. |
| `businessPartnerName` | `"James Kofi"` | VARCHAR(100) | yes | Customer name. ✅ Minimum **2 characters**. Docs (E807/E811) say it must match the name first sent for that TIN; staging does not enforce this. |
| `businessPartnerTin` | `"C00000009055"` | VARCHAR(15) | yes (B2B) | Customer TIN or Ghana Card number. B2C placeholder in the samples: `C0000000000`. Docs (E824) say 11 or 13 chars; ✅ staging accepts any length, empty, and Ghana-card format. |
| `reference` | `"RF_INV_26_001"` | VARCHAR(50) | **for refunds** | The refund's own id. ✅ **Must be non-empty and unique** for `REFUND` and `PARTIAL_REFUND` (E805 / E750) ⚠ the docs' own full-refund sample sends `""`, which is rejected. Send `""` for `INVOICE`. |
| `groupReferenceId` | `""` | VARCHAR(50) | no | Groups invoices under one id (statement of account). |
| `purchaseOrderReference` | `""` | — | no | ⚠ Undocumented; present in samples. Used with purchases (E713–E715). |
| `taxType` | `"STANDARD"` | — | no | ⚠ Undocumented; present in 2026 samples. We omitted it in every test and all were accepted ✅. |
| `items` | `[...]` | array | yes | See §4.2. At least one line. |

### 4.2 Line fields (`items[]`)

| Field | Example | Type (docs) | Required | Notes |
|---|---|---|---|---|
| `itemCode` | `"TXC005918138"` | VARCHAR(50) | yes | Unique id for the item. ✅ GRA **remembers the category of each code forever** (E806 if it changes). ✅ One code with two different `unitPrice`s on one invoice is rejected (E827). ✅ The same code twice at the same price is **silently merged** (`ysdcitems` counts distinct codes). ✅ Staging accepts > 101 chars ⚠ docs say 50 (tag table) and 100 (E812). |
| `itemCategory` | `""` | VARCHAR(50) | yes | `""` standard · `EXM` exempt/zero-rated · `CST` communications · `TRSM` tourism · `RNT` rent · `EXC_PLASTIC` plastic excise. ✅ **Categories are enabled per taxpayer**: `RNT` returned E751 on the test taxpayer. ✅ One category per line — a line cannot carry both CST and tourism. |
| `description` | `"Bowl"` | VARCHAR(100) | yes | Item name. ✅ Renaming a code between invoices is accepted on staging ⚠ docs E826. |
| `quantity` | `10.0` | NUMERIC | yes | ✅ Fractional quantities accepted. ✅ Must be > 0. |
| `unitPrice` | `10.0` | NUMERIC | yes | Inclusive or exclusive of tax per `calculationType`. ✅ Must be > 0 — **complimentary lines cannot be sent at price 0**. |
| `levyAmountA` | `2.05` | NUMERIC | yes | NHIL 2.5 %. |
| `levyAmountB` | `2.05` | NUMERIC | yes | GETFund 2.5 %. |
| `levyAmountC` | `0.8` | NUMERIC | pre-2026 only | COVID 1 %. **Only for transaction dates before 2026-01-01.** 2026 samples omit it; omission is accepted ✅. |
| `levyAmountD` | `0.0` | NUMERIC | yes | CST 5 %. |
| `levyAmountE` | `0.0` | NUMERIC | yes | Tourism 1 %. |
| `discountAmount` | `0.0` | NUMERIC | no | Line discount, on the **same basis as `unitPrice`** (gross for inclusive). A 100 % line discount is accepted ✅. |
| `exciseAmount` | `10` | NUMERIC | when applicable | Excise on the line. |
| `batchCode` | `"5MAKD1"` | VARCHAR(100) | no | Batch number. |
| `expireDate` | `""` | VARCHAR(45) | no | Expiry date. |

> The per-line VAT amount is **not** sent — only the invoice-level `totalVat`.

### 4.3 Flag semantics ✅

| Flag | `invoiceNumber` | `reference` | Receipt prefix | Stamp `flag` returned |
|---|---|---|---|---|
| `INVOICE` | new, unique | `""` | `NS` | `INVOICE` |
| `REFUND` | original sale | new, unique, non-empty | `NR` | `REFUND` |
| `PARTIAL_REFUND` | original sale | new, unique, non-empty | `NR` | **`REFUND`** ⚠ |
| `PURCHASE` 📄 | new, unique | `""` | — | — |
| `PURCHASE_RETURN` 📄 | original purchase | new, unique | — | — |

Refund rules verified live:
- Each refund's lines use the original's item codes; over-refunding a line's
  remaining quantity → `E828` ("item quantity exceeded") ⚠ docs E829.
- Several partial refunds may be issued against one sale, each with its own
  `reference`.
- Once **any** refund exists, a `REFUND` for the **full original amount** fails
  (`E725`). Refund the remainder with `PARTIAL_REFUND`.
- Staging accepts a `REFUND` that covers only part of the sale, but we will
  follow the docs: `REFUND` only for a first refund that reverses 100 %.
- Cancelling a refund **restores** that quantity for future refunds.

### 4.4 Success response ✅

HTTP 200:

```json
{
  "response": {
    "distributor_tin": "CXX000000YY",
    "message": {
      "num": "URYT260907103401-A",
      "ysdcid": "E000001001",
      "ysdcrecnum": "1001-632B-NS56",
      "ysdcintdata": "YKPV-HVY6-CUI3-WUL6-T3LX-UNTD-DM",
      "ysdcregsig": "EZCU-YJM2-PELK-T5DD",
      "ysdcmrc": "00:0C:29:0D:90:D0",
      "ysdcmrctim": "2026/09/07 10:34:03",
      "ysdctime": "2026/09/07 10:34:03",
      "flag": "INVOICE",
      "ysdcitems": "1"
    },
    "qr_code": "https://verification.vat-gh.com?data=...&v=1.1&t=i",
    "status": "SUCCESS"
  }
}
```

| Field | Receipt label | Meaning |
|---|---|---|
| `distributor_tin` | TIN | Taxpayer's TIN |
| `message.num` | Invoice No | The `invoiceNumber` we sent |
| `message.ysdcid` | SDC ID | Id of the signing SDC |
| `message.ysdcrecnum` | Receipt Number | SDC receipt number. Format `{sdc}-{seq}-{type}{n}`; type is `NS` sale, `NR` refund, `CR` refund cancellation |
| `message.ysdcintdata` | Internal Data | Internal data |
| `message.ysdcregsig` | Signature | Invoice signature |
| `message.ysdcmrc` | MRC | Machine Registration Code |
| `message.ysdcmrctim` | — | Time received at the backend. ⚠ The docs call this `ysdcmrctime`; the real key is **`ysdcmrctim`**. |
| `message.ysdctime` | Date & Time | Time stamped. Format `YYYY/MM/DD HH:MM:SS`. |
| `message.flag` | — | Transaction type (see §4.3) |
| `message.ysdcitems` | Line-Item Count | **Distinct** item codes on the transaction |
| `qr_code` | QR code | A URL to render as a QR image, **at least 2.5 cm × 2.5 cm** on the receipt |
| `status` | — | `SUCCESS` |

> Receipt sequence numbers are consumed even by some failed requests (a
> rejected 110-char invoice number skipped a number), but a failed request
> leaves **no transaction** at GRA (callback returns E704) ✅.

Error responses are covered in [03-errors-and-responses.md](03-errors-and-responses.md).

---

## 5. `POST /cancellation` — refund cancellation ✅

Reverses a previously signed **refund** (not a sale).

```json
{
  "invoiceNumber": "INV_26_001",
  "reference": "RF_INV_26_001",
  "userName": "Kofi Ghana",
  "flag": "REFUND_CANCELATION",
  "transactionDate": "2026-09-17T12:00:00Z",
  "totalAmount": 180.0
}
```

| Field | Notes |
|---|---|
| `invoiceNumber` | The original sale. |
| `reference` | The refund being cancelled. |
| `flag` | `REFUND_CANCELATION` or `PURCHASE_RETURN_CANCELATION`. ⚠ **One L** — the docs' prose says "CANCELLATION", the payload value is `CANCELATION`. |
| `totalAmount` | The refund's total. ✅ **Not validated** — a wrong value was accepted. We will still send the correct value. |
| `transactionDate` | ISO-8601 in all samples. |

Response: the §4.4 success envelope with `flag: REFUND_CANCELATION`, receipt
prefix `CR`. Cancelling the same refund twice → `E729` ✅.

---

## 6. `POST /invoice/callback` — recover a stamp ✅

```json
{ "invoiceNumber": "INV_26_001", "reference": "", "flag": "INVOICE" }
```

| To recover… | `flag` | `reference` |
|---|---|---|
| a sale | `INVOICE` | `""` |
| a full **or partial** refund | **`REFUND`** (not `PARTIAL_REFUND` → E704) | the refund's reference |
| a refund cancellation | `REFUND_CANCELATION` | the cancelled refund's reference |

- Returns the **byte-identical** stamp of the original signing (same receipt
  number, signature, internal data and QR) ✅.
- If GRA has no such transaction → `E704 Transaction was not found.` ✅
- So callback is both **stamp recovery** and a **"did GRA receive it?" check**.
- Fast: 0.4–0.9 s.

---

## 7. Lookups ✅

### 7.1 `GET /identification/tin/{tin}`

```json
{"status": "SUCCESS", "data": {"tin": "C0034186913", "name": "SPRING DATA WORKS. LIMITED"}}
```
- Not found → **HTTP 200** with `{"status": "NOT_FOUND", "data": null}`. Check `status`, not the HTTP code.
- ✅ Looking up the B2C placeholder `C0000000000` **hung until timeout** (20 s). Never look up the placeholder.
- ⚠ The docs' sample shows more fields (`type`, `sector`, `address`); the live response returned only `tin` and `name`.

### 7.2 `GET /identification/nationalId/{ghanaCardNumber}`

Same response shape. Placeholder cards returned `NOT_FOUND` ✅.

### 7.3 `GET /health`

`{"status": "UP"}` (XML: `<ResponseDto><status>UP</status></ResponseDto>`). A
wrong key returns `E900` on HTTP 401 ✅.

---

## 8. Documented but out of scope for v1 📄

### 8.1 `POST /note` — credit / debit note

For a credit or debit spanning **several** invoices (a refund applies to one).

| Field | Required | Notes |
|---|---|---|
| `noteNumber` | yes | Unique note id, VARCHAR(50) |
| `currency`, `exchangeRate` | yes | |
| `noteAmount` | yes | Total of the note |
| `calculationType` | no | Defaults to `INCLUSIVE` |
| `flag` | yes | `CREDIT_NOTE` or `DEBIT_NOTE` |
| `noteLineFlag` | no | `INVOICE` (default) or `PURCHASE` |
| `businessPartnerName`, `businessPartnerTin` | name yes; TIN for B2B | |
| `userName`, `transactionDate` | yes | |
| `groupReferenceId`, `remarks` | no | |
| `noteLines[]` | yes | `{invoiceNumber, invoiceDate, invoiceAmount}` |

Related errors (docs): E721 (a credited/debited invoice cannot be partially
refunded), E722 (note already exists), E723 (duplicate invoice in the note),
E724 (note amount exceeds the invoices).

### 8.2 `POST /statment_of_account` — hospitality folio

"Implemented for the hospitality industries, this allows for a single invoice
(a combination of all invoices from the PMS & PoS) to be printed at the end of
a stay." Relevant to URY's iHotel room-charge flow (Phase 5).

| Field | Required | Notes |
|---|---|---|
| `currency`, `exchangeRate`, `calculationType` | yes | |
| `totalVat`, `totalAmount`, `totalLevies` | yes | ⚠ `totalLevies` here, `totalLevy` on invoices |
| `userName`, `businessPartnerName`, `businessPartnerTin`, `transactionDate` | yes | |
| `groupReferenceId` | **yes** | Ties the statement to its invoices |
| `groupInvoiceLines[]` | yes | `{currency, exchangeRate, calculationType, invoiceNumber, reference, flag, invoiceVat, invoiceAmount, invoiceLevies, transactionDate}`. ⚠ The tag table names the id `transactionId`; the sample uses `invoiceNumber`. Lines may be `INVOICE`, `REFUND`, `PARTIAL_REFUND`, `CREDIT_NOTE`, `DEBIT_NOTE`, `REFUND_CANCELATION`. |

E703: every transaction tied to the group reference must be in the payload.
E881: group reference not found.

### 8.3 `POST /inventory`

```json
{"inventories": [{"code": "04004X", "description": "Yogo", "quantity": 3,
  "batchCode": "0001", "unitPrice": 100.0, "expiryDate": "2024-04-04"}],
 "inventoryDate": "2024-04-04"}
```
Response: `{"status": "SUCCESS"}`.

### 8.4 Purchases

`PURCHASE` and `PURCHASE_RETURN` use the §4 payload; `PURCHASE_RETURN_CANCELATION`
uses §5. Related errors: E710–E716, E730.

---

## 9. Supported currencies

From GRA's published list ([reference/supported-currencies.csv](reference/supported-currencies.csv)):

`AED` UAE · `CAD` Canada · `CHF` Switzerland · `CFA` French West Africa ·
`CNY` China · `EUR` Europe · `GBP` Britain · **`GHS` Ghana** · `HKD` Hong Kong ·
`INR` India · `JPY` Japan · `LRD` Liberia · `NGN` Nigeria · `SLE` Sierra Leone ·
`USD` USA · `ZAR` South Africa

> The docs' tag table says "GHS, USD, EUR or GBP"; the published list is the
> 16 above. Refunds must use the invoice's currency (E825).

## 10. Staging credentials (public)

These are published by GRA in the docs. They are **not secrets**. Production
keys **must never** be committed anywhere.

| Reference | Key | Note |
|---|---|---|
| `CXX000000YY-001` | `Z60gftKe9sei3xOZhvvDa0StkVILKR3j5MBM9ygi1zg=` | Default in the docs; **heavily shared, often E990** |
| `CXX000000YY-006` | `xbPeYDaPFG7bqnNO7WThWRDrBhKggz+ls/6rV38zyA1iqe7dPg8Pc2EElmrUq+2v` | **Use this one for development** |
| `CXX000000YY-007` | `49BvCVhgjRxx3kbE4hiCLZrq8VKjKpKt0zfW1pJg9wClpcXOttM6cV83UtitMAx3` | healthy |
| `CXX000000YY-008` | `Yqu34/kLbewAY1NCH3lKjUEaZFFNtoxpiLzKGI8JrcdrUmxO9ud8dZO2Nx/mQPAE` | healthy |
| `CXX0000XXXY-001` (flat rate) | `OcXp9FnGEqOXpuJ3/ID2e1iVRGk1PIbF7iOWTNo69FH5Hf3Lj+5Z2aPccMsG6Fvb` | `/health` OK; no flat-rate requests documented |

Receipt numbers encode the branch: key `-001` issues `1001-…`, key `-006`
issues `1006-…`.
