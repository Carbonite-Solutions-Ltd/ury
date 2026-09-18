# 08 — Decisions and risks

## 1. Open decisions — answer these before build

Each has a recommendation. "Blocks" is the first task that needs the answer.
Record the answer and date in the **Decision** column.

| ID | Question | Options | Recommendation | Why | Blocks | Decision |
|---|---|---|---|---|---|---|
| **D1** | Where does the production VSDC run? | GRA cloud · on-prem server | **Start on cloud**; move on-prem if latency or volume demands | Staging is cloud and works. The always-on LAN PC URY already uses as a QZ print gateway could host an on-prem VSDC later. | P4 go-live | — |
| **D2** | What happens when a sale can't be signed (GRA down, config error)? | allow the sale, print a provisional receipt, sign later · block the sale | **Allow and sign later** | URY's hard lesson: rules that halt trading strand outlets. Nothing is lost: the queue signs it and the reconciliation report shows it until then. Needs GRA's view on provisional receipts (§3). | P1.10 | — |
| **D3** | Cancelling a paid/signed sale | refuse and require Return (desk `before_cancel` **and** URY `cancel_order`) · auto-send a full refund | **Refuse, require Return** | Keeps URY's documents and GRA's in lock-step. **This adds a restriction to URY**, so it needs your explicit OK. | P1.10, P3.1 | — |
| **D4** | Print a refund slip with GRA's stamp on Return and on Undo Return? | yes · no | **Yes** | Each refund and cancellation is its own signed fiscal document. | P3.6 | — |
| **D5** | Reprints that add a late stamp: count against the cashier's reprint limit? | exempt · count | **Exempt** | Otherwise cashiers run out of reprints through no fault of their own. | P3.7 | — |
| **D6** | Does the client pay the 1 % **tourism levy**? | yes → tourism tax row + `TRSM` items · no | ~~Ask the accountant~~ | **ANSWERED 2026-09-18 by the data**: `Ghana Tax - LR` already carries a 1 % Tourism Levy row, so items go to GRA as `TRSM` and the gross factor is 1.21. | P0.3 | **Yes — tourism levy applies** |
| **D7** | Which items (if any) are **exempt / zero-rated**? | list · none | **Ask the accountant** | They need an Item Tax Template and the `EXM` category. | P0.3 | — |
| **D8** | What name and TIN are sent for customers without a TIN? | customer's own name + `C0000000000` · always a fixed "Cash Customer" + `C0000000000` | **Customer's own name; the POS Profile's default customer as "Cash Customer"**; TIN `C0000000000`. **Confirm with GRA.** | GRA's own POS sample uses a named walk-in with the placeholder TIN, but the docs say the name must match "day 1" (not enforced on staging). | P1.8 | — |
| **D9** | Receipt layout | add the E-VAT block to the client's existing bill format · switch to GRA's layout | **Add the block**, ship GRA's layout as a reference format. **Ask GRA whether the logo is required.** | Least disruption; both samples show the GRA logo. | P2.3 | — |
| **D10** | iHotel room charges (never submitted, settled via the folio) | Phase 5 · include in v1 | **Phase 5, approved separately** — but note: until then, restaurant sales charged to rooms are **not reported to GRA** | It needs the `statment_of_account` flow and iHotel changes. The client must accept the gap knowingly. | — | — |
| **D11** | Where does `gra_evat` live? | its own repository · a folder in the URY repo | **Its own repository**, installed with `bench get-app` | Frappe apps need their own directory; reusable for other Ghana clients. Same push rules as URY. | P0.6 | — |
| **D12** | Unsigned sales at shift close | warn · block the close | **Warn** | Blocking the close strands the outlet (URY 2026-07-29 lesson); the report tracks them. | P3.9 | — |
| **D13** | Historic invoices before go-live | never send · back-fill from a date | **Never send** | GRA only needs transactions from go-live; back-filling risks old-regime dates and collisions. | P1.10 | — |
| **D14** | Per-branch invoice-number prefix | none · a short site code (e.g. `LND-`) | **Use a prefix** | Protects against re-issued numbers after a site restore or naming-series reset. It changes the number GRA stores and prints, so pick it once. | P1.8 | — |
| **D15** | ERPNext versions | v16 only · v15 too | **v16 only** | This bench is v16; v15 stores item-wise tax differently. | P1.8 | — |

## 2. Risk register

L = likelihood, I = impact (H / M / L).

