# 03 — Errors and responses

The official error table is useful but **not reliable**: several codes are
shifted by one, HTTP statuses differ, and three of the five response shapes
aren't documented at all. This page gives the shapes, the verified behaviour,
and how `gra_evat` must react to each outcome.

---

## 1. The five response shapes ✅

A client must recognise all five. **Classify by shape and code first, HTTP
status second** — for example, an over-long invoice number returns HTTP 401
with `E600`, which is not an authentication problem.

### 1.1 Success (HTTP 200)
```json
{"response": {"distributor_tin": "…", "message": {"num": "…", "ysdcid": "…", "…": "…"},
              "qr_code": "https://…", "status": "SUCCESS"}}
```
Detect: top-level `response` object with `status == "SUCCESS"`.

### 1.2 Coded business error (HTTP 400, 401 or 429)
```json
{"timestamp": "2026-09-17 12:57:27", "code": "E708", "message": "Invalid total vat."}
```
- `code` is usually `E` + 3 digits, **but not always**: a bad total discount
  returned `"code": "400"` with message `"Invalid total discount___[]"`.
- Line-level errors name the failing item code in brackets:
  `"Invalid levy a amount. (ABT301)"`.
- `timestamp` is `YYYY-MM-DD HH:MM:SS` here but ISO in other shapes.

### 1.3 Validation error (HTTP 400) — undocumented
```json
{"timestamp": "2026-09-17T13:06:07.424+00:00", "status": 400,
 "errors": ["Please provide client name", "Client name must be at least equal to 2 "]}
```
Produced *before* the business rules run. Seen for:

| Input | `errors[]` |
|---|---|
| `transactionDate` in the future | `Please provide pass or present date.` |
| empty `businessPartnerName` | `Please provide client name`, `Client name must be at least equal to 2 ` |
| `unitPrice` 0 | `Unit Price must be greater than 0` |
| `quantity` 0 | `Total amount must be greater than 0`, `Quantity must be greater than 0` |

### 1.4 Problem details, RFC 7807 (HTTP 400 / 404) — undocumented
```json
{"type": "about:blank", "title": "Bad Request", "status": 400,
 "detail": "Failed to read request", "instance": "/vsdc/api/v1/taxpayer/…/invoice"}
```
- HTTP 400 `Failed to read request`: the body couldn't be deserialised — seen
  for `transactionDate` in Frappe's `YYYY-MM-DD HH:MM:SS` format.
- HTTP 404 `No static resource …`: wrong path.

### 1.5 Lookup result (HTTP 200)
```json
{"status": "SUCCESS", "data": {"tin": "C0034186913", "name": "…"}}
{"status": "NOT_FOUND", "data": null}
```
"Not found" is **HTTP 200** — check `status`.

### 1.6 Documented but never observed
```json
{"timestamp": "2023-08-25 01:20:04", "status": 901, "error": "forbidden"}      // docs: HTTP 403
{"timestamp": "2023-08-25 01:35:07", "status": 400, "error": "Invoice_NS230818-9X00001_already_signed"}
```
The live server returned shape 1.2 in both situations (`E900`, `E700`). The
parser should still accept these older shapes in case production differs.

---

## 2. Codes observed live ✅

