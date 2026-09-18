# 07 — Implementation plan

**Nothing here starts until the plan is approved and the decisions in
[08](08-decisions-and-risks.md) are answered.** Phases run in order; each has
an exit gate. Sizes are relative (S / M / L), not time estimates.

URY's working rules apply throughout (see the URY `CLAUDE.md`): no `git push`
without explicit permission for that push, a new branch for every push, tests
before asking to push, a Fixes-log entry for URY changes, and **surfacing any
new restriction before adding it**.

---

## 1. Phases at a glance

| Phase | Goal | Touches URY? | Exit gate |
|---|---|---|---|
| **0 — Prerequisites** | decisions answered, a working dev site, facts from the client and GRA | no | §2 checklist complete |
| **1 — Core app** | `gra_evat` signs POS Invoices, returns and undo-returns end to end | no | all unit and integration tests green; sandbox contract suite green; a POS Invoice on the dev site gets `Signed` |
| **2 — Printing and reconciliation** | fiscal receipts with QR; the reconciliation report | no | a printed QR scans to GRA's verification page; the report shows 0.00 for a mixed test day |
| **3 — URY glue** | the POS signs at payment, shows status, prints the right receipt; `cancel_order` guarded | **yes** | browser end-to-end matrix (§6) passes |
| **4 — Hardening and go-live** | failure drills, then production | config only | drills pass; day-one reconciliation is 0.00 |
| 5 — Later | iHotel, desk invoices, notes, purchases, inventory | — | separately approved |

## 2. Phase 0 — Prerequisites

