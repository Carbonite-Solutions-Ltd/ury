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