| Code | HTTP | Message (verbatim) | When |
|---|---|---|---|
| `E600` | **401** | Something went wrong | `invoiceNumber` longer than 100 chars |
| `E700` | 400 | Invoice has already been signed | resending a signed `invoiceNumber` |
| `E704` | 400 | Transaction was not found. | callback for something GRA doesn't have (also callback with flag `PARTIAL_REFUND`) |
| `E708` | 400 | Invalid total vat. | `totalVat` more than 0.50 off |
| `E709` | 400 | Invalid total levies. | `totalLevy` more than 0.50 off |
| `E725` | 400 | Refund amount exceded invoice amount. | full `REFUND` after partial refunds |
| `E729` | 400 | Refund already cancelled. | cancelling a refund twice |
| `E750` | 400 | Reference is in use | reusing a refund `reference` |
| `E751` | 400 | Item category not found. | category not enabled for the taxpayer (`RNT`) or unknown |
| `E805` | 400 | Invalid reference | empty `reference` on a refund |
| `E806` | 400 | Invalid item category (CODE, Taxable Item) | an item code sent with a different category from its first use |
| `E818` | 400 | Invalid levy a amount. (CODE) | NHIL wrong (also: discount applied the wrong way) |
| `E820` | 400 | Invalid levy c amount. (CODE) | COVID levy missing on a pre-2026 date |
| `E821` | 400 | Invalid levy d amount. (CODE) | CST on a non-CST line |
| `E822` | 400 | Invalid levy e amount. (CODE) | tourism on a non-tourism line |
| `E827` | 400 | Differents unit price was attributed the item. (CODE) | one code, two prices, one invoice |
| `E828` | 400 | item quantity exceded. (CODE) | refunding more than remains on a line |
| `E900` | **401** | Invalid Security Key. | wrong key |
| `E990` | **429** | Too many requests. | rate limit — **happens on the shared `-001` key even at low volume** |
| `"400"` | 400 | Invalid total discount___[] | GENERAL discount with line discounts but header 0 |

### The off-by-one pattern

From E818 upwards the server's codes are **one lower** than the docs:

| Meaning | Docs | Server |
|---|---|---|
| Invalid levy A | E819 | **E818** |
| Invalid levy B | E820 | E819 (inferred) |
| Invalid levy C | E821 | **E820** |
| Invalid levy D | E822 | **E821** |
| Invalid levy E | E823 | **E822** |
| Different unit price | E828 | **E827** |
| Item quantity exceeded | E829 | **E828** |
| Invalid total discount | E818 | **`"400"`** |

**Never branch on a code number alone** for these. Branch on the code *and*
check the message; treat unknown combinations as "rejected — needs review".

---

## 3. How `gra_evat` reacts

