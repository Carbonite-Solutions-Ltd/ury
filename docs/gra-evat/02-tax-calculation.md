# 02 — Tax calculation

The whole integration rests on this page: **URY must compute tax exactly the
way GRA does**, otherwise the two sides can never agree.

Sources: GRA's workbook ([reference/tax-calculation-template.xlsx](reference/tax-calculation-template.xlsx),
flattened in [.txt](reference/tax-calculation-template.txt)), the two 2026
sample receipts ([POS](reference/sample-receipt-pos.png), [A4](reference/sample-receipt-a4.png)),
and live sandbox tests ([04](04-sandbox-verification.md)).

---

## 1. Rates

| Tax / levy | Rate | API field | In `totalLevy`? | Applies to |
|---|---|---|---|---|
| NHIL (National Health Insurance Levy) | 2.5 % | `levyAmountA` | yes | every taxable line |
| GETFund levy | 2.5 % | `levyAmountB` | yes | every taxable line |
| COVID-19 levy | 1 % | `levyAmountC` | yes | **only transaction dates before 2026-01-01** |
| CST (Communications Service Tax) | 5 % | `levyAmountD` | yes | category `CST` |
| Tourism levy | 1 % | `levyAmountE` | yes | category `TRSM` |
| Excise (plastics) | 5 % | `exciseAmount` | **no** — `totalExciseAmount` | category `EXC_PLASTIC` |
| VAT | 15 % | (line VAT is not sent) | no — `totalVat` | every taxable line |

## 2. Two tax regimes

The regime is chosen by **`transactionDate`** ✅.

| | From 2026-01-01 (current) | Before 2026-01-01 (old) |
|---|---|---|
| COVID levy | none | 1 % |
| VAT base | **the net amount** | net + NHIL + GETFund + COVID (cumulative) |
| Standard effective rate | **20 %** | 21.9 % |
| Proof | A4 + POS 2026 receipts; sandbox accepts it, rejects the old VAT with E708 | the docs' 2023 full-refund sample reproduces exactly; a 2025-dated invoice without COVID levy → E820 |

**`gra_evat` v1 supports the 2026 regime only.** Transactions dated before
2026-01-01 are refused before sending (historic backlogs are out of scope).

Old-regime check, for the record (docs sample, inclusive 1,300.00):
base = 1300 / 1.219 = 1066.45 → NHIL 26.66, GETFund 26.66, COVID 10.66
(`totalLevy` 63.99), VAT = 1066.45 × 1.06 × 15 % = 169.57. Matches the sample
exactly.

## 3. The 2026 formula

Let **L** be a line's net taxable value (after any GENERAL discount, excluding
all taxes). Per category:

| Category | Pre-VAT add-on | Taxable base **B** | NHIL | GETFund | Tourism | VAT | Gross = L × |
|---|---|---|---|---|---|---|---|
| `""` standard | — | L | B × 2.5 % | B × 2.5 % | — | B × 15 % | **1.20** |
| `TRSM` | — | L | B × 2.5 % | B × 2.5 % | **L × 1 %** | B × 15 % | **1.21** |
| `CST` | CST = L × 5 % | **L × 1.05** | B × 2.5 % | B × 2.5 % | — | B × 15 % | **1.26** |
| `EXC_PLASTIC` | Excise = L × 5 % | **L × 1.05** | B × 2.5 % | B × 2.5 % | — | B × 15 % | **1.26** |
| `EXM` | — | 0 | 0 | 0 | — | 0 | 1.00 |
| `RNT` | not verified — not enabled on the test taxpayer (E751). Receipt label "VAT(RENT 5% STD 15%)" suggests 5 % VAT on rent. Out of scope. | | | | | | |

Key points, all verified:
- VAT is **not** charged on the levies.
- **Tourism does not enter the VAT base** (VAT on a tourism line is L × 15 %,
  not (L + tourism) × 15 %).
- **CST and excise do enter the base**: NHIL, GETFund and VAT are computed on
  L + CST (or L + excise).
