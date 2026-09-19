# 04 — Sandbox verification log

Everything claimed as "verified" in this pack was exercised against GRA's live
staging VSDC. About **140 calls** were made in two sessions.

- **Session 1 — 2026-09-07**, key `CXX000000YY-001`: 14 calls. Not machine-logged
  (the scratch area was wiped); results are transcribed below.
- **Session 2 — 2026-09-17**, mostly key `CXX000000YY-006`: 127 calls. Every
  `POST` is in [reference/sandbox-probes-2026-09-17.jsonl](reference/sandbox-probes-2026-09-17.jsonl)
  (115 lines: label, path, full request, HTTP status, duration, full response).

Receipt numbers are quoted where they matter, so a result can be checked with a
callback later.

---

## Session 1 — 2026-09-07

| # | Test | Result |
|---|---|---|
| 1 | `GET /health`, correct key | `{"status":"UP"}`, 0.79 s |
| 2 | `GET /health`, wrong key | **HTTP 401** `E900 Invalid Security Key.` (docs: 403 `forbidden`) |
| 3 | Exclusive 45 × 100, levies 112.50 + 112.50, VAT 675 (2026 method) | ✅ signed `1001-632B-NS56`, 1.99 s |
| 4 | Same base, VAT 708.75 (pre-2026 cumulative method) | ❌ `E708 Invalid total vat.` |
| 5 | Levy A 200 instead of 112.50 | ❌ **`E818`** `Invalid levy a amount. (ABT301)` (docs: E819) |
| 6 | Inclusive 1 × 120, levies 2.50 + 2.50, VAT 15.00 | ✅ signed `1001-632B-NS58` |
| 7 | Resend #6 unchanged | ❌ `E700 Invoice has already been signed` |
| 8 | `POST /invoice/callback` for #6 | ✅ **byte-identical stamp** to #6 (same receipt number, signature, internal data, QR), 0.84 s |
| 9 | Same item code on two lines, same price | ✅ signed — but `ysdcitems: "1"`: **silently merged** (docs imply E830) |
| 10 | Two different item codes, same totals | ✅ signed, `ysdcitems: "2"` |
| 11 | Invoice → | ✅ `…NS62` |
| 12 | → full `REFUND` with reference | ✅ `…NR2` (refund prefix `NR`) |
| 13 | → `REFUND_CANCELATION` via `/cancellation` | ✅ `…CR2` (prefix `CR`) |
| 14 | → cancel the same refund again | ❌ `E729 Refund already cancelled.` |

Latency for signed invoices: 1.3–2.4 s.

---

## Session 2 — 2026-09-17

Labels (R1, D1, …) match the `label` field in the JSONL log.

### Keys and rate limiting
| Test | Result |
|---|---|
| 9 calls on the default key `-001` | **8 × `E990` on HTTP 429** from the very first call. The key is published in GRA's docs and shared by every integrator. |
| `/health` on keys `-006`, `-007`, `-008` | all `UP` |
| K1: invoice on `-006` | ✅ `1006-6335-NS4` — receipt numbers encode the branch |
| Flat-rate taxpayer `CXX0000XXXY-001` `/health` | `UP` (no flat-rate requests are documented) |

### Rounding and tolerance — three lines at 7.00 incl. (true levy 0.875, VAT 2.625)
| Test | Sent | Result |
|---|---|---|
| R1 | totals = sum of rounded lines (0.90 / 2.64) | ✅ |
| R2 | totals = rounded exact sum (0.88 / 2.63) | ✅ |
| R3 / R4 | VAT +0.02 / +0.10 | ✅ both |
| R5 | full precision (0.875 / 2.625) | ✅ |
| R6 | line levies truncated to 0.14 | ✅ |
| T-vat | VAT +0.5, +1, +2, +5 | ❌ `E708` |
| T-levy | levy +0.5, +1, +2 | ❌ `E709` |
| T-lineA | line NHIL 0.20 / 0.30 / 0.50 (true 0.146) | ✅ / ✅ / ❌ `E709` (the total moved > 0.5) |
| S | VAT = true +0.45, +0.49, −0.45 | ✅ all |
| L | 12,000 invoice: exact / VAT +0.45 / +0.60 / +5 | ✅ / ✅ / ❌ E708 / ❌ E708 |

**Conclusion: ±0.50 absolute on totals, independent of invoice size.**

