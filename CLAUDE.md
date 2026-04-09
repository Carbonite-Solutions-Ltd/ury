# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules for this project (READ FIRST)

These are user-imposed rules for how Claude should behave in this repo. They override the default harness behavior and the superpowers skill system.

1. **Do NOT invoke any `superpowers:*` skill** (brainstorming, TDD, debugging, writing-plans, using-git-worktrees, verification-before-completion, etc.) when working in this repo. The user has disabled them for URY. Non-superpowers skills (`update-config`, `simplify`, `find-skills`, …) are fine if they actually apply.
2. **Never `git push` without explicit permission for that specific push.** A prior approval is not standing. When permission is granted:
   - Create a new branch — never push to `develop` or `main` directly.
   - The push must go out under the user's git credentials (`buildwithmoi`) from his local machine. Do not attribute commits/pushes to Claude.
   - No `Co-Authored-By: Claude` trailers on commits that will be pushed to this remote.
   - No GitHub PRs created by me. The user merges branches manually.
3. **Test before asking to push.** Do not surface "ready to push?" until the change has been verified working — rebuild affected frontends, restart/migrate the bench, walk through the reproduction path, and confirm the original bug is gone AND nothing adjacent broke. If something can only be tested in the user's browser session, say so and wait for his confirmation before raising the push question.
4. **Current direction: reduce permission restrictions.** The existing role-gating in URY is tangled and blocks legitimate users (including Administrator). Default to loosening overly aggressive checks, and always surface other restrictive checks you notice to the user *before* touching them.
5. **Log every fix in the Fixes log section below.** Each entry: date, symptom, root cause, file(s) changed, verification. Future-me reads this before making similar changes to avoid reintroducing the same bug.
6. **Keep session memory current** at `~/.claude/projects/-home-patoo-fb-dev16-5-apps-ury/memory/`. After any meaningful checkpoint, update the relevant memory file so the next session can resume without re-explanation.

## What this is

URY is a **Frappe/ERPNext custom app** for restaurant management (POS, KDS, P&L reports). It depends on `erpnext` and `hrms` and is installed into a Frappe bench via `bench get-app` / `bench install-app`. Nothing in this repo runs standalone — it must live inside a `frappe-bench/apps/ury` checkout and be served by a Frappe site.

Current working checkout: [apps/ury](.) inside `fb-dev16-5` bench. Sibling paths `../../../sites/common_site_config.json` and `../../frappe` are assumed to exist (the Vite dev servers read `common_site_config.json` directly — see [urypos/proxyOptions.js](urypos/proxyOptions.js)).

## Repository layout — the four sub-projects

This is a **polyglot monorepo** containing one Python app and three independent Node frontends. They share no code; each is built and shipped separately, but all three frontend bundles end up served by the same Frappe site.

| Path | Stack | Purpose |
|---|---|---|
| [ury/](ury/) | Python / Frappe | Backend: DocTypes, hooks, whitelisted APIs, fixtures, scheduled tasks |
| [pos/](pos/) | React 19 + TypeScript + Vite + Zustand + Tailwind | **v2 POS** (current) — terminal-based cashier UI |
| [urypos/](urypos/) | Vue 3 + Vite + Pinia + Tailwind + Flowbite | **v1 POS** (legacy) — support ends Dec 2025 per [README.md](README.md) |
| [URYMosaic/](URYMosaic/) | Vue 3 + Vite + Tailwind | Kitchen Display System (KDS) with KOT printing |