- **CST is part of `totalLevy`; excise is not** (it goes to `totalExciseAmount`).
- A line has **one** category, so CST and tourism cannot be combined on a line.
  (The workbook has a "CST & Tourism" column; the API rejects it — E821/E822.)

### Getting L from the prices

| `calculationType` | L = |
|---|---|
| `EXCLUSIVE` | unitPrice × quantity − lineDiscount |
| `INCLUSIVE` | (unitPrice × quantity − lineDiscount) ÷ gross factor (1.20 / 1.21 / 1.26 / 1.00) |

### Header totals

| Field | Value |
|---|---|
| `totalAmount` | Σ unitPrice × quantity — **before discount, whatever the calculation type** |
| `discountAmount` | Σ line discounts (GENERAL) |
| `totalLevy` | Σ (NHIL + GETFund + CST + tourism) |
| `totalVat` | Σ VAT |
| `totalExciseAmount` | Σ excise |
| amount payable (not sent) | EXCLUSIVE: totalAmount − discount + totalLevy + totalVat + totalExcise · INCLUSIVE: totalAmount − discount |

## 4. Worked examples

### 4.1 GRA workbook — exclusive (unit price 100 unless noted)

| Scenario | L | Add-on | NHIL | GETFund | Tourism | VAT | totalLevy | Payable |
|---|---|---|---|---|---|---|---|---|
| Standard, 45 × 100 | 4,500 | — | 112.50 | 112.50 | — | 675.00 | 225.00 | 5,400.00 |
| CST | 100 | CST 5.00 | 2.625 | 2.625 | — | 15.75 | 10.25 | 126.00 |
| Tourism | 100 | — | 2.50 | 2.50 | 1.00 | 15.00 | 6.00 | 121.00 |
| Excise (plastic) | 100 | excise 5.00 | 2.625 | 2.625 | — | 15.75 | 5.25 (+ excise 5.00) | 126.00 |

### 4.2 GRA workbook — inclusive (gross 100 unless noted)

| Scenario | L | Add-on | NHIL | GETFund | Tourism | VAT | totalLevy |
|---|---|---|---|---|---|---|---|
| Standard | 83.3333 | — | 2.0833 | 2.0833 | — | 12.5000 | 4.1667 |
| CST | 79.3651 | CST 3.9683 | 2.0833 | 2.0833 | — | 12.5000 | 8.1349 |
| Tourism | 82.6446 | — | 2.0661 | 2.0661 | 0.8264 | 12.3967 | 4.9587 |
| Excise, 32 × 540 = 17,280 | 13,714.29 | excise 685.71 | 360.00 | 360.00 | — | 2,160.00 | 720.00 |

> Workbook quirk: its "CST & Tourism" column reports a total levy of 4.9587,
> which leaves out the CST even though the CST-only column includes it. That
> combination can't be sent anyway (§3), so it doesn't matter.

### 4.3 GRA's 2026 sample receipts

| Receipt | Lines | Excl. taxes | NHIL | GETFund | VAT | Total taxes | Invoice total |
|---|---|---|---|---|---|---|---|
| POS (inclusive) | 5 × 25.00 | 104.17 | 2.60 | 2.60 | 15.63 | 20.83 | **125.00** |
| A4 | 12 × 300 + 95 × 40 = 7,400 | 7,400.00 | 185.00 | 185.00 | 1,110.00 | 1,480.00 | **8,880.00** |

### 4.4 Verified live

| Test | Sent | Result |
|---|---|---|
| Exclusive 45 × 100, VAT 675 | 2026 method | ✅ signed |
| Same, VAT 708.75 | old cumulative method | ❌ E708 |
| Inclusive 1 × 120, levies 2.50 + 2.50, VAT 15.00 | 2026 method | ✅ signed |
| CST, tourism and excise lines as in §4.1 | workbook method | ✅ signed |
| `EXM` line with all zeros | | ✅ signed |

## 5. Discounts