### Dates
| Test | Result |
|---|---|
| D1 `2026-08-01` (past) | ✅ |
| D2 `2026-12-31` (future) | ❌ validation shape: `Please provide pass or present date.` |
| D3 `2025-06-01`, no COVID levy | ❌ `E820 Invalid levy c amount.` — **the date selects the regime** |
| D4 `2026-09-17T10:00:00Z` | ✅ |
| D5 `2026-09-17 10:00:00` (Frappe format) | ❌ problem+json `Failed to read request` |

### Discounts — GHS 1,000 base (see [02 §5](02-tax-calculation.md#5-discounts))
| Test | Type | Header / line discount | Tax on | Result |
|---|---|---|---|---|
| EG1 | GENERAL | 100 / 100 | discounted | ✅ |
| EG2 | GENERAL | 100 / 100 | undiscounted | ❌ E818 |
| EG3 | GENERAL | 100 / 0 | discounted | ❌ E818 |
| EG4 | GENERAL | 0 / 100 | discounted | ❌ code `"400"` `Invalid total discount___[]` |
| ES1 | SELECTIVE | 100 / 0 | discounted | ❌ E818 |
| ES2 | SELECTIVE | 100 / 0 | undiscounted | ✅ |
| ES3 | SELECTIVE | 100 / 100 | discounted | ❌ E818 |
| IG1 | GENERAL, inclusive 1,200 | 120 / 120 | discounted | ✅ |
| IG2 | GENERAL, inclusive | 120 / 120 | undiscounted | ❌ E818 |
| IS1 | SELECTIVE, inclusive | 120 / 0 | discounted | ❌ E818 |
| IS2 | SELECTIVE, inclusive | 120 / 0 | undiscounted | ✅ |

