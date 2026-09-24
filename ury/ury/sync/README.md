# URY branch → cloud sync

Outbound replication of completed sales from a **branch-local** URY site to
the **cloud** site, for head-office reporting.

> **Status: increment 1 of the offline/LAN architecture.** The engine is
> built and unit-tested; it has **not** been run against two real sites yet.
> See *What is not done* below before deploying anything.

**Disabled by default.** While `URY Sync Settings.enabled` is off, the doc
event and both scheduled jobs return immediately. Installing this changes
nothing on an existing site until somebody switches it on.

## Why this exists

Under the offline/LAN architecture each branch runs its own URY instance on
the restaurant LAN and is authoritative for its own trading, so service
survives an internet outage. Completed sales then have to reach the cloud.
The branch's link is unreliable *by assumption* — that is the entire premise
— so "push it when it happens" is not a strategy. Hence a durable queue that
retries.

## Shape

```
BRANCH SITE                                  CLOUD SITE
  POS Invoice submitted
        │ doc_event (no-op when disabled)
        ▼
  URY Sync Queue  ──► worker.process_queue (every minute)
        ▲                     │ payload.build
        │                     ▼
        │              transport.push_sale ──HTTP──► receiver.receive_sale
        │                                                   │
   worker.sweep (15 min)                                     ▼
   reclaim / backfill / alert                        URY Remote Sale
                                                     (+ Remote Sale Item)
```

| File | Role |
|---|---|
| `rules.py` | **Pure.** The state machine: backoff, due-ness, staleness, alerting. No `frappe` import, so it tests without a bench. |
| `queue.py` | Enqueue, claim, mark. The doc-event handler lives here. |
| `payload.py` | Builds the wire payload. `to_payload` is pure. |
| `transport.py` | HTTP delivery and — importantly — failure classification. |
| `worker.py` | The two scheduled jobs. |
| `receiver.py` | **Runs on the cloud.** Accepts a sale, idempotently. |

## Three decisions worth knowing before changing anything

**1. Sales are mirrored, not replicated.** They land in `URY Remote Sale`, a
hook-free doctype with no links to masters — *not* in a real POS Invoice.
Inserting a real POS Invoice on the cloud would fire `pos_invoice_naming`
(re-assigning its name), ERPNext's `validate_pos_opening_entry` (which throws
outright — the cloud has no open shift for that profile) and
`set_order_number` (recomputing from the wrong baseline). Suppressing all
three would be fragile in a way that corrupts replicas silently.

**2. A transient failure retries forever.** This is the deliberate difference
from `gra_evat`'s queue, which gives up after ~20 attempts. Abandoning a sync
row means a real sale silently never reaches head office's books. Only an
*explicit rejection from the receiver* is terminal. Backoff caps at hourly so
a branch offline for two days costs 24 attempts, not thousands.

**3. Idempotency lives at the receiver, not the claim.** `URY Remote Sale` is
keyed `<source site>|<invoice name>`; a repeat delivery returns
`duplicate: 1` without inserting. The queue's claim is an optimisation to
avoid wasted requests — if two workers ever raced past it, the cost is one
redundant HTTP call, not a double-booked sale. Scoping the key by site also
means two branches cannot collide **even if the per-branch invoice prefixes
were never configured**, which is a real risk (see `gra-evat` D14).

## Setup

**On the cloud site:** create a dedicated user with create/write on `URY
Remote Sale`, generate API key + secret. Do not reuse an administrator key.
Leave `URY Sync Settings.enabled` **off** there — a receiving site must not
also push.

**On each branch site:** fill in `URY Sync Settings` (remote URL, key,
secret, alert role), then tick `enabled`.

The settings doctype refuses a remote URL pointing at itself, and the
receiver refuses to accept anything while its own outbound sync is enabled —
between them a site cannot end up in a loop with itself.

## Tests

No bench required — both suites are pure:

```bash
env/bin/python -m unittest ury.ury.sync.test_sync_rules ury.ury.sync.test_sync_payload
```

51 tests: the backoff schedule and its cap, claim/terminal/due boundaries,
stale reclaim, alert thresholds (including a regression guard that alerting
lands under an hour of failure), payload field renames and the `no_of_pax`
string coercion, `remote_key` collision-scoping, and the failure classifier —
with explicit invariant tests that a transient failure can **never** become
terminal and that only an explicit rejection ever is.

## What is NOT done

- **Never run against two live sites.** Every test here is a unit test. The
  HTTP leg, the API-key auth and the receiver's behaviour under a real
  Frappe request have not been exercised end to end.
- **No masters sync (cloud → branch).** Menus, items, prices and tax
  templates still have to reach a branch somehow. Nothing here does that.
- **Reporting still reads POS Invoice.** Head-office reports will not see
  `URY Remote Sale` rows until they are taught to, so a branch-hosted sale is
  currently invisible to them.
- **Only POS Invoice is synced.** Not KOTs, shifts, closing entries or
  customers created at a branch.
- **`backfill_missing` only looks at sales created since sync was switched
  on**, deliberately — enabling it must not enqueue years of history. A
  genuine historical backfill needs its own tool.
- **Returns** are queued as their own submitted invoice, which is correct,
  but the cloud has no logic tying a return to its original.