Verified with a GHS 1,000 base so the differences exceed the ±0.50 tolerance.

| `discountType` | Put the discount on… | Tax is charged on… | Verified |
|---|---|---|---|
| **`GENERAL`** | each line's `discountAmount`; header `discountAmount` = their sum | the **discounted** amount | ✅ exclusive and inclusive |
| **`SELECTIVE`** | the header only; line discounts must be 0 | the **undiscounted** amount | ✅ exclusive and inclusive |

Rejections observed: GENERAL with tax on the undiscounted amount (E818);
GENERAL with a header discount but no line discounts (E818); GENERAL with line
discounts but header 0 (`"Invalid total discount"`); SELECTIVE with tax on the
discounted amount (E818); SELECTIVE with line discounts (E818).

The docs describe SELECTIVE as "discount on total amount, taxable" and GENERAL
as "discount per line, tax exempt". Read "taxable" as *the discount does not
reduce tax* and "tax exempt" as *the discounted part is not taxed*.

**For URY:** ERPNext charges tax on the discounted amount, so URY maps to
**GENERAL**, with the invoice-level discount spread over the lines.

Line `discountAmount` is on the **same basis as `unitPrice`**. For inclusive
pricing it is a *gross* amount: a 1,200 line with a 120 discount is taxed on
(1,200 − 120) ÷ 1.20 = 900 ✅.

A **100 % line discount** is accepted ✅, which is how complimentary items can
be sent (`unitPrice` must be > 0).

## 6. Rounding and the validator's tolerance

- GRA recomputes the tax from the lines and accepts `totalVat` and `totalLevy`
  that are within **±0.50** of its own result ✅, whatever the invoice size
  (tested on 21.00 and 12,000.00). Beyond that: E708 / E709.
- Per-line levies are checked just as loosely (a line NHIL of 0.30 against a
  true 0.146 was accepted).
- Full-precision and 2-decimal values are both accepted.

**Consequence:** GRA accepting an invoice does **not** prove URY and GRA agree
to the cent. On a GHS 21 bill, a VAT of 3.115 against a true 2.625 was
accepted. So:

1. `gra_evat` sends **URY's own booked figures** (2 decimals), never a
   separately recomputed number. That makes GRA's record equal URY's by
   construction.
2. It also runs its **own calculator** (§8) and compares. A difference above a
   small threshold (proposed 0.05) means the ERPNext tax setup is wrong; the
   transaction is held with a clear message instead of being sent.
3. The ledger stores both, so reconciliation is exact.

## 7. What the ERPNext tax setup must look like

| Row | Account (example) | Charge type | Rate | Included in print rate |
|---|---|---|---|---|
| 1 | NHIL payable | **On Net Total** | 2.5 | ✓ for inclusive menus |
| 2 | GETFund payable | **On Net Total** | 2.5 | ✓ |
| 3 | VAT payable | **On Net Total** | 15 | ✓ |
| 4 (only if the outlet pays tourism levy) | Tourism levy payable | **On Net Total** | 1 | ✓ |

- **Never "On Previous Row Total" for these rows.** That is the pre-2026
  cumulative method, and GRA will reject every invoice (E708).
- With several "On Net Total" inclusive rows, ERPNext computes
  net = gross ÷ (1 + Σ rates) = gross ÷ 1.20, which matches GRA.
- **All rows inclusive or all exclusive.** A mix has no GRA equivalent.
- Exempt items: an Item Tax Template setting each of these accounts to 0 %.
- CST / excise would need the levy and VAT rows to be "On Previous Row Total"
  pointing at the CST / excise row. Not needed for restaurants; out of scope.
- **This has not been checked on the live site** (no local bench has URY
  installed). It is Phase 0 task P0.3.

## 8. Reference algorithm

This is the specification for `gra_evat/tax/calculator.py`. Pure Python, no
database, fully unit-tested against every example on this page.