### Categories — exclusive 1 × 100
| Test | Result |
|---|---|
| C1 `EXM`, all zeros | ✅ |
| C2 `CST`, workbook method | ✅ |
| C3 `TRSM`, workbook method | ✅ |
| C4 `EXC_PLASTIC`, excise separate from levy | ✅ |
| C5 `TRSM`, tourism inside the VAT base | ✅ (within the ±0.50 tolerance, so it doesn't disprove C3; the workbook is authoritative) |
| C6 / C7 `RNT` | ❌ `E751 Item category not found.` — not enabled for this taxpayer |
| C8 `BOGUS` | ❌ `E751` (docs would suggest E806) |
| CT1 / CT2 `CST` line carrying tourism | ❌ `E822 Invalid levy e amount.` |
| CT3 `TRSM` line carrying CST | ❌ `E821 Invalid levy d amount.` |

### Refund sequence — invoice `P260917130349-RF` (A × 4, B × 4 at 120 incl.)
| Step | Test | Result |
|---|---|---|
| F0 | invoice | ✅ `1006-6335-NS29`, `ysdcitems` 2 |
| F1 | `PARTIAL_REFUND` A × 1, ref PR1 | ✅ `…NR2`, returned flag **`REFUND`** |
| F2 | `PARTIAL_REFUND` A × 1.5 (fractional), ref PR2 | ✅ `…NR3` |
| F3 | reuse ref PR1 | ❌ `E750 Reference is in use` |
| F4 | A × 2 when 1.5 remains | ❌ `E828 item quantity exceded. (RFA)` |
| F5 | empty reference | ❌ `E805 Invalid reference` |
| F6 | callback PR1 with flag `PARTIAL_REFUND` | ❌ `E704` |
| F7 | `REFUND_CANCELATION` of PR2 | ✅ `…CR2` |
| F8 | A × 2 again (PR2's 1.5 restored) | ✅ `…NR4` |
| F9 | full `REFUND` of the original amounts | ❌ `E725 Refund amount exceded invoice amount.` |
| CB1 | callback PR1 with flag `REFUND` | ✅ `…NR2` |
| CB2 | callback PR2 with flag `REFUND_CANCELATION` | ✅ `…CR2` |
| CB3 | callback the sale with flag `INVOICE` | ✅ `…NS29` |
| CB4 | callback an unknown number | ❌ `E704` |

### Full-refund variants
| Test | Result |
|---|---|
| G1 → G2: full `REFUND` with **empty** reference (as in the docs' own sample) | ❌ `E805` |
| G3 → G4: `REFUND` flag for only half the quantity | ✅ (not enforced) |
| G5 → G6: full `REFUND` with reference | ✅ `…NR6` |
| G7: callback of G6 with flag `REFUND` | ✅ same stamp |
| G8: `REFUND_CANCELATION` with a wrong `totalAmount` (999) | ✅ accepted — not validated |

### Invoice numbers
| Test | Result |
|---|---|
| N1–N6: `/`, `_`, `.`, space, `#`, `@` | ✅ all (docs E870 would reject `@`) |
| N7: 60 chars | ✅ |
| X3: exactly 100 chars | ✅ |
| N8 / X4: 110 / 101 chars | ❌ `E600 Something went wrong` on **HTTP 401**; a receipt number was skipped |
| X1 / X2: callback N8 (full and truncated) | ❌ `E704` — the failed call left no transaction |

### Partner name and TIN
| Test | Result |
|---|---|
| T1–T6: TIN empty, 10, 12, 13 chars, Ghana-card format, lowercase | ✅ all (docs E824 would reject most) |
| P1: empty name | ❌ validation shape: name required, min 2 chars |
| P2: different name for `C0000000000` | ✅ |
| P3: real-looking TIN with an unrelated name | ✅ (docs E807/E811 not enforced on staging) |

### Item master drift — code `RFA`, first sent as "Refund A", standard, 120
| Test | Result |
|---|---|
| M1: renamed description | ✅ (docs E826 not enforced) |
| M2: category changed to `EXM` | ❌ **`E806 Invalid item category (RFA, Taxable Item)`** |
| M3: price changed to 150 | ✅ |
| M4: code twice on one invoice at 120 and 60 | ❌ `E827 Differents unit price was attributed the item.` |

### Zero and edge lines
| Test | Result |
|---|---|
| Z1: `unitPrice` 0 (complimentary) | ❌ validation shape: `Unit Price must be greater than 0` |
| Z2: `quantity` 0 | ❌ validation shape: quantity and total must be > 0 |
| Z3: 100 % line discount (GENERAL) | ✅ |
| IC: `itemCode` of 50, 51, 100, 101 chars | ✅ all (docs say 50 / 100) |
| ID: `description` of 100, 101 chars | ✅ both |

### Lookups (`GET`)
| Test | Result |
|---|---|
| `/identification/tin/C0034186913` | ✅ `SUCCESS`, `{tin, name}` only |
| `/identification/tin/P0000000000`, `/identification/tin/X` | HTTP 200 `NOT_FOUND` |
| `/identification/tin/C0000000000` (B2C placeholder) | **no response within 20 s** |
| `/identification/tin?tin=…`, `/identification/{tin}` | HTTP 404 problem+json |
| `/identification/nationalId/GHA-000XXXXXX-2` and `GHA-000000000-0` | HTTP 200 `NOT_FOUND` |

### Latency (session 2, 59 signed calls)
min 0.48 s · **median 3.18 s** · max 5.61 s. Refunds, cancellations and
callbacks were consistently under 1.6 s.

---

## Not verified

Treat these as unknown until tested:

- Purchases, purchase returns and their cancellation; credit/debit notes;
  statement of account; inventory; XML format.
- `saleType: EXPORT`, `voucherAmount`, non-GHS currencies, `taxType`.
- Levy B's error code (inferred E819).
- `RNT` tax rules (not enabled on the test taxpayer).
- **Production strictness.** Staging ignores several documented rules (TIN
  length, partner-name consistency, renames, invoice-number characters, field
  lengths). Production may enforce them, so `gra_evat` validates to the
  documented, stricter rules anyway.
- On-prem VSDC behaviour and latency.
- The exact rate-limit window.
- Whether the GRA logo is required on printed receipts (both samples show it).

## Re-running

```bash
cd docs/gra-evat/reference
EVAT_REF=CXX000000YY-006 EVAT_PROBE_LOG=/tmp/probes.jsonl python3 - <<'PY'
from sandbox_probe import *
call("health-ish invoice", "invoice",
     inv(f"P{RUN}-X", [item("X1", "Test", 1, 120, 2.5, 2.5)], 120, 15, 5), expect="OK")
PY
```

Invoice numbers are permanent at GRA — always include `RUN` (a timestamp) so
numbers never repeat. Keep to ~40 calls a minute.