| ID | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | **Production is stricter than staging** (TIN length, partner-name consistency, renames, invoice-number characters, field lengths) | M | H | Validate to the documented, stricter rules anyway; run a production smoke test on day one |
| R2 | The docs don't match the server (off-by-one codes, extra shapes), and the API may change | H | M | Classify by code *and* message; unknown → Rejected for review; re-run the contract suite before every release; keep a copy of the collection and compare its hash |
| R3 | The shared staging key is rate-limited by other integrators | H | L | Develop on `-006`; the contract suite waits on E990 |
| R4 | Latency keeps growing (≈2 s → 3.2 s median in ten days) | M | M | Configurable timeout; the queue is the safety net; on-prem option (D1) |
| R5 | **The live tax template is cumulative** or otherwise wrong | M | H | Phase 0 check (P0.3); the calculator check holds mismatches with a precise hint |
| R6 | GRA signs a sale that URY then rolls back | L | H | Nothing is sent before commit (`after_commit`) |
| R7 | A sale is signed twice | L | H | Atomic claiming, unique ledger index, GRA idempotency + callback |
| R8 | A response is lost | M | M | `Unknown` state; callback before any resend |
| R9 | An old invoice number is re-issued (restore / reset) and GRA returns a stranger's stamp | L | H | Per-branch prefix (D14); callback stamps verified; production guard |
| R10 | An item's category changes and GRA rejects every later sale (E806) | M | H | Category embedded in the GRA item code |
| R11 | One item at two prices on one invoice (E827) | L | M | Weighted-price merge; precision checked in P1.13, fallback to split codes |
| R12 | A URY path bypasses hooks (raw SQL) | M | H | `cancel_order` guard (P3.1); the sweeper finds submitted invoices with no ledger row |
| R13 | A dev or restored site signs into production | L | H | Site-config guard + host sanity check |
| R14 | Room-charged sales are never reported | H (until Phase 5) | H | D10 made explicit to the client |
| R15 | The thermal printer renders the QR illegibly | M | M | P2.4 real-printer scan test; PNG at a suitable scale, ≥ 25 mm |
| R16 | Many tills paying at once tie up web workers in `sign_now` | M | M | Concurrency cap of 3; overflow goes straight to the queue |
| R17 | A production key leaks | L | H | Password field; never logged; only public staging keys ever in git |
| R18 | An ERPNext upgrade changes how item-wise tax is stored | M | M | Builder tests on real invoices catch it; small adapter layer |
| R19 | A long GRA outage builds a large backlog and many provisional receipts | L | M | Drains at ~45/min per branch; alerts; reprint flow |
| R20 | Customers leave with provisional receipts | M | M | Clear wording; D2; GRA's view requested (§3) |
| R21 | ERPNext's 1-cent recomputation gap on consolidated Sales Invoices looks like an E-VAT mismatch | M | L | The report compares POS Invoices with GRA; the GL gap is shown separately |
| R22 | A carried-over bill dated before 2026 | L | L | Refused locally with a clear message; handled manually |
| R23 | The staging sandbox changes or disappears | L | M | Reference copies and the full call log are kept in [reference/](reference/) |

## 3. Questions for GRA

To ask during onboarding (P0.5). Record the answers here.

| # | Question | Answer |
|---|---|---|
| G1 | Production host(s) and the credential process per branch | — |
| G2 | Is the **GRA logo** required on printed receipts? Which fields are mandatory on a thermal receipt? | — |
| G3 | For walk-in customers: which name should be sent with `C0000000000`? Is the "name must match day 1" rule (E807/E811) enforced in production? | — |
| G4 | Is a **provisional receipt** (paid, not yet signed, reprinted once signed) acceptable during an outage? What wording is required? | — |
| G5 | Which item categories are enabled for the client's TIN (e.g. `TRSM`, `EXM`)? | — |
| G6 | What are the production limits on `invoiceNumber` characters and length, `itemCode` length, TIN format? | — |
| G7 | What is the unit-price decimal precision limit? | — |
| G8 | The doc's error codes around E818–E829 differ from the server's. Which is authoritative, and is there a changelog? | — |
| G9 | Is the rate limit per key, per TIN or per IP, and over what window? | — |
| G10 | Is `taxType` (sent as `STANDARD` in the 2026 samples) required? What other values exist? | — |
| G11 | Is there an agreed approach for restaurant sales charged to a hotel room (statement of account)? | — |
| G12 | Flat-rate taxpayers: is any separate flow required? | — |

## 4. Decision log

| Date | Decision | By |
|---|---|---|
| 2026-09-07 | Build as a **separate app**; goal = URY tax equals GRA tax | user |
| 2026-09-07 | Develop against the **public staging keys** | user |
| 2026-09-17 | **Document and plan before any build**; keep the plan in the URY repo | user |
| 2026-09-18 | P0.2 + P0.3 closed: `local.16.land` runs URY with client data; the live tax template is the correct 2026 method **and includes the tourism levy** (D6 = yes). Found that the `Sitout` POS Profile has no tax template — its sales are untaxed and must be fixed before go-live. | verified from the site |