```python
from decimal import Decimal as D, ROUND_HALF_UP

NHIL = GETF = D("0.025"); VAT = D("0.15"); TRSM = D("0.01")
ADDON = {"CST": D("0.05"), "EXC_PLASTIC": D("0.05")}

def gross_factor(cat):
    if cat == "EXM":
        return D("1")
    addon = D("1") + ADDON.get(cat, D("0"))
    return addon * (D("1") + NHIL + GETF + VAT + (TRSM if cat == "TRSM" else D("0")))

def line_taxes(unit_price, qty, discount, cat, calc):
    gross_or_net = unit_price * qty - discount
    L = gross_or_net if calc == "EXCLUSIVE" else gross_or_net / gross_factor(cat)
    if cat == "EXM":
        return dict(L=L, A=0, B=0, D=0, E=0, excise=0, vat=0)
    addon = L * ADDON.get(cat, D("0"))
    base = L + addon
    return dict(
        L=L,
        A=base * NHIL,
        B=base * GETF,
        D=addon if cat == "CST" else D("0"),
        E=L * TRSM if cat == "TRSM" else D("0"),
        excise=addon if cat == "EXC_PLASTIC" else D("0"),
        vat=base * VAT,
    )

def round2(x):
    return D(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)
```

**Rounding rule.** Each tax type (NHIL, GETFund, CST, tourism, excise, VAT)
is summed *unrounded* across the lines and rounded **once**, `ROUND_HALF_UP`.
`totalLevy` is then the sum of those rounded per-tax totals.

This matches GRA's own POS receipt (NHIL 2.60 + GETFund 2.60 = 5.20, where
rounding the sum once would give 5.21; VAT 15.625 → 15.63). It also matches
ERPNext, which books one rounded row per tax. GRA's workbook rounds the grand
sum instead, so its figures can differ by a cent (e.g. CST 10.25 in the
workbook against 10.26 here). Both are far inside the ±0.50 tolerance.

## 9. Test vectors for the calculator

Every row below becomes a unit test (see [07 §4](07-implementation-plan.md#4-test-plan)).
Expected values were computed with the §8 algorithm and rounding rule, and
cross-checked against the workbook and GRA's receipts.

| # | calc | lines (qty × price, category, discount) | expect totalLevy | expect totalVat | expect excise |
|---|---|---|---|---|---|
| T1 | EXCL | 45 × 100 | 225.00 | 675.00 | 0 |
| T2 | EXCL | 1 × 100 CST | 10.26 (workbook 10.25) | 15.75 | 0 |
| T3 | EXCL | 1 × 100 TRSM | 6.00 | 15.00 | 0 |
| T4 | EXCL | 1 × 100 EXC_PLASTIC | 5.26 (workbook 5.25) | 15.75 | 5.00 |
| T5 | INCL | 1 × 100 | 4.16 (workbook 4.17) | 12.50 | 0 |
| T6 | INCL | 1 × 100 CST | 8.13 | 12.50 | 0 |
| T7 | INCL | 1 × 100 TRSM | 4.97 (workbook 4.96) | 12.40 | 0 |
| T8 | INCL | 32 × 540 EXC_PLASTIC | 720.00 | 2,160.00 | 685.71 |
| T9 | INCL | 5 × 25 (GRA POS receipt) | **5.20** (receipt: 2.60 + 2.60) | 15.63 | 0 |
| T10 | EXCL | 12 × 300 + 95 × 40 (GRA A4 receipt) | 370.00 | 1,110.00 | 0 |
| T11 | EXCL | 1 × 1000, GENERAL discount 100 | 45.00 | 135.00 | 0 |
| T12 | INCL | 1 × 1200, GENERAL discount 120 | 45.00 | 135.00 | 0 |
| T13 | INCL | three distinct codes, 1 × 7 each | 0.88 | 2.63 | 0 |
| T14 | INCL | 1 × 120 EXM | 0.00 | 0.00 | 0 |
| T15 | INCL | 1 × 120 plus 1 × 120 fully discounted | 5.00 | 15.00 | 0 |
