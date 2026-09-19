# GRA E-VAT integration — planning pack

> **Status: PLANNING. Nothing is built yet.** Build starts only after the open
> decisions in [08-decisions-and-risks.md](08-decisions-and-risks.md) are
> answered and the plan in [07-implementation-plan.md](07-implementation-plan.md)
> is approved.
>
> Last updated: 2026-09-17.

## The goal, in one paragraph

When a URY POS Invoice is **paid** (submitted), its tax is pushed to the Ghana
Revenue Authority's E-VAT system (the "VSDC"), which signs it and returns a
fiscal stamp + QR code that must be printed on the customer's receipt. When a
paid sale is **reversed** (returned, or a return is undone), the matching
reversal is pushed too. **For any period, the tax recorded in URY must equal the
tax held by GRA** — and we must be able to prove it with a report.

This will be a **separate Frappe app, `gra_evat`**, plus a thin layer of glue
inside URY. The planning documents live here in the URY repo because the
business driver is URY.

## Read in this order

| # | Document | What's in it |
|---|---|---|
| 01 | [API reference](01-api-reference.md) | Every endpoint, header, field, flag and response shape — the official docs **plus** what the live sandbox actually does |
| 02 | [Tax calculation](02-tax-calculation.md) | The 2026 tax rules, every category, inclusive/exclusive, discounts, rounding, and the ±0.50 validator tolerance |
| 03 | [Errors and responses](03-errors-and-responses.md) | The five response shapes, the verified error-code map, and how each code should be handled |
| 04 | [Sandbox verification](04-sandbox-verification.md) | The ~140 live calls we made against GRA staging and what each proved |
| 05 | [URY integration analysis](05-ury-integration-analysis.md) | Every URY code path that creates or reverses a paid invoice, field mapping, and the landmines |
| 06 | [App design](06-app-design.md) | `gra_evat` architecture: doctypes, state machine, flows, printing, reconciliation, security |
| 07 | [Implementation plan](07-implementation-plan.md) | Phased build plan, files, test matrix, verification and rollout checklists |
| 08 | [Decisions and risks](08-decisions-and-risks.md) | **Open decisions that need an answer before build**, and the risk register |
| — | [reference/](reference/) | Raw source material: the official Postman collection, GRA's tax workbook, sample receipts, the sandbox call log, the probe harness |

## The ten things that matter most

1. **The official docs are wrong in several places.** The live sandbox is the
   authority. Error codes around the levies are consistently **one lower** than
   documented, there are **five** response shapes (docs show two), and bad
   credentials return **HTTP 401**, not 403. See [03](03-errors-and-responses.md).
2. **Tax in 2026 is not cumulative.** NHIL 2.5 %, GETFund 2.5 % and VAT 15 % are
   all charged on the **same base**. Effective rate 20 %. The pre-2026
   cumulative method is **rejected** (E708). See [02](02-tax-calculation.md).
3. **GRA's validator tolerates ±0.50** on totals, whatever the invoice size. It
   will not catch cent-level drift, so **our own ledger is what proves parity**.
4. **There is no "cancel invoice" at GRA.** A signed sale can only be reversed
   by a refund. URY's Return / Undo Return map onto REFUND / PARTIAL_REFUND /
   REFUND_CANCELATION cleanly.
5. **A lost response is always recoverable.** Resending a signed invoice gives
   E700; `POST /invoice/callback` returns a byte-identical stamp, and returns
   E704 if GRA never received it. So a network timeout is never fatal.
6. **GRA remembers each item code's tax category forever** (E806 on change),
   and rejects one item code carrying two unit prices on one invoice (E827).
7. **Never call GRA before the database commits.** If GRA signs a sale that URY
   then rolls back, the two sides disagree permanently.
8. **URY has a latent hole:** `cancel_order` sets `docstatus=2` by raw SQL with no
   guard, so it could cancel a *paid* invoice with no hook firing. It must refuse
   paid invoices before go-live. See [05](05-ury-integration-analysis.md).
9. **Latency is 3–6 s per signed invoice** on staging (median 3.2 s on
   2026-09-17, up from ~2 s ten days earlier). Payment must not wait forever.
10. **The public staging key `-001` is shared by every integrator** and is often
    rate-limited (E990). Use `CXX000000YY-006` for development.

## Environments

| | Staging (now) | Production (later) |
|---|---|---|
| Host | `https://vsdcstaging.vat-gh.com/vsdc/api/v1/taxpayer/{reference}` | issued by GRA at onboarding |
| Keys | public, published in the docs (see [reference/](reference/)) | issued per branch — **never commit** |
| Use for | all development and testing | live trading only, behind a site-config guard |

## Source material

- Official docs: <https://documenter.getpostman.com/view/29809098/2sBXVeGCzK>
  ("For Taxpayers-GRA E-VAT API - VER 8.2"). The page is JavaScript-rendered;
  the raw collection is at
  `https://documenter.gw.postman.com/api/collections/29809098/2sBXVeGCzK?segregateAuth=true&versionTag=latest`
  and a copy is saved in [reference/](reference/).
- Everything linked from the docs (tax workbook, currency list, sample
  receipts) is saved in [reference/](reference/) too, so this pack does not
  depend on any external page staying up.
