# 05 — URY integration analysis

Where URY creates, reverses or prints a paid invoice, what each path means for
GRA, and the traps found reading the code. Line numbers are as of commit
`d5d84b3` (2026-09-17) and will drift.

---

## 1. What gets signed, and what never does

| Document | Sign with GRA? | Why |
|---|---|---|
| **POS Invoice**, submitted, `is_return = 0` | **Yes → `INVOICE`** | This is the sale the customer pays for. |
| **POS Invoice**, submitted, `is_return = 1` | **Yes → `REFUND` / `PARTIAL_REFUND`** | URY's Return feature. |
| POS Invoice return, **cancelled** | **Yes → `REFUND_CANCELATION`** | URY's Undo Return. |
| POS Invoice, **draft** (`docstatus = 0`) | No | Not a sale yet. Drafts are merged, split, held, transferred and cancelled freely. |
| POS Invoice, iHotel "charged draft" (`custom_charge_to_room = 1`) | **Not in v1** | Stays a draft forever; settled through the hotel folio. Needs `statment_of_account` (Phase 5). |
| **Sales Invoice with `is_consolidated = 1`** | **Never** | Created at shift close from POS Invoices that were already signed. Signing it would double-count. |
| Sales Invoice, not consolidated (desk sales) | Later (Phase 5) | Not a URY flow. |
| POS Closing Entry, Payment Entry, Journal Entry | No | Not sales documents. |

## 2. Every path that creates or reverses a paid invoice