All three frontends use [frappe-js-sdk](https://github.com/The-Commit-Company/frappe-js-sdk) to call whitelisted Python methods, and [qz-tray](https://qz.io/) for direct-to-printer output. The React `pos/` also uses `socket.io-client`-style realtime via a custom listener ([pos/src/lib/kot-listener.ts](pos/src/lib/kot-listener.ts)); the Vue apps do the same.

## Build & install — the critical detail

**Each frontend builds into `ury/public/<app>/` and its HTML entry is copied into `ury/www/<app>.html`.** That's how Frappe's website layer picks them up and routes `/pos`, `/urypos`, `/URYMosaic` (see [ury/hooks.py](ury/hooks.py#L48-L52) `website_route_rules`). Both output directories are **gitignored** — they are regenerated on every build.

Top-level [package.json](package.json) orchestrates all three:

```bash
yarn install           # runs postinstall → installs all 3 frontends
yarn build             # builds all 3 frontends in sequence
```

Individual subproject commands (run from the subproject directory):

```bash
# pos/ (React)
cd pos && yarn dev              # Vite dev server
cd pos && yarn build            # build → ../ury/public/pos + copy HTML
cd pos && yarn lint             # ESLint (TypeScript)

# urypos/ (Vue legacy)
cd urypos && yarn dev
cd urypos && yarn build         # build → ../ury/public/urypos + copy HTML

# URYMosaic/ (Vue KDS)
cd URYMosaic && yarn dev
cd URYMosaic && yarn build      # build → ../ury/public/URYMosaic + copy HTML
```

The Vite dev servers in `urypos/` and `URYMosaic/` proxy `/app|/api|/assets|/files` to the Frappe webserver port read from `sites/common_site_config.json` — so Frappe must be running for dev to work. `pos/`'s [vite.config.ts](pos/vite.config.ts) does **not** configure a proxy (check before adding one).

**When you change frontend code you must `yarn build` for it to appear on the site** — Frappe serves the built assets, not the dev sources, unless you've mounted the Vite dev server separately.

## Installing / running the app inside a bench

Standard Frappe lifecycle (from [INSTALLATION.md](INSTALLATION.md)):

```bash
bench get-app ury <url>               # already done in this checkout
bench --site <sitename> install-app ury
bench --site <sitename> migrate
bench --site <sitename> build         # Frappe asset pipeline
bench --site <sitename> run-tests --app ury    # server tests
```

Node ≥ 18.20 required. `required_apps = ["erpnext"]` is enforced in [ury/hooks.py](ury/hooks.py#L11); `hrms` is a soft dependency for employee reports.

## Backend architecture

The Python package is a standard Frappe app. Key entry points:

- **[ury/hooks.py](ury/hooks.py)** — the manifest. Declares DocType event hooks, scheduler tasks, fixtures, `page_js` overrides, and web route rules. **This is the first file to read when tracing how a POS action reaches the server.**
- **[ury/ury/doctype/](ury/ury/doctype/)** — ~30 custom DocTypes (URY KOT, URY Menu, URY Table, URY Restaurant, URY Daily P and L, sub-POS closing types, etc.). Each follows the Frappe convention: `<name>.json` (schema) + `<name>.py` (controller) + optional `<name>.js` (desk form script).
- **[ury/ury/hooks/](ury/ury/hooks/)** — doc-event handlers wired up in `hooks.py` under `doc_events`. These extend stock ERPNext DocTypes (POS Invoice, Sales Invoice, POS Profile, POS Opening/Closing Entry, Customer, Item) with URY-specific validation and side effects.
- **[ury/ury/api/](ury/ury/api/)** — whitelisted endpoints called from the frontends (KOT generation, KOT display, KOT reprint, order numbering, printing, validation, menu course validation, button permission).
- **[ury/ury_pos/api.py](ury/ury_pos/api.py)** — additional whitelisted API surface (`getTable`, `getRestaurantMenu`, …) specifically for the POS frontends.
- **[ury/www/pos.py](ury/www/pos.py), [ury/www/pos.html](ury/www/pos.html)** (and `urypos.*`, `URYMosaic.*`) — Frappe www entry points. `pos.py` builds the boot context (CSRF, session) and the `.html` is the built Vite shell copied in by `copy-html-entry`.
- **[ury/public/js/](ury/public/js/)** — desk-side JS loaded via `app_include_js` and `page_js` in `hooks.py` (POS print hooks, quick entry, KOT integration inside the Frappe desk).

Scheduled task: `ury.ury.api.ury_kot_validation.kotValidationThread` runs **every minute** (`scheduler_events.cron`, [hooks.py:157-163](ury/hooks.py#L157-L163)).

Fixtures in `hooks.py` export a large set of Custom Fields (mostly on POS Invoice, Sales Invoice, POS Profile, POS Opening/Closing Entry, URY Menu Course, Printer Settings) plus `Role` records named `URY %` and all `Client Script`s. **When adding a Custom Field that URY relies on, append its name to the fixtures list in hooks.py** or it will not ship to other installations.

## Frontend architecture — `pos/` (React v2)

- State: **Zustand** store in [pos/src/store/pos-store.ts](pos/src/store/pos-store.ts), organized into slices under [pos/src/store/slices/](pos/src/store/slices/) (auth, config, orders).
- API client layer: [pos/src/lib/](pos/src/lib/) — one file per domain (`menu-api`, `order-api`, `invoice-api`, `payment-api`, `pos-profile-api`, `terminal-api`, `customer-api`, `aggregator-api`, `kot-listener`, `print-qz`, `pos-display`, …). All wrap `frappe-js-sdk`.
- Routing: React Router v6, basename `/pos` ([pos/src/App.tsx](pos/src/App.tsx#L126)). Pages in [pos/src/pages/](pos/src/pages/).
- Terminal gating: on boot, `App.tsx` resolves a saved terminal from localStorage via `terminal-api`, then shows `TerminalSetupScreen` if none is registered. Terminals are `URY POS Terminal` DocTypes.
- Printing: QZ Tray via [pos/src/lib/print-qz.ts](pos/src/lib/print-qz.ts) (signed with `privateKey.ts` — **do not commit real keys**; `cert.pem` is gitignored).
- Path alias `@` → `src/` (see [pos/vite.config.ts](pos/vite.config.ts)).

## Frontend architecture — `urypos/` (Vue v1, legacy)

- State: **Pinia** stores in [urypos/src/stores/](urypos/src/stores/) — one per domain (`Auth`, `Menu`, `Table`, `Customer`, `invoiceData`, `posOpening`, `posClosing`, `recentOrder`, `Notification`, `frappeSdk`, …).
- Router guards in [urypos/src/main.js](urypos/src/main.js#L19-L29) redirect unauthenticated users to Login and auth'd users away from Login.
- Uses `@syncfusion/ej2-vue-calendars`, `flowbite-vue`, `jsrsasign` (for QZ Tray signing), `moment`.
- Path alias `@` → `src/`.

## Frontend architecture — `URYMosaic/` (Vue KDS)

- Minimal Vue 3 app: two views ([Home.vue](URYMosaic/src/views/Home.vue), [Login.vue](URYMosaic/src/views/Login.vue)) and a `kot.vue` component. Uses `masonry-layout` for the KOT tile board.
- No Pinia; state is component-local. Realtime KOT updates come from `socket.io-client` subscriptions to the Frappe realtime bus.

## Testing

Server-side tests run inside bench:

```bash
bench --site <site> set-config allow_tests true
bench --site <site> run-tests --app ury              # all tests
bench --site <site> run-tests --app ury --doctype "URY KOT"   # one doctype
bench --site <site> run-tests --app ury --module ury.ury.doctype.ury_kot.test_ury_kot
```

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) spins up a fresh bench with MariaDB, installs URY, and runs `bench run-tests --app ury`. Note CI currently pins Python 3.10 and Node 14 — the Node 14 pin is stale relative to the ≥18.20 requirement in `INSTALLATION.md`; prefer local Node 18+ for development.

No frontend test suites are configured. `pos/` has `yarn lint` (ESLint); the Vue projects have no lint script wired up in their `package.json`.

## Brand naming — "URY" vs "ExPOS Restaurant"

**The product has been rebranded from URY to ExPOS Restaurant, but the underlying DocType names, Python package, URL slugs, and file paths are all still `URY …`**. The rebrand is implemented through Frappe's translation layer, not via renames.

- **Translation source:** [ury/translations/en.csv](ury/translations/en.csv) — maps `URY → ExPOS`, `URY Restaurant → ExPOS Restaurant`, `URY Menu Item → ExPOS Menu Item`, etc. Add new mappings here when you reference a new DocType name in user-visible Python strings.
- **Workspace labels** use the `"label": "ExPOS X"` / `"link_to": "URY X"` split (see [ury/ury/workspace/ury/ury.json](ury/ury/workspace/ury/ury.json) line 42+).
- **What to do in backend Python** — when a `frappe.throw` / `frappe.msgprint` message references a DocType name, **wrap the DocType name in `_()` and interpolate it with `.format()`** so the en.csv mapping applies. Example:
  ```python
  frappe.throw(
      _("No {0} is configured for branch '{1}'. Open '{0}' in the desk...").format(
          _("URY Restaurant"), branch_name
      ),
      title=_("Restaurant Not Configured"),
  )
  ```
  Do NOT write `_("No URY Restaurant is configured...")` — the translator matches whole strings, so the mapping in en.csv (`URY Restaurant`) won't fire inside that longer sentence.
- **What to do in the React POS (`pos/`)** — there is no translation layer. **Hardcode the brand string** (`ExPOS Restaurant`, `ExPOS Menu Item`, etc.) in user-visible text. Keep URL paths, DocType arguments, and API payloads literal — they still reference the real `URY …` names (e.g. the deep-link target is `/app/ury-menu-item/new`, not `/app/expos-menu-item/new`). If the brand changes again, grep for `ExPOS` in `pos/src/` to find every hardcoded occurrence.
- **Never rename the DocTypes, Python package, URL slugs, or file paths.** A rename would break the database schema, all existing records, and all API callers. This is a label-only rebrand.

## Gotchas

- **Gitignored build outputs.** `ury/public/{pos,urypos,URYMosaic}` and `ury/www/{pos,urypos,URYMosaic}.html` are all gitignored. Don't edit them — they get overwritten by `yarn build`. Edit the source under `pos/src/`, `urypos/src/`, or `URYMosaic/src/` instead.
- **Three frontends, one backend.** When changing a whitelisted API, check all three frontends for callers. They don't share a client — each has its own API layer.
- **`pos/` has `main.tsx.backup` and `print.ts(.backup)` files in `src/lib/`.** Treat these as developer scratch; don't import from them.
- **Custom Fields live in fixtures, not DocType JSON.** Look in [ury/hooks.py](ury/hooks.py#L249-L381) `fixtures` to see which fields are shipped. A field not in that list will not be installed on other sites.
- **QZ Tray signing keys.** `pos/privateKey.js`, `urypos/privateKey.js`, `pos/src/privateKey.ts`, and `ury/public/pos/assets/ury/files/cert.pem` are local-only — the `.pem` is gitignored; the `privateKey*` files contain placeholders in the repo. Never commit real keys.
- **Legacy POS sunset.** `urypos/` and `URYMosaic/` v1 support ends Dec 2025 per README. New work should target the React `pos/` unless specifically fixing the legacy apps. Always confirm with the user which POS they mean before making changes.
- **POS Opening Entry is per-terminal as of 2026-04-08.** Don't re-add `main_pos_open_check` (the captain-must-be-open gate) or `sub_pos_close_check` (the sub-cashier-must-close-first gate) to [ury/ury/hooks/ury_pos_opening_entry.py](ury/ury/hooks/ury_pos_opening_entry.py) or [ury/ury/hooks/ury_pos_closing_entry.py](ury/ury/hooks/ury_pos_closing_entry.py). Both were deleted on purpose. Under the new model, `posOpening(terminal)` returns 0 if any open entry exists for that terminal (shared mode, multi_cashier OFF) or if THIS user has an open entry on that terminal (strict mode, multi_cashier ON). The captain/sub-cashier ordering is gone — anyone can open the first entry of the day, and per-invoice attribution is preserved through `POS Invoice.owner` + `POS Invoice.custom_terminal`. The `custom_main_cashier` checkbox on POS Profile and the `custom_rooms` table on POS Opening Entry are deprecated (still in the schema for backward compat, but no longer read by the backend).
- **`POS Settings.invoice_type` must be "POS Invoice".** URY's order flow creates `POS Invoice` docs directly; if the site's `POS Settings.invoice_type` is set to "Sales Invoice" (the other ERPNext mode), every POS order submission throws `"Sales Invoice mode is activated in POS. Please create Sales Invoice instead."` from `validate_is_pos_using_sales_invoice` in [apps/erpnext/erpnext/accounts/doctype/pos_invoice/pos_invoice.py](apps/erpnext/erpnext/accounts/doctype/pos_invoice/pos_invoice.py). `ury.install.ensure_pos_settings_configured()` auto-sets this on every `after_install` and `after_migrate` (wired in [ury/hooks.py](ury/hooks.py)), so a `bench migrate` brings drifted sites back into a working state automatically. If you're debugging a "Sales Invoice mode is activated" error: check the `POS Settings` singleton in the desk — something (manual edit, another app) has flipped it back.
- **`patches.txt` section headers matter — and BOTH must be present.** Any patch that reads columns/fields added by the same migration MUST be listed under `[post_model_sync]`. Patches without a section header default to `[pre_model_sync]`, which runs BEFORE Frappe syncs DocType JSON changes to the database. **Second trap:** once ANY section header exists in the file, Frappe's parser requires BOTH `[pre_model_sync]` and `[post_model_sync]` to be present or `bench migrate` throws `Patch type PatchType.pre_model_sync not found in patches.txt`. Always keep the file shaped like this even if one section is empty:
  ```
  [pre_model_sync]

  [post_model_sync]
  ury.patches.vX_Y.some_backfill
  ```
  Also: give any patch that reads a new column a defensive `frappe.db.has_column(...)` guard at the top so a mis-ordered `patches.txt` degrades to a noisy no-op instead of crashing the whole migration.

## Fixes log

Running record of bugs fixed and non-obvious traps discovered. Add new entries at the top. Each entry should answer: what went wrong, why, where it was fixed, how it was verified.

<!-- Template:
### YYYY-MM-DD — short title
- **Symptom:**
- **Root cause:**
- **Files changed:**
- **Verification:**
- **Notes / follow-ups:**
-->

### 2026-04-09 — In-POS Close Shift dialog (replaces deep-link to desk)
- **Symptom / motivation:** The Existing-Entry branch and the Shift Hours banner both deep-linked to `/app/pos-opening-entry/<name>` in a new tab when the user wanted to close the shift. User wanted feature parity with the opening dialog: a single in-POS UX, no jumping to the desk just to submit a closing entry.
- **Files added:**
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) — two new whitelisted endpoints:
    - `preview_pos_closing_entry(opening_entry)` — wraps ERPNext's `make_closing_entry_from_opening` (in `apps/erpnext/erpnext/accounts/doctype/pos_closing_entry/pos_closing_entry.py`) which already does the heavy lifting of querying invoices in the period and computing expected amounts per payment mode. Returns a slim dict shape: opening_entry, period_start_date, period_end_date, totals, and a `payments` array with `{mode_of_payment, opening_amount, expected_amount, closing_amount}`. The `make_` helper hard-codes `opening_amount=0`, so we override it from the opening entry's `balance_details` child table to keep the dialog's "opening / expected / counted / diff" math correct. `closing_amount` is pre-seeded with `expected_amount` so a one-click close (no edits) just works for the common "drawer matches" case.
    - `submit_pos_closing_entry(opening_entry, closing_amounts)` — accepts a JSON map of `{mode_of_payment: counted_amount}`, runs the same `make_closing_entry_from_opening` to build a fresh draft (no client trust on the totals), applies the user's counted values, computes the difference per row, then `insert()` + `submit()`. Errors propagate as ValidationError so the frontend's standard error pipeline picks them up.
  - [pos/src/lib/pos-closing-api.ts](pos/src/lib/pos-closing-api.ts) — new module with `previewClosingEntry(openingEntry)` and `submitClosingEntry(openingEntry, closingAmounts)` helpers + the `POSClosingPreview` and `POSClosingPaymentRow` types.
  - [pos/src/components/POSClosingDialog.tsx](pos/src/components/POSClosingDialog.tsx) — new dialog. State machine: `loading → form → submitting → success`, with an `error` state for the initial preview fetch failing. The form body shows three summary stat cards (invoice count, grand total, net total) above a payment-reconciliation table with one row per mode of payment: read-only opening + expected, editable counted (defaults to expected), and a live-computed colour-coded difference (green when over, red when short, gray when matched). Footer row sums the net difference. Header has Cancel and Close Shift buttons. On submit, the dialog briefly shows a success state ("Shift Closed — Closing Entry: POS-CLOSE-…") before the parent decides what to do (typically `window.location.reload()`).
- **Files changed:**
  - [pos/src/components/ShiftHoursBanner.tsx](pos/src/components/ShiftHoursBanner.tsx) — Close Shift button no longer opens a new tab. Instead it sets `showClosingDialog = true` and renders `<POSClosingDialog>` inline. On `onClosed`, the banner triggers a full page reload so the cleared shift state propagates everywhere.
  - [pos/src/components/POSOpeningDialog.tsx](pos/src/components/POSOpeningDialog.tsx) — the `existing-entry` branch's "Close Existing Entry" button now opens `POSClosingDialog` directly instead of deep-linking. On success, the dialog reloads so the opening flow restarts against a clean profile.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 649.30 kB → 657.09 kB.
  - `python3 -m py_compile ury/ury_pos/api.py` — OK.
  - **Still to do:** user reproduces the existing-entry collision, clicks Close Existing Entry, sees the new dialog with one row per mode (cash, card, etc.) showing opening + expected + editable counted + live diff, edits the counted values to mismatch deliberately, submits, sees the success flash, then sees the opening dialog reload cleanly so they can start a new shift. Same path via the Shift Hours banner: set `custom_shift_hours=1`, backdate the entry, wait for the orange banner, click Close Shift, complete the form.
- **Notes / follow-ups:**
  - **Both endpoints fully wrap ERPNext's `make_closing_entry_from_opening`** so we don't duplicate the invoice-totals query in URY code. If ERPNext changes the closing logic (taxes, returns, multi-currency), we automatically inherit it. The only thing we override is the hard-coded `opening_amount=0` because URY actually uses opening balances per mode of payment, which most ERPNext POS deployments don't.
  - **No client trust on the closing totals.** The frontend never sends grand_total / net_total / expected amounts back to the server — the backend rebuilds them from invoices on submit. The only client-supplied data is the closing_amount per mode of payment (i.e., what the cashier physically counted in the drawer). Backend recomputes diffs.
  - **Sub POS Closing flow** in [ury/ury/doctype/sub_pos_closing/sub_pos_closing.py](ury/ury/doctype/sub_pos_closing/sub_pos_closing.py) is unchanged. It's part of the deprecated multi-cashier captain model that round 2 of phase-1 dismantled. Eventually we'll either remove it or rebuild it on the new per-terminal model, but it's not in the way of anything right now.
  - **The dialog uses `formatCurrency` from `pos/src/lib/utils.ts`** for amount display. That helper currently uses the `currencySymbol` from localStorage which is set at app boot via `fetchCurrencySymbol`. As long as the user has loaded the POS at least once successfully, the symbol is correct.
  - **`submit_pos_closing_entry` is whitelisted with no role check.** Any user who can hit `/api/method/...` can submit a close on their own session. ERPNext's POS Closing Entry doctype permissions still apply (the user must have create permission on POS Closing Entry), so it's not a wide-open hole — but worth knowing.

### 2026-04-09 — Existing-Entry dialog branch + Shift Hours banner
- **Symptom:** After yesterday's per-terminal scoping shipped, the user logged in today and tried to open a new POS Opening Entry on Bar 1. The dialog showed `**Bar 1** is open. Close the POS or cancel the existing POS Opening Entry to create a new POS Opening Entry.` (with raw `<strong>` HTML rendering as asterisks). Two problems:
  1. **No way out from the dialog.** The error came from ERPNext's `check_open_pos_exists` which filters by `(pos_profile, status=Open)` and ignores terminal scoping entirely. Even with our new per-terminal logic on the URY side, ERPNext's standard validation refuses to create a second open entry for the same profile while another is still open. The dialog had no button to actually do anything about it — the user was stuck.
  2. **No prevention.** The reason the entry was still open was that nobody closed yesterday's shift. The user wanted a configurable shift length per POS Profile so the POS would prompt cashiers to close before this collision happens.
- **Root cause for collision:** ERPNext's [pos_opening_entry.py:64-71](apps/erpnext/erpnext/accounts/doctype/pos_opening_entry/pos_opening_entry.py#L64-L71) `check_open_pos_exists` is profile-scoped, not terminal-scoped. URY's per-terminal `posOpening()` correctly returned "no entry on this terminal" → dialog showed → user submitted → ERPNext rejected. The URY backend can't easily override ERPNext's validation since it lives in the parent app's `validate()` method, so the fix is on the frontend: detect this specific error and switch the dialog to a focused "Existing Open Entry" mode with a deep-link to the blocking entry.
- **Schema changes (Fix B):**
  - [ury/fixtures/custom_field.json](ury/fixtures/custom_field.json) + [ury/hooks.py](ury/hooks.py) — two new POS Profile fields: `custom_shift_hours` (Int, default 0 = disabled) and `custom_block_orders_after_shift_end` (Check, depends_on `custom_shift_hours > 0`).
- **Backend changes:**
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `getPosProfile()` — returns both new shift fields in the response so the frontend can configure the watcher.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) new `get_pos_open_entry(terminal=None)` whitelisted method. Returns `{name, period_start_date, posting_date, pos_profile, user}` for the currently-open entry, or None. Three lookup modes: (1) per-terminal + per-user (when multi_cashier ON), (2) per-terminal only (when multi_cashier OFF), (3) **fallback by `pos_profile` only** for when the per-terminal/user check finds nothing but ERPNext's profile-scoped check would still block — that's the case Fix A uses to find the blocking entry's name to deep-link to.
- **Frontend changes (Fix A — Existing Entry dialog branch):**
  - [pos/src/lib/pos-opening-api.ts](pos/src/lib/pos-opening-api.ts) — new `getCurrentPosOpenEntry(terminal?)` helper wrapping the new whitelisted method.
  - [pos/src/components/POSOpeningDialog.tsx](pos/src/components/POSOpeningDialog.tsx) — `OpeningMode` gets a new `existing-entry` variant with the blocking entry name + the parsed error message. The submit-handler catch block uses `extractFrappeServerError` (so the `<strong>` HTML is stripped automatically) and matches on `parsed.title === 'POS Opening Entry Exists'` OR a regex on the message body (defensive fallback in case the title is translated). When matched, it calls `getCurrentPosOpenEntry(terminalName)` to look up which entry is blocking and switches the dialog to the new mode. The render branch shows an orange "Existing Open Entry" card with the entry name + a primary button **Close Existing Entry** (deep-link to `/app/pos-opening-entry/<name>` in a new tab) + a secondary **I've Closed It — Reload** button.
- **Frontend changes (Fix B — Shift Hours banner):**
  - [pos/src/lib/pos-profile-api.ts](pos/src/lib/pos-profile-api.ts) — `PosProfileLimited` and `PosProfileCombined` types gain `custom_shift_hours` and `custom_block_orders_after_shift_end`. `getCombinedPosProfile` propagates both through the merge.
  - [pos/src/store/pos-store.ts](pos/src/store/pos-store.ts) — new state fields `shiftExpired: boolean` and `shiftBlocked: boolean`, new action `setShiftExpired(expired, blocked)`. The action no-ops when both flags already match the requested values to prevent re-renders from the 60-second poll timer.
  - [pos/src/components/ShiftHoursBanner.tsx](pos/src/components/ShiftHoursBanner.tsx) — new component. Reads `posProfile.custom_shift_hours` (returns null when 0). Polls `getCurrentPosOpenEntry(terminalName)` once a minute, parses the entry's `period_start_date` (Frappe local datetime → JS Date), computes elapsed hours, and sets the store flags when elapsed >= shift_hours. Renders a sticky orange banner at the top of the POS with a "Close Shift" deep-link button. When the profile's `custom_block_orders_after_shift_end` is enabled, the banner turns red and is non-dismissible (load-bearing UI). Otherwise the banner is dismissible per session via an X button.
  - [pos/src/components/POSOpeningProvider.tsx](pos/src/components/POSOpeningProvider.tsx) — mounts `<ShiftHoursBanner />` as a sibling to `children`, so the banner is visible across all POS routes whenever the user is past the opening dialog.
  - [pos/src/components/OrderPanel.tsx](pos/src/components/OrderPanel.tsx) — destructures `shiftBlocked` from the store, blocks `handleSubmit` with a friendly toast when true, and adds `shiftBlocked` to the `isInteractionDisabled` computed value so the order UI grays out cleanly when the hard-block flag is on.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 645.16 kB → 649.30 kB.
  - `python3 -m py_compile ury/ury_pos/api.py` — OK.
  - `json.load` on `custom_field.json` — OK.
  - **Still to do:** user runs `bench --site <site> migrate` to apply the two new POS Profile fields. Then walks the matrix: (a) hit the existing-entry collision (try to open while another is open) → see the new dialog branch with Close Existing Entry button; (b) set `custom_shift_hours=2`, leave `custom_block_orders_after_shift_end` off, open a fresh entry, fudge `period_start_date` 3h back via the desk → orange banner appears with Close Shift button; (c) flip `custom_block_orders_after_shift_end` on, repeat → banner turns red and is non-dismissible, OrderPanel submit is blocked with the friendly toast.
- **Notes / follow-ups:**
  - The banner polls every 60 seconds. For shift_hours=8, that means a worst-case ~1-minute delay between hitting the threshold and seeing the banner. Acceptable. For very short shift_hours values (testing) the delay is also 1 minute — bear that in mind during the test matrix.
  - The "block orders" hard block is a frontend-only check. If a malicious client bypassed it, the order would still go through on the backend. I'm leaving it as a soft trust check because the threat model here is "remind cashiers to close shifts", not "prevent unauthorized sales after hours". A hard backend block would need a similar guard in `sync_order` and is overkill for this feature.
  - ShiftHoursBanner's `parseFrappeDateTime` parses the entry's `period_start_date` as **local time**, not UTC. Frappe stores datetimes in the site's timezone without an offset suffix, so `new Date('2026-04-09T08:00:00')` parses as the browser's local time. As long as the POS device is in the same timezone as the Frappe site (the normal case), elapsed hours are correct. Cross-timezone setups would need a fix.
  - The existing-entry branch is reached via title-match `'POS Opening Entry Exists'` OR a regex on the message body. The regex is the fallback for translated installs; English installs always match the title.
  - **`custom_block_orders_after_shift_end` description includes `depends_on` `eval:doc.custom_shift_hours > 0`**, so the checkbox is hidden in the desk until shift hours are set. Cleaner admin UX.

### 2026-04-08 — POS Opening Entry per-terminal scoping (revamp phase 1, round 2)
- **Symptom / motivation:** After binding `URY POS Terminal` to `POS Profile` (round 1), opening entries were still branch-scoped. Two terminals on the same branch shared a single opening entry — the first to open "the branch" satisfied the open-check for everyone on every till at that branch. Wrong for independent cash drawers: Bar 1 and Restaurant A each have their own physical drawer and need their own opening balance + closing reconciliation. Phase 1 round 2 closes that loop.
- **Design decision (user confirmed):** scoping rules depend on the POS Profile's existing `custom_enable_multiple_cashier` flag.
  - **`multi_cashier` OFF (shared mode):** one POS Opening Entry per terminal per shift. The first user to arrive on a terminal opens it; everyone else who logs in onto that terminal just enters the POS without their own opening entry. Per-invoice attribution still happens via `POS Invoice.owner` (Frappe standard) and `POS Invoice.custom_terminal` (URY field added in round 1).
  - **`multi_cashier` ON (strict mode):** one POS Opening Entry per `(terminal, user)` per shift. Each user opens their own entry when they start their shift and closes their own when they leave. Used when management wants strict per-cashier shift accounting.
- **Schema changes:**
  - [ury/fixtures/custom_field.json](ury/fixtures/custom_field.json) + [ury/hooks.py](ury/hooks.py) fixtures — new `POS Opening Entry.custom_terminal` Link field (Link → URY POS Terminal, read-only, `in_list_view: 1` + `in_standard_filter: 1` so it shows in the desk list and filter bar). Mirrors the `POS Invoice.custom_terminal` field from round 1.
- **Backend changes:**
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `posOpening(terminal=None)` — new optional `terminal` parameter. When supplied, looks up the POS Profile from the terminal, reads `custom_enable_multiple_cashier`, and filters POS Opening Entry by `(custom_terminal, status, docstatus)` plus `user` if multi_cashier is ON. When omitted, falls back to the legacy branch-only check so the legacy Vue POS keeps working.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `validate_pos_close(pos_profile, terminal=None)` — same scoping. The "previous day not closed" check is now per-terminal (and per-user when multi_cashier is ON), so an unclosed entry on Bar 1 doesn't block the cashier on Restaurant A.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `getPosProfile()` multi_cashier branch — **massively simplified.** The old code did a SQL join through `Multiple Rooms` to figure out "who opened the captain's entry" and used that to set `cashier`/`owner`. The whole concept is gone now. New code just sets `cashier = owner = frappe.session.user`. Per-terminal scoping makes the room/captain lookup unnecessary. Also drops the dependency on `getBranchRoom()` from this code path, which was the source of the original "No room assigned to this user" landmine.
  - [ury/ury/hooks/ury_pos_opening_entry.py](ury/ury/hooks/ury_pos_opening_entry.py) — `main_pos_open_check` (captain-must-be-open gate) **DELETED**. New `validate_terminal_branch` hook verifies that a supplied `custom_terminal`'s branch matches the entry's branch (server-side trust check, mirrors the same check on URY POS Terminal save). `set_cashier_room` and `set_current_time` kept — they're harmless metadata stamping.
  - [ury/ury/hooks/ury_pos_closing_entry.py](ury/ury/hooks/ury_pos_closing_entry.py) — `sub_pos_close_check` (sub-cashier-must-close-first gate) **DELETED**. Captain/sub-cashier ordering is gone everywhere now. Comments left in both hook files explaining why, so future-me doesn't reintroduce the gates.
  - [ury/patches/v0_2/backfill_opening_entry_terminal.py](ury/patches/v0_2/backfill_opening_entry_terminal.py) + [ury/patches.txt](ury/patches.txt) — idempotent `[post_model_sync]` patch that backfills `custom_terminal` on existing POS Opening Entry rows. For each entry with no terminal: looks up `URY POS Terminal` rows matching `(branch, pos_profile, disabled=0)`. 1 candidate → stamp it. 0 → skip and log (admin must set manually). >1 → skip and log the candidates so admin can disambiguate. Defensive `frappe.db.has_column` guard.
- **Frontend changes:**
  - [pos/src/lib/pos-opening-api.ts](pos/src/lib/pos-opening-api.ts) — `checkPOSOpening(terminal?)`, `validatePOSClose(pos_profile, terminal?)`, and `CreatePOSOpeningPayload` gained an optional `custom_terminal` field. Comment on `createAndSubmitPOSOpening` updated to note that the captain gate is gone. `hasMainCashierOpened` marked `@deprecated` but kept in case the dialog's Join/Waiting branches are re-enabled for a future role-gated workflow.
  - [pos/src/components/POSOpeningProvider.tsx](pos/src/components/POSOpeningProvider.tsx) — pulls `terminalName` from the POS store and passes it to both `checkPOSOpening` and `validatePOSClose`.
  - [pos/src/components/POSOpeningDialog.tsx](pos/src/components/POSOpeningDialog.tsx) — pulls `terminalName` from the store, threads it through `OpeningBranchProps` to `OpeningBranch`, and includes `custom_terminal: terminalName` in the `createAndSubmitPOSOpening` payload (only when the terminal is set; the conditional spread keeps the payload clean otherwise). The Join Session / Waiting for Main Cashier branches are **left in place** per user's request — they're unreachable code paths under the new model but the UI stays ready in case a future role-gated "manager-must-open" workflow wants them.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 644.79 kB → 645.16 kB.
  - `python3 -m py_compile` on all four edited Python files + the new patch — OK.
  - `json.load` on `custom_field.json` — OK.
  - **Still to do:** user runs `bench --site <site> migrate` (runs the new patch), then walks the matrix: (a) shared mode (multi_cashier OFF), first user opens terminal → entry created with `custom_terminal` set; (b) second user logs in on the same terminal → enters POS without seeing the open dialog; (c) third user logs in on a DIFFERENT terminal on the same branch → sees the open dialog (NOT the first terminal's entry); (d) strict mode (multi_cashier ON), each of two users on the same terminal must open their own entry; (e) user closes the entry, second day login on same terminal shows the open dialog cleanly.
- **Notes / follow-ups:**
  - **Captain/sub-cashier deprecation is partial.** The `custom_main_cashier` checkbox on POS Profile User and the `custom_rooms` table on POS Opening Entry are still in the schema. The backend stops reading them. Sub POS Closing flow ([ury/ury/doctype/sub_pos_closing/sub_pos_closing.py](ury/ury/doctype/sub_pos_closing/sub_pos_closing.py)) and the closing-entry `calculate_closing_amount` hook still reference Sub POS Closing — those weren't touched in this round because they're a separate flow. They'll either need to be removed in a follow-up or kept around as a "legacy multi-cashier strict mode" that the new strict mode replaces.
  - **`getCashier(room)` SQL** in `ury_pos/api.py:538-556` still uses the old branch + room query. Only called from the legacy Vue POS (`urypos/src/stores/Table.js:148`), not from the React POS. Left unchanged for backward compat. Will become irrelevant when the legacy Vue POS is sunset (Dec 2025 per README).
  - **The backfill patch's "0 matches" branch silently skips** — meaning an existing opening entry on a branch without any terminals stays unstamped. It still shows up in the desk; only the new `posOpening(terminal=...)` check treats it as not-found. Acceptable because the admin will see "Please Open POS Entry" the next time they try to load the POS, and they can either re-stamp the entry manually or close it and open a new one through the dialog.
  - **The `OpeningBranch.tsx` sub-cashier branches are dead code** under the new model. They don't fire because `mainCashierUser` resolution depends on `posProfile.applicable_for_users[].custom_main_cashier` which is no longer the source of truth. Per user's instruction we kept them in case they're useful for a future "manager-must-open" gate. Don't be alarmed by the unreachable paths.

### 2026-04-08 — "Set Price in Menu" button invisible on the Price Not Set toast
- **Symptom:** After the previous round shipped the rich Price Not Set toast with a role-gated action button, a user logged in as `URY Captain` + `URY Manager` + `System Manager` still didn't see the button on the toast. Cashiers correctly didn't see it. Admin correctly saw it. Captain/manager didn't — looked like a role check bug.
- **Investigation:** Added a one-shot diagnostic `console.log({userName, userRoles, canEdit, ...})` in the `Price Not Set` branch of `OrderPanel.tsx`. On reproduction, console showed: `userRoles: Array(44)` containing `['... System Manager, URY Cashier, URY Manager, URY Captain]`, `canEdit: true`. So `canManageMenuPrices` was returning true correctly and `content.action` was being passed to `showToast.error` correctly — the button was in the React tree, it just wasn't visible to the eye.
- **Root cause:** The button's Tailwind classes were `bg-white/20 hover:bg-white/30 text-white`. That assumes the react-toastify `colored` theme's dark-red background for error toasts, which is the default when you pass `theme: 'colored'`. **But [pos/src/components/ui/toast.css](pos/src/components/ui/toast.css) overrides the colored theme with pastel backgrounds** (`#fef2f2` for error, `#ecfdf5` for success, `#eff6ff` for info) via `!important` rules — that's the URY house style. Against a pale-pink background with white text, the button was effectively invisible. White text on almost-white background. It was in the DOM the entire time; you just couldn't see it.
- **Files changed:**
  - [pos/src/components/ui/toast.tsx](pos/src/components/ui/toast.tsx) — button styles switched from white-on-dark (`bg-white/20 text-white`) to `currentColor`-aware inline styles: `backgroundColor: rgba(0,0,0,0.08)`, `border: 1px solid rgba(0,0,0,0.2)`, `color: currentColor`. The dark-overlay background is visible on every pastel toast variant; the currentColor text picks up whatever foreground the toast type set (dark red on error, dark green on success, dark blue on info) so the button label is always readable. Inline hover handlers bump the overlay to `rgba(0,0,0,0.16)` — couldn't use Tailwind's `hover:` prefix cleanly because we're on inline styles. Added a long source comment explaining the trap so future-me doesn't re-ship the same button and wonder why it's invisible again.
  - [pos/src/components/OrderPanel.tsx](pos/src/components/OrderPanel.tsx) — removed the one-shot `[URY diagnostic]` console.log that we used to identify the bug. `canEdit: true` in the probe output proved the role logic was correct, which scoped the fix to visual rendering only.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle rebuilt.
  - **Still to do:** user walks Case A / Case E one more time (zero-rate Sprite as captain → button VISIBLE now; zero-rate Sprite as cashier → button still hidden).
- **Notes / follow-ups:**
  - **Lesson:** Any time a component uses the `showToast.error/success/info` rich-content mode with an action button, check that the button's colours work against URY's pastel backgrounds, NOT against react-toastify's default dark "colored" theme. The default theme is overridden by [toast.css](pos/src/components/ui/toast.css) with `!important`, which is load-bearing for the URY brand look but traps anyone writing new toast content that assumes dark backgrounds.
  - The diagnostic `console.log` shipped briefly in `index-BnqyBqR5.js`. Removed in the same commit as the fix so production users never see it.
  - If we ever add a third toast variant (warning, neutral) with a different pastel background, the `currentColor`-based button will still work because it only depends on the foreground colour being dark — which every pastel toast already enforces for legibility.

### 2026-04-08 — "Sales Invoice mode is activated" blocker + sync_order error-wrapping cleanup
- **Symptom:** After the previous round's menu/toast fixes shipped, user still couldn't submit orders. DevTools Response showed three stacked `_server_messages`: (1) the old "Item Price added for <a>Fanta</a>..." side-effect alert (still firing because the menu hadn't been re-saved after the UOM fix), (2) the real `ValidationError` `"Sales Invoice mode is activated in POS. Please create Sales Invoice instead."`, and (3) `"Error while updating order: Sales Invoice mode is activated..."` — a duplicate wrapper of message 2.
- **Root causes:**
  1. **`POS Settings.invoice_type = "Sales Invoice"`** on the site. ERPNext's `POSInvoice.validate_is_pos_using_sales_invoice()` ([apps/erpnext/erpnext/accounts/doctype/pos_invoice/pos_invoice.py:466-469](apps/erpnext/erpnext/accounts/doctype/pos_invoice/pos_invoice.py#L466-L469)) rejects any POS Invoice save when that singleton is in Sales Invoice mode. URY is architecturally incompatible with that mode — it creates POS Invoices directly. **This setting had to be flipped to "POS Invoice" manually the first time**, and the failure mode was a confusing stack of server messages because of Root Cause 2.
  2. **`sync_order` wrapped `invoice.save()` in `try/except` and re-threw.** The legacy code was `try: invoice.save() except Exception as e: frappe.throw(f"Error while updating order: {e}")` — which caught ERPNext's well-formed ValidationError, stripped its title, stripped its indicator, prefixed the message with "Error while updating order:", and re-threw as a plain ValidationError with the stringified original. The frontend `extractFrappeServerError` then had to choose between the original (message 2) and the wrapper (message 3) and ended up showing the noisier one. Removing the wrapper lets ERPNext's errors propagate cleanly — they already have all the metadata the frontend needs.
- **Files changed:**
  - [ury/ury/doctype/ury_order/ury_order.py](ury/ury/doctype/ury_order/ury_order.py) — deleted the `try/except` around `invoice.save()`. ValidationErrors now propagate unwrapped.
  - [ury/install.py](ury/install.py) — new `ensure_pos_settings_configured()` function that auto-sets `POS Settings.invoice_type = "POS Invoice"` if it isn't already. Called from both `after_install` (for fresh installs) and a new `after_migrate` (for existing installs — every `bench migrate` brings drifted sites back into a working state). Logs a yellow `[URY]` line when a correction is applied, or a red warning if the set fails for any reason (permissions, missing DocType, etc.) — either way it doesn't crash install or migrate.
  - [ury/hooks.py](ury/hooks.py) — uncommented `after_install` and added `after_migrate`, both pointing at `ury.install`. Note: `after_install` was commented out before this round, which means `ury.install.after_install` (the `setup()` call) was never actually running. Bundling the rewire with the new POS Settings guard so upgrades get both in one go.
  - [CLAUDE.md](CLAUDE.md) — added a Gotchas entry documenting the `POS Settings.invoice_type` dependency, plus this Fixes log entry.
- **Verification:**
  - `python3 -m py_compile` on `install.py`, `hooks.py`, `ury_order.py` — OK.
  - No React frontend changes this round — bundle not rebuilt.
  - **User pre-verified in the browser:** flipped `POS Settings.invoice_type` to "POS Invoice" manually + ran `bench migrate` + re-saved the URY Menu → order submission worked cleanly. This round just codifies that manual fix so future installs don't hit the same wall.
- **Notes / follow-ups:**
  - **Because `after_install` was previously commented out, `setup()` (the `create_custom_fields` call in [ury/setup.py](ury/setup.py)) was never running on `after_install`.** That means URY installs relied entirely on the `fixtures` list in hooks.py to create those custom fields. The wire-up here restores the intended behaviour but it's a latent behaviour change worth flagging if any existing site starts seeing duplicate or re-created custom fields on their next migrate. The `create_custom_fields` function is idempotent so there shouldn't be damage, but keep an eye on it.
  - The `try/except` that silently swallows `setup()` failures in `install.py` is kept as-is — I don't want to surface latent install errors from someone else's 3-year-old code in the middle of a permissions-revamp session. That's its own cleanup pass.
  - No `sync_order` callers relied on the "Error while updating order:" prefix. Grep confirmed.

### 2026-04-08 — "Item Price added for <a>...</a>" noise toast + Price Not Set rich error
- **Symptom:** After tapping a menu item (Fanta) and hitting Submit, the POS showed a toast containing raw HTML: `tem Price added for <a href="http://.../desk/item/Fanta" rel="noopener noreferrer">Fanta</a> in Price List S...`. The user wanted a cleaner notification and specifically a way to set the price from the POS.
- **Root cause (three stacked bugs):**
  1. **UOM missing on menu-synced Item Prices.** `URYMenu.make_price_list` in [ury/ury/doctype/ury_menu/ury_menu.py](ury/ury/doctype/ury_menu/ury_menu.py#L36-L46) was creating Item Price rows without setting `uom`. ERPNext's standard POS Invoice validation in `erpnext/stock/get_item_details.py:insert_item_price()` filters Item Price lookups by `uom = item.stock_uom` — so it couldn't match the URY-created row, fell through to the "auto-insert missing price" branch (Stock Settings `auto_insert_price_list_rate_if_missing` defaults to on), created a *second* duplicate Item Price, and fired `frappe.msgprint("Item Price added for <a href='...'>Fanta</a> in Price List ...", alert=True)` on **every** POS submission.
  2. **OrderPanel picked the wrong `_server_messages` entry.** [pos/src/components/OrderPanel.tsx](pos/src/components/OrderPanel.tsx) read `JSON.parse(messages[0])` — always the first entry. When the response carried BOTH ERPNext's side-effect alert AND the real ValidationError, the user saw the alert. Classic "first in the array" trap — Frappe's convention is to mark the thrown error with `raise_exception: 1`, so consumers should look for that flag, not blindly grab index zero.
  3. **Toast rendered HTML as plain text.** react-toastify's string mode doesn't strip tags, so `<a href="...">Fanta</a>` showed up literally in the toast. Even after fixing which message to pick, any legit message with a desk link would have looked broken.
- **Files changed:**
  - [ury/ury/doctype/ury_menu/ury_menu.py](ury/ury/doctype/ury_menu/ury_menu.py) — `make_price_list` now reads `Item.stock_uom` and stamps it on every Item Price it inserts. Kills the ERPNext auto-insert path at the root.
  - [ury/patches/v0_2/backfill_item_price_uom.py](ury/patches/v0_2/backfill_item_price_uom.py) + [ury/patches.txt](ury/patches.txt) — idempotent `[post_model_sync]` patch that walks all menu-linked Price Lists (`Price List.restaurant_menu IS NOT NULL`) and backfills `uom` on any Item Price rows where it's null. Defensive `frappe.db.has_column` guard. Runs after the terminal backfill. Safe to re-run.
  - [ury/ury/doctype/ury_order/ury_order.py](ury/ury/doctype/ury_order/ury_order.py) — `sync_order` now throws `title="Price Not Set"` with a clean sentence naming the item AND the menu (ExPOS Menu via translation), covering BOTH "no Item Price row" AND "row exists but rate is 0/null". Previously the "no row" case threw a terse `"No item price found for Item X in Price List Y"` and the "zero rate" case silently stamped a zero-rate line onto the invoice.
  - [pos/src/lib/utils.ts](pos/src/lib/utils.ts) — new `parseFrappeServerMessages()` + `extractFrappeServerError()` helpers. The extractor walks the full `_server_messages` array, prefers the entry with `raise_exception: 1`, falls back to the last entry, then `err.message`, then a caller-supplied fallback. Strips HTML tags from the final string so `<a>` etc. render as plain text. Returns `{title, message, raw}` so callers can switch on the title (e.g. "Price Not Set" → rich toast).
  - [pos/src/lib/role-utils.ts](pos/src/lib/role-utils.ts) — new `canManageMenuPrices(user)` helper. Returns true for `Administrator`, `System Manager`, `URY Manager`, `URY Captain`. Gates the "Set Price in Menu" action button in the Price Not Set toast so cashiers don't see a button they can't use.
  - [pos/src/components/ui/toast.tsx](pos/src/components/ui/toast.tsx) — `showToast.error/success/info` now accept either a `string` (legacy shorthand, unchanged behaviour) or a `RichToastContent` object `{title, description?, action?: {label, onClick}}`. A rich toast with an action auto-closes after 8 s instead of 2 s and disables closeOnClick so the user has time to hit the button. Action button is rendered inside the toast card with an ExternalLink icon.
  - [pos/src/components/OrderPanel.tsx](pos/src/components/OrderPanel.tsx) — submit-handler's catch block now uses `extractFrappeServerError()`. When the parsed title is `"Price Not Set"`, shows a rich toast with title "Price Not Set", description = the server sentence, and an action `"Set Price in Menu"` that opens `/app/ury-menu` in a new tab — **only** for users where `canManageMenuPrices(user)` returns true. All other errors render as plain-text toasts with the parsed message.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 643.10 kB → 644.79 kB.
  - `python3 -m py_compile` on both edited Python files + new patch — OK.
  - **Still to do:** user runs `bench migrate` (runs the backfill), then tests the three freshinstall states: (a) item with no Item Price row at all → rich Price Not Set toast, action button visible for admin/captain/manager, hidden for cashier; (b) item with rate 0 → same toast; (c) menu saved with a rate → resync creates Item Price rows WITH `uom` set; (d) submit an order → no "Item Price added for <a>..." noise toast appears anymore.
- **Notes / follow-ups:**
  - The `extractFrappeServerError` helper should replace the ad-hoc `_server_messages` parsers scattered across `config-slice.ts`, `App.tsx`, `menu-api.ts`, `aggregator-api.ts`, `customer-api.ts`, `POSOpeningDialog.tsx`. **Not touching those in this round** to keep scope tight, but the next time any of them misbehave, migrate them to the helper instead of adding a sixth copy of the parser.
  - The "Set Price in Menu" action deep-links to `/app/ury-menu` (the list view), not a specific menu record. The list is usually short enough that one click lands the admin on the right menu. A more precise deep-link would need the menu name in the frontend payload — punt to phase 2 if desired.
  - **Role list for `canManageMenuPrices`:** user asked for "administrator and captain". I included `URY Manager` + `System Manager` as well because (a) `URY Manager` already has write access on URY Menu via DocType permissions, and (b) `System Manager` is Frappe's framework god-role and will always need access. If the user wants a stricter list (Administrator + URY Captain only), trim the `allowed` array in `role-utils.ts`. Flagged in the commit message.
  - **Rate is still optional on the URY Menu Item DocType JSON.** Per user's request we enforce at order time instead of schema time. Admins can save work-in-progress menus without getting blocked.

### 2026-04-08 — URY POS Terminal ↔ POS Profile binding (revamp phase 1, round 1)
- **Symptom / motivation:** The React POS never showed the cashier *which* POS Profile they were ringing in. There was no way to run multiple terminals per branch (Bar 1, Bar 2, Restaurant A) with different menus/printers/payment modes because `getPosProfile()` picked the profile purely by branch (`frappe.db.exists("POS Profile", {"branch": branch_name})` — undefined behaviour when multiple profiles existed on the same branch). POS Invoices had no terminal link so "which till sold this" reporting was impossible.
- **Design decision (user confirmed):** `URY POS Terminal` becomes the single source of truth for per-device configuration. Each terminal is linked to exactly one `POS Profile`, and the React POS sends the registered terminal name on every profile-resolution call. Multi-terminal-per-branch is now first-class.
- **Schema changes:**
  - [ury/ury/doctype/ury_pos_terminal/ury_pos_terminal.json](ury/ury/doctype/ury_pos_terminal/ury_pos_terminal.json) — new required `pos_profile` Link field (Link → POS Profile). This is a native URY DocType field (not a Custom Field), so it lives directly in the DocType JSON, not in `custom_field.json`.
  - [ury/fixtures/custom_field.json](ury/fixtures/custom_field.json) — new `POS Invoice.custom_terminal` Link field (Link → URY POS Terminal, read-only, stamped on invoice creation, `in_standard_filter: 1` so it shows in the desk list view's filter bar for reporting). Registered in [ury/hooks.py](ury/hooks.py) fixtures list.
  - [ury/translations/en.csv](ury/translations/en.csv) — added `URY POS Terminal → ExPOS POS Terminal` so backend error titles/messages rebrand consistently.
- **Backend changes:**
  - [ury/ury/doctype/ury_pos_terminal/ury_pos_terminal.py](ury/ury/doctype/ury_pos_terminal/ury_pos_terminal.py) `validate()` now enforces that the linked POS Profile's branch matches the terminal's branch. Cross-branch binding is a config error and is rejected with a branded "Branch Mismatch" title.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `get_terminal_config()` now returns `pos_profile` and hard-errors with "Terminal Not Configured" if the terminal has no profile set. `get_terminals()` returns `pos_profile` too so the setup screen can flag unconfigured terminals.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `getPosProfile(terminal=None)` — new optional `terminal` parameter. When supplied, resolves the profile from `URY POS Terminal.pos_profile` (deterministic, branch-disambiguated). When absent, falls back to the historical "first POS Profile for this branch" behaviour so legacy Vue POS and Administrator callers don't break. Added a clean "POS Profile Not Configured" error if neither path finds a profile. The response echoes the `terminal` back so the frontend store has a single source of truth.
  - [ury/ury/doctype/ury_order/ury_order.py](ury/ury/doctype/ury_order/ury_order.py) `sync_order(..., terminal=None)` — new optional `terminal` parameter. When set and the terminal's branch matches the invoice's branch (server-side verification, never trust the client blindly), stamps `invoice.custom_terminal`. A terminal from a different branch is silently ignored rather than throwing — the invoice still saves, just without a terminal stamp.
  - [ury/patches/v0_2/backfill_terminal_pos_profile.py](ury/patches/v0_2/backfill_terminal_pos_profile.py) + [ury/patches.txt](ury/patches.txt) — idempotent migration patch that backfills `URY POS Terminal.pos_profile` on existing installs. If the terminal's branch has exactly one non-disabled POS Profile, copy it. If zero → skip (admin gets "Terminal Not Configured" error and fixes it manually). If multiple → skip and log the candidates so the admin disambiguates. Runs on `bench migrate`. Safe to re-run. The v0_2 subdirectory establishes the versioned patch folder convention for URY — use it for any future schema migrations. **Patch MUST be listed under `[post_model_sync]` in `patches.txt`** — it reads a column (`pos_profile`) that only exists after Frappe syncs the DocType JSON during migration. Initial attempt without the section header crashed with `Unknown column 'pos_profile' in 'SELECT'` because un-sectioned patches default to `[pre_model_sync]` which runs before model sync. The patch also has a defensive `frappe.db.has_column` guard that logs and returns if the column is absent for any reason, so a mis-ordered patches.txt is a noisy no-op rather than a fatal crash.
- **Frontend changes:**
  - [pos/src/lib/terminal-api.ts](pos/src/lib/terminal-api.ts) — `TerminalConfig` now carries optional `pos_profile`. Required on the single-config endpoint; may be empty on the list endpoint (unconfigured terminals).
  - [pos/src/lib/pos-profile-api.ts](pos/src/lib/pos-profile-api.ts) — `getPosProfileLimitedFields` / `getCombinedPosProfile` accept an optional `terminal` argument and send it to the backend. `PosProfileLimited` gained an optional `terminal` field that mirrors the server's echo.
  - [pos/src/store/slices/config-slice.ts](pos/src/store/slices/config-slice.ts) — `fetchPosProfile` reads the device's saved terminal (via `getSavedTerminal()` from localStorage, same source of truth `App.tsx` uses) and passes it through so the AuthGuard-path profile fetch resolves deterministically too.
  - [pos/src/store/pos-store.ts](pos/src/store/pos-store.ts) — new store fields `terminalBranch` and `terminalPosProfile`, populated by `setTerminalConfig`. The pos-store's `fetchPosProfile` now reads `get().terminalName` and passes it. `OrderPanel.tsx` pulls `terminalName` from the store and includes `terminal` in the `syncOrder` payload.
  - [pos/src/lib/order-api.ts](pos/src/lib/order-api.ts) — `SyncOrderRequest` gained an optional `terminal` field.
  - [pos/src/components/Header.tsx](pos/src/components/Header.tsx) — new "terminal · branch · profile" chip next to the logo. Click/hover surfaces the terminal description via the `title` attribute. User menu dropdown also shows the POS Profile name and terminal description explicitly.
  - [pos/src/App.tsx](pos/src/App.tsx) — terminal setup screen shows the POS Profile per terminal and **disables** (non-clickable, reduced opacity, red "Not configured — no POS Profile linked" warning) any terminal that isn't bound to a POS Profile. Prevents the admin from registering a device to a broken terminal config.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 641.56 kB → 643.10 kB.
  - `python3 -m py_compile` on all four edited Python files + the new patch — OK.
  - `json.load` round-trip on `custom_field.json` and the `URY POS Terminal` DocType JSON — OK.
  - **Still to do:** user runs `bench --site <site> migrate` to apply the new field + patch, then tests the full matrix: (a) create a URY POS Terminal without a POS Profile → setup screen shows it disabled with the "Not configured" warning; (b) set the POS Profile → terminal becomes selectable; (c) pick the terminal → POS loads the correct profile; (d) Header chip shows "terminal · branch · profile"; (e) create a POS invoice → open it in the desk and confirm `custom_terminal` is set; (f) create a **second** POS Profile on the same branch and a **second** terminal bound to it → register the second terminal and confirm the POS loads the second profile.
- **Notes / follow-ups:**
  - **`POS Opening Entry` is still branch-scoped**, not per-terminal. Round 2 (deferred) will add `custom_ury_terminal` to POS Opening Entry and make `posOpening` / `validate_pos_close` per-terminal. Until then, two terminals on the same branch share a single opening entry — which is wrong for independent tills but not an immediate blocker because the invoice *stamping* is correct.
  - **Multi-cashier "captain" mode is still branch-wide**, not per-terminal. Same round 2 item.
  - **Trust model on `custom_terminal` stamping:** the server verifies that the frontend-supplied terminal belongs to the same branch as the resolved POS Invoice before stamping. A malicious client can't stamp "Accra - Bar 1" on a Tamale invoice — it would silently drop to unstamped. This matches the spirit of "phase 1 loosens restrictions but doesn't open auth holes".
  - **The "one POS Profile per branch" assumption is NOT fully gone from the codebase.** Several `getBranch` + `POS Profile where branch = X` lookups in `api.py` and the doc-event hooks still assume it. They'll continue to work correctly as long as each terminal's POS Profile uniquely identifies itself (which it does by name). Removing the assumption entirely is a round-2 sweep.
  - **Brand convention followed:** `URY POS Terminal` stays as the literal DocType name / Python class / URL slug / file path. Only labels rebrand through `en.csv`. Frontend user-facing strings say "ExPOS POS Terminal".

### 2026-04-08 — Fresh-install "Failed to load menu items" (417 EXPECTATION FAILED) + initializeApp swallowing errors
- **Symptom:** On a fresh install with no URY Restaurant / URY Menu / URY Menu Items created yet, opening `/pos` showed "Failed to load POS / Failed to load menu items / Retry". Network tab showed `GET getRestaurantMenu ... 417 EXPECTATION FAILED`. Even when the real server message was something actionable like "Please set an active menu for Restaurant None", the frontend displayed only the generic "Failed to load menu items" string.
- **Root cause (three layers):**
  1. [ury/ury_pos/api.py](ury/ury_pos/api.py) `getRestaurantMenu` assumed a URY Restaurant existed for the branch. When `frappe.db.get_value("URY Restaurant", {"branch": branch_name}, "name")` returned `None`, every downstream lookup also returned `None` and the final throw formatted as "Please set an active menu for Restaurant None" — confusing because the restaurant itself was missing, not just the menu.
  2. [pos/src/store/pos-store.ts](pos/src/store/pos-store.ts) `fetchMenuItems` caught the error and replaced it with the hardcoded string `'Failed to load menu items'`, even though [pos/src/lib/menu-api.ts](pos/src/lib/menu-api.ts#L37-L42) had already parsed `_server_messages` into `new Error(serverMessage)`. The friendly text was there — the store just discarded it.
  3. `initializeApp()` used `Promise.allSettled` and, on any rejection, **overwrote** whatever error its child actions had set with a fresh `'Failed to initialize app. Please refresh the page.'` string. So even if layer 2 had been fixed, the user would still see the generic wrapper message. (Also the top-level `try/catch` around `allSettled` was dead — `allSettled` never rejects.)
- **Files changed:**
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `getRestaurantMenu()` — two distinct early-guard errors with `title` set: "Restaurant Not Configured" when no URY Restaurant exists for the branch (tells the user to open "URY Restaurant" in the desk and create a record), "Active Menu Not Set" when the restaurant exists but `active_menu` is unset. Crucially, an empty menu (menu exists but has zero `URY Menu Item` children) is **not an error** — the function returns `items: []` successfully so the POS can render a dedicated empty state with a deep-link to add items.
  - [pos/src/store/pos-store.ts](pos/src/store/pos-store.ts) `fetchMenuItems` — catch block now uses `(error as Error)?.message` so the friendly message from `menu-api.ts` reaches the user. Fallback to the old string only if `message` is genuinely empty.
  - [pos/src/store/pos-store.ts](pos/src/store/pos-store.ts) `initializeApp` — no longer overwrites child errors. Each child action (`fetchPosProfile`, `fetchMenuItems`, `fetchCategories`, `fetchPaymentModes`) sets its own specific `error` on failure; `initializeApp` just awaits `Promise.allSettled` and lets whatever child message stuck take precedence. Removed the dead top-level `try/catch` since `allSettled` never rejects (kept a defensive outer try for unexpected sync errors but it now preserves the original message if any).
  - [pos/src/components/MenuList.tsx](pos/src/components/MenuList.tsx) — distinguishes two empty cases. When the underlying `menuItems` array is genuinely empty (no items at all — fresh install or admin who hasn't added items) the component shows a friendly "No menu items yet" message with an **Add Menu Items** button that opens `/app/ury-menu-item/new` in a new tab. The existing "No items found / Try adjusting your filters" branch is preserved for the case where items exist but filters exclude them all.
  - [pos/src/pages/POS.tsx](pos/src/pages/POS.tsx) — removed a duplicate `if (error) { return ... }` block that was dead code (the first `if (error)` already returned, so the second one was unreachable).
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 641.31 kB → 641.55 kB.
  - `python3 -m py_compile ury/ury_pos/api.py` — OK.
  - **Still to do:** user walks the three freshinstall stages in his browser: (a) no URY Restaurant exists → "Restaurant Not Configured" error; (b) URY Restaurant exists, no Active Menu → "Active Menu Not Set" error; (c) active menu set, no items → POS loads with "No menu items yet" empty state and the "Add Menu Items" button; (d) items exist → normal POS grid.
- **Notes / follow-ups:**
  - The pattern "child action sets specific error, parent orchestrator preserves it" is now the rule for this store. If a new child action is added to `initializeApp`'s `Promise.allSettled`, make sure it sets a user-actionable error on its own failure path — the wrapper will not do it for you anymore.
  - The "Add Menu Items" deep-link goes to the create form with `disabled=0` prefilled. If the user needs to create the parent URY Menu first, the Frappe form will surface that requirement. Phase-2 could add a full setup wizard, but this deep-link unblocks a fresh install with minimal UI effort.
  - `menu-api.ts` was already parsing `_server_messages` correctly — this round's fix was entirely about not discarding the parsed message further up the chain. Worth remembering: frappe-js-sdk throws an object with `_server_messages` on it, and there's already a parser for that in `menu-api.ts`, `pos-opening-api.ts` style — reuse that pattern before writing new parsers.
  - **Brand:** The new error strings use `_("URY Restaurant")` wrapped inside the sentence via `.format()` so the en.csv rebrand (`URY Restaurant → ExPOS Restaurant`) applies at runtime. Frontend hardcodes "ExPOS Menu Item" directly. See the "Brand naming" section above for the full convention. Also added `URY Menu Item, ExPOS Menu Item,` to [ury/translations/en.csv](ury/translations/en.csv) so any future backend message referencing it gets rebranded for free.

### 2026-04-08 — Multi-cashier mode crashed POS load via `getBranchRoom()`
- **Symptom:** Enabling `custom_enable_multiple_cashier` on the POS Profile made `/pos` show a generic "Access Denied / There was an error" screen for regular cashiers. Browser Network tab on `getPosProfile` showed `frappe.exceptions.ValidationError: No room assigned to this user. Please contact your administrator.` with the error originating in `ury_pos/api.py:getBranchRoom` line 157.
- **Root cause (two layers):**
  1. **`getBranchRoom()`** treated the `room` field on `URY User` as required and hard-threw `frappe.throw("No room assigned to this user...")` whenever a cashier's URY User row had no room. The schema in [ury/ury/doctype/ury_user/ury_user.json](ury/ury/doctype/ury_user/ury_user.json) has `room` as optional, so this was a mismatch between schema and runtime behaviour. Administrator had the same fall-through-to-`None` bug as the `getBranch()` fix from the previous session. The function is only called in the `getPosProfile()` multi-cashier branch, which is why non-multi-cashier POS worked fine.
  2. **Frontend error display** in [pos/src/store/slices/config-slice.ts](pos/src/store/slices/config-slice.ts) `fetchPosProfile()` was setting `error: (error as Error).message`, which for `frappe-js-sdk` errors is the HTTP status phrase, not the server's `_server_messages`. That's why the user saw "There was an error." instead of the friendly "No room assigned..." — the real message was in the response body but we were throwing it away.
- **Files changed:**
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `getBranchRoom()` — rewritten with: (a) Administrator fallback using first non-disabled POS Profile's branch + first URY Room in that branch; (b) friendly error when the user has no URY User row at all ("Ask your administrator to add you to a Branch's URY Users list"); (c) graceful empty-room fallback — if the URY User row has no room, silently pick the first URY Room in the user's branch, or pass `room=None` downstream if the branch has zero rooms. No more hard-throws on missing room. The caller (`getPosProfile`) handles an empty `pos_opening_list` without crashing.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) `getRoom()` — same Administrator fallback + same friendly error for missing URY User row. `getRoom()` is only called by the legacy Vue POS today, but fixing it now keeps the three sibling functions (`getBranch`, `getBranchRoom`, `getRoom`) consistent so no one has to relearn the trap.
  - [pos/src/store/slices/config-slice.ts](pos/src/store/slices/config-slice.ts) — added `extractFrappeErrorMessage()` helper that parses `_server_messages` (JSON-encoded array of JSON-encoded objects — Frappe's standard error envelope) and falls back to `err.message` or a static default. Used by `fetchPosProfile`'s catch block so the `AuthGuard` "Access Denied" screen now shows the real reason.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle 641.02 kB → 641.31 kB.
  - `python3 -m py_compile ury/ury_pos/api.py` — OK.
  - **Still to do:** user re-enables `custom_enable_multiple_cashier` on the POS Profile, restarts bench web, hard-reloads `/pos`, and walks the 5-item matrix again — specifically including the multi-cashier main-cashier and sub-cashier paths that now hit `getBranchRoom()`.
- **Notes / follow-ups:**
  - The "silently fall back to first room in branch" behaviour means a cashier whose URY User row lacks a room will be implicitly assigned to whatever room comes first in that branch. In multi-cashier mode this affects which `POS Opening Entry` they're matched against. **This is a deliberate loosening per the phase-1 direction** — hard-throwing was worse. Phase-2 permission redesign should probably make room assignment explicit at login.
  - `extractFrappeErrorMessage` is a local helper in `config-slice.ts`. If a third call site needs the same parsing, move it to `pos/src/lib/utils.ts`.
  - All three Administrator fall-through bugs from the initial audit (`getBranch`, `getBranchRoom`, `getRoom`) are now fixed. No known remaining Administrator fall-through bugs in `ury_pos/api.py`.

### 2026-04-08 — In-POS "Open POS Entry" dialog (replaces "Switch to Desk" dead-end)
- **Symptom:** When no POS Opening Entry was open for the branch, `/pos` showed a dead-end modal with "Reload Page" + "Switch to Desk". Users had to leave the app, navigate to `POS Opening Entry` in the Frappe desk, create and submit an entry by hand, and come back. Multi-cashier "captain" mode was especially confusing — sub-cashiers got cryptic "Main Cashier POS must be open" errors with no guidance.
- **Root cause:** [pos/src/components/POSOpeningDialog.tsx](pos/src/components/POSOpeningDialog.tsx) only rendered two buttons with no in-POS opening flow. The legacy Vue POS ([urypos/src/components/posOpening.vue](urypos/src/components/posOpening.vue)) already had this form — it was a React-POS regression.
- **Files changed:**
  - [pos/src/components/POSOpeningDialog.tsx](pos/src/components/POSOpeningDialog.tsx) — rewritten as a branching dialog: main cashier (or non-multi-cashier) sees a form with one input per mode of payment; sub-cashier in multi-cashier mode sees either a one-click "Join Session" button (if the captain has opened) or a "Waiting for Main Cashier" screen (if not). Closing-issue branch now has "Close Previous Session" that deep-links to the specific unclosed entry's form instead of dumping the user on `/app`. Success state shows a brief "POS Opened — Loading menu…" flash before the provider reloads.
  - [pos/src/components/POSOpeningProvider.tsx](pos/src/components/POSOpeningProvider.tsx) — now carries `unclosedEntry` alongside the validation type, handles both the new `{status, unclosed_entry}` response shape and the legacy string response for forward compatibility, and triggers `window.location.reload()` on dialog success (the dialog `sessionStorage.clear()`s first so cached menus/payment modes/POS Profile all refetch — this is the deliberate cache-busting strategy for "someone added items on the desk right before open").
  - [pos/src/lib/pos-opening-api.ts](pos/src/lib/pos-opening-api.ts) — added `getOpeningBalanceDetails`, `createAndSubmitPOSOpening` (createDoc → updateDoc(docstatus:1), mirroring the legacy Vue flow), and `hasMainCashierOpened`. Updated `POSCloseValidationResponse` type to accept both the new object shape and the old string.
  - [pos/src/lib/pos-profile-api.ts](pos/src/lib/pos-profile-api.ts) — added `PosProfileUser` and `PosProfilePayment` types and extended `PosProfileFull` with `applicable_for_users`, `payments`, and `custom_enable_multiple_cashier` so the dialog can detect the captain without extra API calls.
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) — `validate_pos_close()` now returns `{"status": "...", "unclosed_entry": "..."}` instead of a bare "Success"/"Failed" string so the frontend can deep-link to the unclosed entry.
- **Verification:**
  - `yarn build` in `pos/` — clean, bundle grew from 633.91 kB → 641.02 kB (form + state machinery, expected).
  - `python3 -m py_compile ury/ury_pos/api.py` — OK.
  - **Still to do:** user tests the full matrix in his browser — non-multi-cashier open flow, multi-cashier main cashier open, multi-cashier sub-cashier "Join Session" (after captain opens), multi-cashier sub-cashier "Waiting" (before captain opens), closing-issue deep-link.
- **Notes / follow-ups:**
  - **Cache-refresh-on-open is intentional.** `sessionStorage.clear()` + `window.location.reload()` after a successful open is deliberate so that menu items, categories, payment modes, and POS Profile all refetch. Do not "optimize" this to a soft re-run of `checkPOSStatus()` without also clearing those sessionStorage keys — you'd ship stale menus.
  - **Full in-POS closing dialog is phase-2 backlog.** The current closing-issue branch deep-links to the specific unclosed entry's form (`/app/pos-opening-entry/<name>`) which lands the user one click from the "Create Closing Entry" action. A native in-POS closing form needs computed invoice totals, denomination breakdown, and actual-vs-expected reconciliation — too much for phase 1.
  - **`validate_pos_close` response shape change is backward-compatible.** Older clients that read `.message === "Failed"` will no longer match (the response is now an object) — but the only caller in this repo is the POS provider, which handles both shapes.
  - **Multi-cashier captain detection uses `posProfile.applicable_for_users[].custom_main_cashier`.** If a POS Profile has multi-cashier mode enabled but no user is flagged as main cashier, the dialog falls back to showing the full form for everyone (misconfiguration should not hard-block).

### 2026-04-08 — POS "Permission Required" + Administrator "Access Denied"
- **Symptom:**
  1. Loading `/pos` showed a "Permission Required / Required roles:" screen with an empty required-roles list — users could not open the POS.
  2. Logging in as `Administrator` and opening `/pos` showed "Access Denied".
- **Root cause:**
  1. [pos/src/store/slices/config-slice.ts](pos/src/store/slices/config-slice.ts) `checkAccess()` set `hasAccess: false` whenever `allowedRoles.length === 0`. The allowed-roles list is derived from `posProfile.role_allowed_for_billing`; if that child table is empty or unreadable, the whole POS is locked out. The legacy Vue POS ([urypos/src/stores/Auth.js](urypos/src/stores/Auth.js)) never hard-gates on this — the gate is a React-POS regression.
  2. [ury/ury_pos/api.py](ury/ury_pos/api.py) `getBranch()` had the shape `if user != "Administrator": ...; return branch_name` with **no else branch** — Administrator fell through and the function returned `None` implicitly. Downstream `getPosProfile()` then tried `frappe.db.exists("POS Profile", {"branch": None})`, the chain blew up, and the frontend surfaced the error as "Access Denied". Two sibling functions (`getBranchRoom`, `getRoom`) in the same file have the identical bug but are not on Administrator's POS load path, so they were **deliberately left unfixed** in this round per user scope.
- **Files changed:**
  - [pos/src/store/slices/config-slice.ts](pos/src/store/slices/config-slice.ts) — `checkAccess()` now: (a) returns `hasAccess: true` unconditionally for `user.name === "Administrator"` or any user with the `System Manager` role; (b) treats an empty `allowedRoles` list as "no restriction" instead of "deny all".
  - [ury/ury_pos/api.py](ury/ury_pos/api.py) — `getBranch()` Administrator path now returns the branch of the first non-disabled POS Profile, or throws a clear "create a POS Profile linked to a Branch" message if none exists.
- **Verification:**
  - `yarn build` inside [pos/](pos/) — clean build, bundle regenerated into `ury/public/pos/` and `ury/www/pos.html`.
  - `python3 -m py_compile ury/ury_pos/api.py` — OK.
  - **Still to do:** user browser-tests Administrator login and a regular user login in the POS to confirm both paths open, then signs off before any push.
- **Notes / follow-ups:**
  - `getBranchRoom()` and `getRoom()` in [ury/ury_pos/api.py](ury/ury_pos/api.py) still have the identical Administrator bug — they'll bite the moment an Administrator uses multi-cashier mode or any code path that hits them. Revisit in the next permissions-cleanup pass.
  - `AuthGuard.tsx` was intentionally **not** touched — the two upstream fixes cover the root causes and editing the guard would risk hiding legitimate future errors.
  - The React POS introduced a hard "Permission Required" gate that the legacy Vue POS never had. Consider whether that whole component should be removed vs. softened when the broader permission redesign happens.