| # | Task | Output |
|---|---|---|
| P0.1 | Answer decisions D1–D15 ([08](08-decisions-and-risks.md)) | decisions recorded in 08 |
| ~~P0.2~~ | ~~Dev site with `erpnext`, `hrms` and `ury`~~ **Done** — `fb-16-landn` / `local.16.land` already runs frappe 16.33, erpnext 16.34 and ury 0.2.1 with the client's data (1,529 POS Invoices). An earlier note here said no bench had URY: `site_config.json`'s app list was stale, `bench list-apps` reads the database. | ✅ |
| ~~P0.3~~ | ~~Check the live tax setup~~ **Done 2026-09-18** — `Ghana Tax - LR` is NHIL 2.5 + GETFund 2.5 + **Tourism 1.0** + VAT 15, all *On Net Total*, all inclusive: exactly the 2026 GRA method. Two findings: **the tourism levy applies** (D6 answered → `TRSM`, factor 1.21) and **the `Sitout` POS Profile has no tax template**, so its sales are untaxed. See [05 §3.10](05-ury-integration-analysis.md#310-the-tax-setup--checked-2026-09-18-and-it-is-correct-). | ✅ + one fix for the client |
| P0.4 | Collect client facts: TIN, registered business name, branches and their GRA branch codes, whether the tourism levy applies (D6), exempt items (D7), the bill print format in use, printer models | a client fact sheet |
| P0.5 | GRA onboarding: request production credentials per branch; confirm cloud vs on-prem (D1); ask the GRA questions in [08 §3](08-decisions-and-risks.md#3-questions-for-gra) | answers recorded in 08 |
| P0.6 | Create the `gra_evat` repository (D11) | empty repo, same push rules as URY |

## 3. Phase 1 — Core app

Build bottom-up: pure logic first (fully testable without a site), then
doctypes, then the moving parts.

| # | Task | Files | Size | Tests |
|---|---|---|---|---|
| P1.1 | Scaffold: `bench new-app gra_evat`, module "GRA EVAT", `pyproject.toml` (no new dependencies) | app skeleton | S | app installs and uninstalls cleanly |
| P1.2 | Tax calculator ([02 §8](02-tax-calculation.md#8-reference-algorithm)) | `evat/calculator.py` | S | T1–T15 from [02 §9](02-tax-calculation.md#9-test-vectors-for-the-calculator) plus edge cases (§4.1) |
| P1.3 | Response parser and classifier ([03](03-errors-and-responses.md)) | `evat/responses.py` | S | every shape and code recorded in the sandbox log, used as fixtures |
| P1.4 | HTTP client and rate limiter | `evat/client.py`, `evat/ratelimit.py` | S | mocked transport: timeout → `Unknown`, refused → `Retrying`, 5xx → `Unknown`, 429 → `Retrying`; the key never appears in logs |
| P1.5 | Doctypes: Settings, Tax Account, Branch, Transaction, Attempt; permissions; unique index | `gra_evat/doctype/*`, `install.py` | M | validation (reference format, host rules, Password field); index rejects duplicates |
| P1.6 | Custom fields from one source | `setup/custom_fields.py`, `install.py` | S | runs twice with no changes; `no_copy` confirmed on a return made with `make_return_doc` |
| P1.7 | Config resolution and environment guard | `evat/config.py` | S | branch → config; company default; production refused without the site-config flag; staging host refused in Production |
| P1.8 | Payload builder ([06 §6](06-app-design.md#6-payload-builder)) | `evat/builder.py` | **L** | §4.2 — built from **real POS Invoices** created on the dev site |
| P1.9 | State machine and sending ([06 §4–5](06-app-design.md#4-the-transaction-state-machine)) | `evat/service.py` | **L** | fake transport covering every transition, callback verification, collision detection, stamp mirroring |
| P1.10 | Doc events: `on_submit`, `before_cancel`, `on_cancel` | `evat/events.py`, `hooks.py` | M | §4.3 |
| P1.11 | Worker, sweeper, health job | `evat/worker.py`, `hooks.py` | M | due-row selection, dependency waiting, stale `Sending`, missing-transaction detection |
| P1.12 | Whitelisted API ([06 §12](06-app-design.md#12-whitelisted-api)) | `api.py` | M | permission checks, `sign_now` timeout, concurrency semaphore |
| P1.13 | Sandbox contract suite (opt-in, uses the network) | `tests/sandbox_contract.py` | M | §4.4 |

**Exit gate:** all Phase 1 tests pass; the contract suite passes on key
`CXX000000YY-006`; on the dev site, paying a POS order produces a `Signed`
transaction whose stamp is mirrored onto the invoice; a partial return and
its undo produce signed `PARTIAL_REFUND` and `REFUND_CANCELATION`
transactions.

## 4. Test plan

Following URY rule 6: every module with logic gets a test file with many
scenarios, runnable through a `run_*_tests()` wrapper with
`bench --site <site> execute …` (the usual `bench run-tests` is blocked by
ERPNext's test bootstrap on these sites). The pure modules (`calculator`,
`responses`) also run under plain `python -m unittest`, so **they can run in
CI without a bench**.

### 4.1 Calculator (`test_calculator.py`)
- T1–T15 exactly as in [02 §9](02-tax-calculation.md#9-test-vectors-for-the-calculator).
- Rounding: per-tax rounding, `ROUND_HALF_UP`, 0.005 boundaries.
- Fractional quantities (0.5, 1.5); very large amounts (1,000,000).
- `EXM` gives zeros; unknown category raises.
- Exclusive and inclusive give the same tax for the same net value.
- A 100 % discount gives zero tax on that line.

### 4.2 Builder (`test_builder.py`) — on real ERPNext invoices
- Single line, inclusive; several lines; exclusive template.
- Invoice-level discount (URY's `additional_discount_percentage`): the derived
  line discounts sum to the header, and the calculator agrees with the booked
  tax.
- Same item on two lines (two notes) → one GRA line, `ysdcitems` expectation 1.
- Same item at two prices → one line at the weighted price; `totalAmount`
  unchanged.
- Category suffix (`~EXM`); 60-character item code → hashed, stable, ≤ 50.
- Description over 100 → trimmed.
- Walk-in customer → B2C name and TIN; customer with a `tax_id` → B2B;
  malformed TIN → refused.
- Unmapped tax account → refused; mixed inclusive/exclusive → refused;
  disallowed category → refused.
- **Tax template set to "On Previous Row Total" → held** with the template hint.
- Future date, pre-2026 date, pre-go-live date → refused / not applicable.
- Zero-priced line dropped; all-zero invoice → not applicable.
- Return: full → `REFUND`; partial → `PARTIAL_REFUND`; a second return after a
  first → `PARTIAL_REFUND`; lines reuse the sale's codes and prices;
  quantities positive.
- Cancellation payload fields.

### 4.3 Events and service (`test_events.py`, `test_service.py`)
- Submit creates exactly one transaction, even if the hook runs twice.
- Nothing is sent before commit; a rolled-back submit leaves no transaction and
  no job.
- Claiming: two claimers, one wins.
- Every outcome class → the right state (success, E700 → callback, E704 on
  callback → resend, 429, timeout, 5xx, E900 → branch unhealthy, E708 →
  rejected, unknown code → rejected).
- Callback stamp with the wrong `num`, `flag` or item count → rejected
  (collision).
- A refund waits for its sale; a voided sale voids its refund.
- `before_cancel`: refused for `Signed` / `Sending` / `Unknown`; allowed and
  voided for `Queued` / `Retrying` / `Rejected`; refused if claimed
  mid-cancel.
- Undo return for each refund state (06 §5.3).
- Manual retry rebuilds the payload only from `Rejected`.
- Stamp mirrored onto the POS Invoice; a return does not inherit it.

### 4.4 Sandbox contract suite (manual, network)
Run with `bench --site <site> execute gra_evat.tests.sandbox_contract.run`
against key `-006`. Unique invoice numbers per run.
1. health; 2. sale → signed; 3. replay → E700 → callback matches;
4. partial refund → signed; 5. second partial refund; 6. over-refund → E828
handled as rejected; 7. refund cancellation → signed; 8. full refund on a
fresh sale; 9. **weighted-price decimal precision** (resolves the open item in
06 §6.1); 10. a GENERAL discount invoice built by the builder; 11. an `EXM`
line; 12. a wrong key → CONFIG class.
Tolerates E990 by waiting and retrying.

### 4.5 Reconciliation (`test_reconciliation.py`, Phase 2)
A day with sales, a partial return, a full return, an undo, one rejected and
one missing invoice → the totals, signs, differences and counts are exactly as
expected.

### 4.6 Printing (`test_printing.py`, Phase 2)
Receipt state for draft / paid-unsigned / signed / not applicable; QR helper
returns an image; the block renders with the stamp fields.

## 5. Phase 2 — Printing and reconciliation

| # | Task | Size |
|---|---|---|
| P2.1 | Jinja helpers `gra_evat_stamp`, `gra_evat_qr` | S |
| P2.2 | Receipt block template (06 §8.2) | S |
| P2.3 | Reference print format "GRA EVAT POS Receipt" (06 §8.3) | M |
| P2.4 | **Real printer test** through URY's QZ path: print a signed receipt on the client's thermal printer; the QR is at least 25 mm and **scans to verification.vat-gh.com** with a phone | S |
| P2.5 | Reconciliation report (06 §9) + tests | M |
| P2.6 | Workspace, number cards (signed today, pending, rejected, missing), alerts | S |
| P2.7 | Transaction list actions: Retry, Check with GRA, Void | S |

**Exit gate:** printed QR scans; the report shows 0.00 difference for a mixed
test day and flags a deliberately unsigned invoice.

## 6. Phase 3 — URY glue (URY repo)

| # | Task | Where | Size |
|---|---|---|---|
| P3.1 | `cancel_order` refuses `docstatus != 0` ("This bill is paid. Use Return."); drop `Recently Paid` from the Cancel button condition. **New restriction — needs D3 approval.** | `ury_order.py`, `Orders.tsx` | S |
| P3.2 | `getPosProfile` returns `evat_enabled` | `api.py` | S |
| P3.3 | `lib/evat-api.ts`: `signNow`, `getStatus`; treats "method not found" as disabled | new file | S |
| P3.4 | PaymentDialog: after payment, "Signing with GRA…" → print; if still pending, print provisional and warn | `PaymentDialog.tsx` | M |
| P3.5 | ItemSplitFlow: same, per bill | `ItemSplitFlow.tsx` | S |
| P3.6 | Return and Undo Return: sign; print a refund slip (D4) | `ReturnDialog.tsx`, `Orders.tsx` | M |
| P3.7 | Orders page: E-VAT badge on paid orders; manager Retry; reprint when a stamp arrives late, not counted against the reprint limit (D5) | `Orders.tsx`, `ury_print.py` | M |
| P3.8 | Customer quick-create: optional TIN (`Customer.tax_id`), optional lookup | `CustomerSelect.tsx`, `customer-api.ts` | S |
| P3.9 | POS Closing dialog: "N sales not yet signed with GRA" (warn only, D12) | `POSClosingDialog.tsx`, `api.py` | S |
| P3.10 | Settings page: E-VAT health section (optional) | `Settings.tsx` | S |
| P3.11 | URY Fixes-log entry; `tsc -p tsconfig.app.json --noEmit`, eslint (no new problems), `yarn build`; `py_compile` | — | S |

### Browser end-to-end matrix (exit gate)
| # | Scenario | Expected |
|---|---|---|
| E1 | Take-away, single payer | fiscal receipt with QR prints; badge **Signed** |
| E2 | Table order: bill printed, then paid | first print says **BILL — NOT A VAT INVOICE**; post-payment print is fiscal |
| E3 | Split by value (two payers) | both receipts show the same stamp |
| E4 | Split by item (three bills) | three signed invoices, three receipts |
| E5 | On-account sale | signed at payment |
| E6 | Invoice discount 10 % | signed; tax matches the booked tax |
| E7 | Same dish twice with different notes | signed; line count 1 for that dish |
| E8 | Partial return | refund signed; refund slip prints |
| E9 | Undo that return | cancellation signed |
| E10 | Full return | `REFUND` signed |
| E11 | Captain tries to cancel a paid bill (API call) | refused with "Use Return" |
| E12 | GRA unreachable (bad host) during a sale | sale completes; **provisional** receipt; badge **Queued/Retrying**; after restoring the host, signs automatically; reprint gives the fiscal receipt |
| E13 | Customer with a TIN | receipt shows the TIN; GRA payload is B2B |
| E14 | Close the shift with one unsigned sale | warning shown; close allowed |
| E15 | Admin payment | no auto-print (existing behaviour), but the sale is signed |

## 7. Phase 4 — Hardening and go-live

### 7.1 Drills (staging)
| # | Drill | Pass when |
|---|---|---|
| H1 | Outage: bad host for 30 minutes of simulated trading | no sale blocked; queue drains after restore; **no duplicates** at GRA (callback per number) |
| H2 | Volume: 200 sales in 5 minutes on key `-006` | rate limiter holds; no E990 storm; all signed |
| H3 | Crash: kill the worker mid-send | stale `Sending` → `Unknown` → callback resolves; exactly one stamp |
| H4 | Collision: reuse an old invoice number | `Rejected` ("collision"); no foreign stamp stored |
| H5 | Wrong template: switch a row to *On Previous Row Total* | sale held with the template hint; nothing sent |
| H6 | Wrong key | branch `Unhealthy`; alert; queue resumes after fixing the key |
| H7 | Production guard: set Production without the site-config flag | nothing is sent; clear message |

### 7.2 Go-live checklist (production site only)
- [ ] Production credentials entered per branch (Password field), host and deployment set
- [ ] `"gra_evat_allow_production": 1` in **this site's** `site_config.json` only
- [ ] Settings → environment **Production**
- [ ] `go_live_date` set to the first trading day
- [ ] Tax templates verified (*On Net Total*); every tax account mapped
- [ ] Item categories set (`EXM`, `TRSM` where applicable); branch `allowed_categories` set
- [ ] B2C name and TIN confirmed with GRA
- [ ] Bill print format includes the receipt block; QR scan test passed on the real printer
- [ ] `bench --site <site> migrate`, `bench restart`, URY frontend build deployed
- [ ] First live sale signed and its QR scanned; first return and undo signed
- [ ] End of day one: reconciliation difference **0.00**, nothing missing or rejected

### 7.3 First week
Daily reconciliation per branch; review every `Rejected`; watch latency and
`Unknown` counts.

## 8. Deployment

**`gra_evat`** (new app):
```bash
bench get-app <gra_evat repo url>
bench --site <site> install-app gra_evat     # creates doctypes, custom fields, index
bench --site <site> migrate
bench restart                                # doc_events and scheduler are loaded at start-up
```
**URY glue:** the normal URY deploy (`deploy-ury.yml`): pull → `yarn build` →
`bench build --app ury` → `migrate` → `restart`.

**CI for `gra_evat`:** `compileall`, JSON validity, and the pure unit tests
(`calculator`, `responses`, parts of `builder`) with plain `python -m unittest`
— no bench needed. The sandbox suite is never run in CI.

## 9. Definition of done (v1)

1. Every paid POS Invoice since go-live is **Signed**, or visibly queued or
   rejected with a reason.
2. Every return is a signed `REFUND` / `PARTIAL_REFUND`; every undo is a signed
   `REFUND_CANCELATION`.
3. A signed sale cannot be cancelled without going through Return.
4. Paying a bill prints a fiscal receipt with a scannable QR when GRA is
   reachable, and never blocks trading when it isn't (under D2 as proposed).
5. The reconciliation report shows **0.00** difference between URY and GRA for
   any closed day.
6. All unit, integration and contract tests pass; drills H1–H7 pass.
7. This pack is updated with anything learned during the build.