| Path | Where | Mechanism | Fires `on_submit` / `on_cancel`? | GRA action |
|---|---|---|---|---|
| **Pay a bill** (single payer, split-by-value, on-account) | `make_invoice` — [ury_order.py:1316](../../ury/ury/doctype/ury_order/ury_order.py#L1316), submit at L1429 | `invoice.submit()` | ✅ `on_submit` | `INVOICE` |
| **Split by item** | `split_invoice_by_item` — [ury_order.py:1510](../../ury/ury/doctype/ury_order/ury_order.py#L1510) | N × `new_inv.submit()` (L1756); the source **draft** is cancelled by raw SQL (L1791) | ✅ per new bill | one `INVOICE` per bill. The source was never signed, so nothing to reverse. |
| **Return** (full or partial) | `create_pos_return` — [api.py:6597](../../ury/ury_pos/api.py#L6597), submit at L6746 | ERPNext `make_return_doc` + `submit()` | ✅ `on_submit`, `is_return = 1` | `REFUND` or `PARTIAL_REFUND` |
| **Undo Return** | `reverse_pos_return` — [api.py:6970](../../ury/ury_pos/api.py#L6970), cancel at L7011 | `doc.cancel()` | ✅ `on_cancel`, `is_return = 1` | `REFUND_CANCELATION` |
| **Cancel order** | `cancel_order` — [ury_order.py:866](../../ury/ury/doctype/ury_order/ury_order.py#L866) | **raw `frappe.db.set_value(..., "docstatus", 2)`** at L930 | ❌ **no hooks fire** | none for drafts — but see §3.1 |
| Desk: cancel a POS Invoice | ERPNext form | `doc.cancel()` | ✅ `before_cancel` / `on_cancel` | must not silently cancel a signed sale — see §3.2 |
| Desk: ERPNext's own Point of Sale page | ERPNext | `submit()` | ✅ | `INVOICE` (covered by the generic hook) |
| Shift close / consolidation | `submit_pos_closing_entry` — [api.py:2333](../../ury/ury_pos/api.py#L2333) | ERPNext merge log → consolidated Sales Invoice | Sales Invoice hooks | **none** — excluded by `is_consolidated` |
| Change payment method on a paid bill | `change_invoice_payment_mode` — [api.py:9704](../../ury/ury_pos/api.py#L9704) | `db.set_value` on payment rows | ❌ | none — payments aren't in the payload |
| Change waiter / cashier | `update_invoice_attribution` — [api.py:9859](../../ury/ury_pos/api.py#L9859) | `db.set_value` | ❌ | none — a signed invoice can't be amended |
| Charge to room | `charge_invoice_to_room` — [api.py:7955](../../ury/ury_pos/api.py#L7955) | stays a draft | ❌ | none in v1 |
| Merge / hold / transfer | various | drafts only | — | none |

**Good news:** every path that creates or reverses a *signed* document goes
through Frappe's normal `submit()` / `cancel()`. So `gra_evat` can hang off
**generic `POS Invoice` doc events** and needs no hooks inside URY's
functions.

## 3. Landmines

### 3.1 `cancel_order` can cancel a paid invoice, silently ⚠ must fix before go-live

`cancel_order` ([ury_order.py:866](../../ury/ury/doctype/ury_order/ury_order.py#L866))
sets `docstatus = 2` by raw SQL and **never checks the current docstatus**. The
only role check is "captain or above".

- **In the UI today it isn't reachable for paid bills.** The Cancel button
  ([Orders.tsx:1080](../../pos/src/pages/Orders.tsx#L1080)) is shown when
  `selectedOrder.status` is `Draft`, `Unbilled` or `Recently Paid`. But the
  backend returns the invoice's own status, which for a paid bill is `Paid`,
  never `Recently Paid` — so the button doesn't show. The code clearly
  *intends* it to.
- **The endpoint is whitelisted**, so any captain can call it directly for a
  paid invoice.
- **Consequence with E-VAT:** GRA holds a signed sale that URY considers
  cancelled — a permanent mismatch. (Even without E-VAT this silently drops the
  sale from consolidation and the drawer count.)

**Proposed fix (URY change, decision D3):** `cancel_order` refuses any invoice
whose `docstatus != 0`, with the message "This bill is paid. Use Return to
reverse it." The Orders button condition should drop `Recently Paid`.

### 3.2 Cancelling a signed invoice from the desk
GRA has no "cancel sale". **Proposed (decision D3):** a `before_cancel` hook
refuses to cancel a signed or in-flight sale and points to Return, so URY and
GRA always hold matching documents. An unsigned sale (queued, never sent) may
be cancelled; its transaction is voided and never sent.

### 3.3 One dish, two notes = two lines with one item code
URY's cart keys lines by `uniqueId`, **including the item comment**, so the
same dish with two special instructions is two lines sharing an `item_code`.
GRA silently merges same-code, same-price lines (the receipt's line count then
disagrees with URY's), and **rejects** same-code, different-price lines
(E827). The payload builder must aggregate lines itself (see
[06 §6](06-app-design.md#6-payload-builder)).

### 3.4 GRA remembers each item code's category forever
If an admin changes an item from standard to exempt, every later invoice with
that code fails (E806). The builder embeds non-standard categories in the code
it sends (see [06 §6](06-app-design.md#6-payload-builder)).

### 3.5 The invoice number comes from a free-text prefix
POS Invoice names come from `URY Restaurant.invoice_series_prefix` (free text,
[ury_order.py:72](../../ury/ury/doctype/ury_order/ury_order.py#L72);
[ury_pos_invoice.py:154](../../ury/ury/hooks/ury_pos_invoice.py#L154)).
GRA caps `invoiceNumber` at 100 characters and the docs forbid some
characters. The builder validates. A naming-series reset (e.g. a restored or
cloned site) would re-issue old numbers — GRA answers E700 and a callback
would return **the old sale's stamp**. `gra_evat` verifies callback stamps and
supports an optional per-branch prefix (see [03 §3](03-errors-and-responses.md#3-how-gra_evat-reacts)).

### 3.6 Dates
- `preserve_original_order_date` ([ury_order.py:260](../../ury/ury/doctype/ury_order/ury_order.py#L260))
  back-dates a carried-over bill to the day it was rung. GRA accepts past dates ✅,
  so `transactionDate = posting_date` works.
- Frappe's `YYYY-MM-DD HH:MM:SS` format is **rejected** by GRA; send
  `YYYY-MM-DD` (or ISO-8601 with `T…Z`). Ghana is UTC+0.
- A bill dated before 2026-01-01 needs the old tax regime → refused locally.

### 3.7 Table orders are printed before they're paid
`validate_invoice_print` ([ury_pos_invoice.py:134](../../ury/ury/hooks/ury_pos_invoice.py#L134))
blocks payment of a table order until the bill has been printed. That first
print is necessarily **unsigned**. The fiscal receipt is the print made
**after** payment. The receipt template must make the difference obvious (see
[06 §8](06-app-design.md#8-printing)).

### 3.8 The admin skips the post-payment print
[PaymentDialog.tsx:626](../../pos/src/components/PaymentDialog.tsx#L626)
skips the auto-print for Administrator / System Manager (a testing
convenience). With E-VAT that means admins never get a fiscal receipt unless
they reprint. Fine for testing; worth knowing.

### 3.9 URY has no TIN field — ERPNext already does
No app in this bench has a TIN field. ERPNext's **`Customer.tax_id`** (Data)
exists and is the natural place. No custom field is needed.

### 3.10 The tax setup — checked 2026-09-18, and it is correct ✅
Checked on `local.16.land` (which **does** have URY installed — an earlier note
here said otherwise because `site_config.json`'s app list was stale; `bench
list-apps` reads the database).

`Ghana Tax - LR` is exactly the 2026 GRA method:

| Row | Account | Charge type | Rate | Incl. |
|---|---|---|---|---|
| 1 | NHI Levy | On Net Total | 2.5 | ✓ |
| 2 | GETF Levy | On Net Total | 2.5 | ✓ |
| 3 | **Tourism Levy** | On Net Total | 1.0 | ✓ |
| 4 | VAT Payable | On Net Total | 15.0 | ✓ |

All *On Net Total*, all tax-inclusive — no cumulative row, so no E708. Two
consequences:

- **The tourism levy applies** (answers decision D6), so every item goes to GRA
  with `itemCategory = "TRSM"` and a gross factor of **1.21**, not 1.20. See
  [02 §3](02-tax-calculation.md#3-the-2026-formula).
- ⚠ **The `Sitout` POS Profile has no tax template at all** (`taxes_and_charges`
  is empty) while `Airport` has one. Sales rung on Sitout are untaxed, so they
  would be sent to GRA with zero VAT and zero levies. This needs fixing before
  go-live regardless of E-VAT.

URY sets the template from the POS Profile (`_apply_pos_profile_taxes`,
[ury_order.py:225](../../ury/ury/doctype/ury_order/ury_order.py#L225)); it
never sets `included_in_print_rate` itself.

### 3.11 URY's own dual-source custom-field trap
URY ships custom fields twice (fixtures + `setup.py`) and has been bitten when
they drift (see the URY CLAUDE.md). `gra_evat` avoids this by creating its
custom fields from **one** programmatic source on install and on every migrate.

## 4. Field mapping — POS Invoice → GRA payload

| GRA field | Source (ERPNext v16 / URY) | Notes |
|---|---|---|
| `invoiceNumber` | `POS Invoice.name` (+ optional branch prefix) | For refunds: the **original** sale's GRA number (`return_against` → its transaction). |
| `reference` | `""` for sales; for refunds the **return** invoice's GRA number | Must be unique and non-empty for refunds. |
| `flag` | derived | see §5 |
| `transactionDate` | `posting_date` → `YYYY-MM-DD` | Cancellations: now, ISO-8601 |
| `currency` | `currency` | Must be one of the 16 supported. |
| `exchangeRate` | `conversion_rate` | 1.0 for GHS |
| `calculationType` | `INCLUSIVE` if every tax row has `included_in_print_rate = 1`; `EXCLUSIVE` if none | Mixed → refused |
| `userName` | cashier's full name (`cashier` → User full name, else owner's) | ≤ 100 chars |
| `businessPartnerName` | `customer_name`; walk-in customer → configured B2C name | ≥ 2, ≤ 100 chars |
| `businessPartnerTin` | `Customer.tax_id`; empty → configured B2C TIN (`C0000000000`) | Validate 11/13 chars or Ghana-card format for B2B |
| `saleType` | `NORMAL` | `EXPORT` not in scope |
| `discountType` | `GENERAL` | ERPNext taxes the discounted amount |
| `discountAmount` | Σ line discounts | |
| `totalAmount` | Σ unitPrice × quantity over the sent lines | |
| `totalVat` | the invoice's **VAT tax row** total | URY's booked figure |
| `totalLevy` | Σ of the **NHIL, GETFund, CST, tourism** tax row totals | URY's booked figures |
| `totalExciseAmount` | excise tax row total | 0 for restaurants |
| `voucherAmount`, `groupReferenceId`, `purchaseOrderReference` | `0`, `""`, `""` | |
| `items[].itemCode` | `item_code` (see [06 §6](06-app-design.md#6-payload-builder) for category suffix and length) | |
| `items[].description` | `item_name`, trimmed to 100 | |
| `items[].itemCategory` | `Item.gra_evat_category` (new field) | default standard |
| `items[].quantity` | Σ `qty` of the aggregated lines (absolute value on returns) | |
| `items[].unitPrice` | the line's rate on the calculation basis (see 06 §6) | > 0 |
| `items[].discountAmount` | the line's share of the discount, same basis as `unitPrice` | from `distributed_discount_amount` / `discount_amount` |
| `items[].levyAmountA…E`, `exciseAmount` | Σ from `POS Invoice.item_wise_tax_details` (child table *Item Wise Tax Detail*: `item_row`, `tax_row`, `rate`, `amount`, `taxable_amount`) | exact per-line figures ERPNext booked |

> ERPNext v16 stores per-line tax in the **`item_wise_tax_details` child
> table** (verified in this bench). v15 used a JSON field on each tax row
> instead. `gra_evat` targets v16; v15 support would need a small adapter.

Which tax row is NHIL, GETFund, VAT, etc. is **configured**, not guessed: a
mapping of *tax account → GRA bucket* in the settings ([06 §3](06-app-design.md#3-doctypes)).
An invoice with an unmapped tax row is refused locally.

## 5. Choosing the flag for a return

| Situation | Flag |
|---|---|
| The return reverses **every line in full** and **no other refund** exists for the sale | `REFUND` |
| Anything else (some lines, part quantities, or a later return after an earlier one) | `PARTIAL_REFUND` |

The refund lines must use the **same item codes and unit prices** as the
signed sale. The builder derives them from the original's transaction payload,
matched through the return rows' `pos_invoice_item` link — never from the
current item master.

A return can only be sent once its original sale is **signed**. If the sale is
still queued, the refund waits for it.

## 6. Frontend touch points (URY glue, Phase 3)

| Where | Change |
|---|---|
| [PaymentDialog.tsx](../../pos/src/components/PaymentDialog.tsx) — after `make_invoice` (L568), before printing (L613 / L643) | call "sign now" with a spinner, then print; if still pending, print a provisional receipt and warn |
| [ItemSplitFlow.tsx](../../pos/src/components/ItemSplitFlow.tsx) — L305 → L317 | same, per bill |
| [ReturnDialog.tsx](../../pos/src/components/ReturnDialog.tsx) — L169 | sign the refund; print a refund slip (decision D4) |
| [Orders.tsx](../../pos/src/pages/Orders.tsx) — Undo Return (L273), Cancel button (L1080), order cards | sign the cancellation; E-VAT status badge; retry / reprint for managers; drop `Recently Paid` from the Cancel condition |
| [print.ts](../../pos/src/lib/print.ts) — `printOrder` (L62), `printSplitReceipts` (L145) | no change — the receipt block lives in the print format |
| `getPosProfile` ([api.py:1643](../../ury/ury_pos/api.py#L1643)) | return `evat_enabled` so the POS knows whether to call `gra_evat` |
| Customer quick-create (CustomerSelect) | optional TIN input → `Customer.tax_id` |
| POS Closing dialog | show the number of unsigned invoices in the shift (warn, don't block — decision D12) |
| Settings page | an E-VAT health section (optional) |