Every outcome maps to one of these classes. The transaction states are defined
in [06 §4](06-app-design.md#4-the-transaction-state-machine).

| Class | Outcomes | Action | Next state |
|---|---|---|---|
| **SIGNED** | success envelope | store the stamp | `Signed` |
| **ALREADY_DONE** | `E700`, `E880`, `E720`, `E727` (sale/refund already signed); `E729` (cancellation already done); `E750` (reference used — maybe by our own lost attempt); `E728` | call **callback**; if it returns a stamp, verify it (see below) and store it | `Signed`, or `Rejected` if the callback can't confirm |
| **UNKNOWN** | timeout, connection reset or any network error **after the request may have been sent** | before any resend, call **callback** | callback success → `Signed`; `E704` → resend; error → stay `Unknown` |
| **TRANSIENT** | `E990` / HTTP 429; HTTP 5xx; `E600`–`E603` (unless caused by our own input); DNS or connection refused *before* sending | retry with backoff (§4) | `Retrying` |
| **CONFIG** | `E900`, `E890`, `E901`–`E908`; HTTP 403 | stop sending for that branch, alert administrators, keep queueing | `Retrying` + branch marked **Unhealthy** |
| **REJECTED** | every other `E7xx` / `E8xx`, code `"400"`, validation shape, problem+json 400, any unrecognised response | stop; show the reason; wait for a human fix and a manual retry | `Rejected` |

**Verifying a callback stamp.** After a site restore or a naming-series reset,
an invoice number can collide with an old, unrelated transaction. E700 plus a
callback would then return *someone else's* stamp. Before accepting a callback
stamp, `gra_evat` checks that `message.num` and `message.flag` match, and that
`ysdcitems` equals the number of distinct item codes we sent. On a mismatch the
transaction is `Rejected` with "invoice number collision", never silently
signed.

**Input errors are prevented, not handled.** The payload builder refuses to
send anything the server is known to reject (over-long numbers, zero prices or
quantities, future or pre-2026 dates, empty names, unsupported currencies,
mixed categories). These fail locally with a clear message and never reach GRA.

## 4. Retry policy

| Setting | Default | Notes |
|---|---|---|
| Sync attempt at payment | 1 attempt, **8 s** timeout | configurable; see [06 §5](06-app-design.md#5-flows) |
| Background timeout | 30 s | |
| Backoff | 1 min, 2 min, 5 min, 10 min, 30 min, then hourly | `E990` waits at least 60 s |
| Max automatic attempts | 20 (≈ 1 day) | then `Rejected` with "gave up after N attempts" — a manual retry resets the count |
| Rate limit | 45 requests / minute per key | shared by all workers via Redis; stays under GRA's 50 |

---

## 5. The documented table, with live annotations

Generated from the official collection. "Live behaviour" is blank where the
code was not exercised.

| HTTP (docs) | Code | Message (docs) | Solution (docs) | Live behaviour |
|---|---|---|---|---|
| 403 | — | FORBIDDEN | Ensure Company Reference in the URL is accompanied by its matching security_key in the Header | ⚠ a wrong key returns **E900 on HTTP 401** instead |
| 400 | — | BAD REQUEST | Ensure you do not have a broken URL / Endpoint | ✅ unparseable body → problem+json (HTTP 400); unknown path → problem+json (HTTP 404) |
| 400 | E600 | Something went wrong | Contact tech support team | ✅ HTTP **401**, for an `invoiceNumber` over 100 chars |
| 400 | E601 | Unable to generate internal data | Contact tech support team |  |
| 400 | E602 | Unable to generate a signature | Contact tech support team |  |
| 400 | E603 | TLS version not supported | Contact tech support team |  |
| 400 | E700 | The invoice has already been signed | Ensure that you are sending an invoice number that has not already been sent to EVAT (Rely on callback endpoint to get a copy of success response) | ✅ `Invoice has already been signed` |
| 400 | E701 | The invoice was not found | Ensure that the invoice number in question has been sent to evat and returned with a success response |  |
| 400 | E702 | Invalid data, invoices already exist | Ensure you insert an invoice number that has not been sent to EVAT |  |
| 400 | E703 | Invalid number of items for statement of account reference | Ensure all transactions tied to the group reference ID are present in the payload |  |
| 400 | E704 | The transaction was not found | Resend Invoice/Purchase transaction bearing that invoice number first | ✅ `Transaction was not found.` |
| 400 | E705 | Invalid transaction flag | Ensure you are using the accepted values for Flag (case sensitive) |  |
| 400 | E706 | Invalid transaction currency | Ensure you are using the accepted values for Currency (case sensitive) |  |
| 400 | E707 | Invalid total amount | Item Amount Value is strictly summation of Unit Price × Quantity |  |
| 400 | E708 | Invalid total VAT | Ensure you have summed up 15% of all taxable items in the payload | ✅ `Invalid total vat.` |
| 400 | E709 | Invalid total levies | Ensure you have summed up 15% of Levies A, B, C, D, E of items in the payload | ✅ `Invalid total levies.` |
| 400 | E710 | Purchase already exist | Invoice Number for the purchase transaction already exists on EVAT, use a new number |  |
| 400 | E711 | Purchase was not found | Ensure the invoice number for the purchase has already been sent to evat |  |
| 400 | E712 | The purchase is already returned | Purchase has already been returned |  |
| 400 | E713 | Purchase order not found | Ensure you have entered a valid purchase order number |  |
| 400 | E714 | Purchase order in use | The purchase order number has already been sent to evat, use a new one |  |
| 400 | E715 | Invalid purchase order reference | Ensure you entered a valid purchase order number |  |
| 400 | E716 | Purchase amount exceeded | Ensure the purchase amount in the return transaction is equal to purchase amount when it was sent as a purchase |  |
| 400 | E720 | The invoice has already been refunded | Issue a refund callback to see response |  |
| 400 | E721 | Invoice credited or debited cannot be refund | You can issue a full refund on a credited or debited invoice |  |
| 400 | E722 | Credit or debit note already exist | Credit or debit note number has already been sent to evat |  |
| 400 | E723 | Duplication of invoice number | Ensure that invoice number is not duplicated in the credit/debit note payload |  |
| 400 | E724 | Credit note amount cannot be greater than invoice amount | Ensure the credit note amount is lesser than the sum of invoice amounts in payload |  |
| 400 | E725 | Refund amount exceeded invoice amount | Ensure Refund amount is lower than invoice amount | ✅ `Refund amount exceded invoice amount.` (full REFUND after partials) |
| 400 | E726 | Invoice totally refunded | Invoice has already been refunded, you can no longer issue a partial refund |  |
| 400 | E727 | Invoice Already Refunded | Invoice has been refunded, request for a refund callback |  |
| 400 | E728 | Transaction(s) already exist | Transaction number has already been sent to EVAT, use a new number |  |
| 400 | E729 | Refund already cancelled | Request for refund callback | ✅ `Refund already cancelled.` |
| 400 | E730 | Purchase return already canceled | Request for purchase return callback |  |
| 400 | E750 | Reference is in use | Reference number has already been sent to evat, use a new one | ✅ `Reference is in use` |
| 400 | E751 | Item category not found | Ensure that item category exists in the payload | ✅ `Item category not found.` — for a category **not enabled for this taxpayer** (RNT) or an unknown one |
| 400 | E801 | Invalid calculation type | Use either INCLUSIVE or EXCLUSIVE |  |
| 400 | E802 | Invalid sale type | Use either NORMAL or EXPORT |  |
| 400 | E803 | Invalid discount type | Use either GENERAL or SELECTIVE |  |
| 400 | E804 | Invalid home currency exchange rate | Set exchange rate to 1.0 if currency is GHS |  |
| 400 | E805 | Invalid reference | Ensure the correct reference value is used | ✅ `Invalid reference` (empty reference on a refund) |
| 400 | E806 | Invalid item category | Use either "", EXM, TRSM, CST, RNT, EXC_PLASTIC | ✅ `Invalid item category (CODE, Taxable Item)` — the code was first sent with a **different** category |
| 400 | E807 | Invalid business partner name | Ensure you use the correct name as sent on day 1 or put in a request to officially change business partner name via EVAT Suite | ⚠ not enforced on staging |
| 400 | E808 | Invalid data, invoices duplication | Ensure the payload is not broken |  |
| 400 | E809 | Invalid currency | Use the approved currencies |  |
| 400 | E810 | Invalid exchange rate | Ensure exchange rate is not 0 or less |  |
| 400 | E811 | Invalid business partner | Ensure you use the correct name as sent on day 1 or put in a request to officially change business partner name via EVAT Suite | ⚠ not enforced on staging |
| 400 | E812 | Invalid item code | Ensure item code is not more than 100 characters | ⚠ not enforced on staging (101-char codes accepted) |
| 400 | E813 | Invalid item description | Ensure item description is not more than 100 characters | ⚠ not enforced on staging (101-char descriptions accepted) |
| 400 | E815 | Invalid item quantity | Ensure value is not 0 or less | ⚠ quantity 0 is caught earlier by the validation layer |
| 400 | E816 | Invalid item unit price | Ensure value is not 0 or less | ⚠ unit price 0 is caught earlier by the validation layer |
| 400 | E817 | Invalid total voucher | Ensure value is not 0 or less |  |
| 400 | E818 | Invalid total discount | Ensure value is not 0 or less | ⚠ server uses E818 for **levy A**; a bad total discount came back as code `"400"` |
| 400 | E819 | Invalid levy A amount | Ensure value is 2.5% of item amount | ⚠ server's levy A is **E818**; levy B presumably E819 (not observed) |
| 400 | E820 | Invalid levy B amount | Ensure value is 2.5% of item amount | ⚠ server's E820 is **levy C** |
| 400 | E821 | Invalid levy C amount | Ensure value is 1% of item amount (for invoices before 2025 only) | ⚠ server's E821 is **levy D** |
| 400 | E822 | Invalid levy D amount | Ensure value is 5% of item amount | ⚠ server's E822 is **levy E** |
| 400 | E823 | Invalid levy E amount | Ensure value is 1% of item amount | ⚠ levy E is **E822** on the server |
| 400 | E824 | Invalid business partner TIN | Ensure value has 11 or 13 characters | ⚠ not enforced on staging (any length accepted) |
| 400 | E825 | Mismatch currency between invoice and refund | Ensure you use the same currency for refund as used for invoice |  |
| 400 | E826 | An item cannot have multiple description | Ensure the same item code is not used for different item descriptions | ⚠ not enforced on staging (renames accepted) |
| 400 | E827 | An item cannot have multiple category | Ensure that each tax version of an item has its unique item code | ⚠ server's E827 is **different unit price** for one code |
| 400 | E828 | Different unit price was attributed to the item | Ensure multiple items in the same invoice payload does not have the same item code but different unit prices | ⚠ server's E828 is **item quantity exceeded** |
| 400 | E829 | Item quantity exceeded | Ensure the quantity is not exceeded | ⚠ quantity exceeded is **E828** on the server |
| 400 | E830 | Item code is duplicated | Ensure that the same item code is not assigned to multiple items on the same invoice | ⚠ not raised — duplicates are **silently merged** |
| 400 | E831 | Invalid consumer |  |  |
| 400 | E870 | Invalid invoice number format | Ensure invoice number doesn't have special characters such as @ or ! | ⚠ not enforced on staging (`@` `#` `/` space all accepted) |
| 400 | E871 | Invalid total amount format | Ensure the value is a decimal number |  |
| 400 | E872 | Invalid total VAT format | Ensure the value is a decimal number |  |
| 400 | E873 | Invalid total levies format | Ensure the value is a decimal number |  |
| 400 | E874 | Invalid total discount format | Ensure the value is a decimal number |  |
| 400 | E875 | Invalid total voucher format | Ensure the value is a decimal number |  |
| 400 | E876 | Invalid exchange rate format | Ensure the value is a decimal number |  |
| 400 | E877 | Invalid item code format | Ensure the value is not more than 100 characters |  |
| 400 | E878 | Invalid quantity format | Ensure the value is a decimal number |  |
| 400 | E879 | Invalid unit price format | Ensure the value is a decimal number |  |
| 400 | E880 | QR Code data already generated | Issue an invoice callback |  |
| 400 | E881 | Group reference not found | Ensure the correct group reference value is used |  |
| 400 | E890 | Invalid authority | Ensure your API credentials are correct |  |
| 400 | E891 | Invalid transaction date format | Ensure the value is a date |  |
| 400 | E892 | Invalid supplier tin | Ensure your business partner TIN has 11 or 13 characters |  |
| 400 | E900 | Invalid Security Key | Ensure your API credentials are correct | ✅ HTTP **401** `Invalid Security Key.` |
| 400 | E901 | Invalid Url | Ensure your API endpoints are correct |  |
| 400 | E902 | Unable to load the application configuration | Ensure your payload is not broken |  |
| 400 | E903 | The application is not Configured | Ensure your payload is not broken |  |
| 400 | E904 | Invalid taxpayer reference | Ensure TIN value in the endpoint URL is correct |  |
| 400 | E905 | Invalid application type | Ensure your payload is not broken |  |
| 400 | E906 | The client machine is not registered | Contact the tech team for assistance |  |
| 400 | E907 | Invalid Security Key or taxpayer reference | Ensure your API credentials are correct |  |
| 400 | E908 | Taxpayer or branch not registered | Contact the tech team for assistance |  |
| 400 | E990 | Too many requests | Ensure you are not exceeding 50 requests per minute | ✅ HTTP **429** `Too many requests.` |
