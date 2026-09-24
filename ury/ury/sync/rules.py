"""Pure decision logic for the branch -> cloud sync queue.

DELIBERATELY FREE OF `frappe` IMPORTS. Everything here is arithmetic over
plain values so it can be unit-tested with no site, no database and no
bench — the same discipline as `_pick_outlet_warehouse` in
`ury/ury/doctype/ury_order/ury_order.py`. `queue.py` and `worker.py` hold
the I/O; this holds the decisions.

── Why this exists ─────────────────────────────────────────────────────
Under the offline/LAN architecture each branch runs its own URY instance
and is authoritative for its own trading. Completed sales then have to
reach the cloud for head-office reporting. The branch's link is
unreliable by assumption (that is the entire premise), so "push it when
it happens" is not a strategy — the push needs a durable queue with
retries, and the retry policy is the part most likely to be got wrong.

── The one rule that differs from `gra_evat`'s queue ───────────────────
`gra_evat` gives up after ~20 attempts and marks a transaction
`Rejected`, which is correct there: a tax submission that GRA keeps
refusing needs a human, and nothing is lost by pausing.

Sync is NOT like that. Abandoning a row means a real sale silently never
reaches head office's books. So a **transient** failure is retried
FOREVER, with the backoff capped so a branch that is offline for two days
costs one attempt an hour rather than thousands. Only a **permanent**
rejection — the receiver telling us the payload itself is wrong — is
allowed to become terminal, and that is precisely the case a human must
look at.
"""

from __future__ import annotations

import datetime

# ── Statuses ────────────────────────────────────────────────────────────
QUEUED = "Queued"
SENDING = "Sending"
SYNCED = "Synced"
RETRYING = "Retrying"
FAILED = "Failed"

#: Terminal states. `Synced` is success; `Failed` needs a human.
TERMINAL_STATUSES = frozenset({SYNCED, FAILED})
#: States a worker may pick up (subject to being due).
CLAIMABLE_STATUSES = frozenset({QUEUED, RETRYING})

# ── Timings ─────────────────────────────────────────────────────────────
#: Backoff before attempts 2..6. Front-loaded because the commonest failure
#: is a brief link stutter, not a dead branch.
BACKOFF_SECONDS: tuple[int, ...] = (60, 120, 300, 600, 1800)
#: Every attempt after the schedule waits this long. Caps the cost of a
#: branch that has been offline for days at one attempt an hour.
MAX_BACKOFF_SECONDS = 3600
#: A row left `Sending` longer than this had its worker die mid-flight
#: (process restart, power cut). The sweeper returns it to `Retrying`.
#: Must comfortably exceed the transport timeout.
STALE_SENDING_SECONDS = 600
#: Attempts after which a still-unsynced row is worth telling someone
#: about. With the schedule above this is ~48 minutes of CONTINUOUS
#: failure (60+120+300+600+1800s), which is the number that matters: long
#: past any link stutter, but still inside the same service so someone can
#: act on it. 10 attempts was the first guess and it works out at nearly
#: six hours — far too late to be worth paging anyone about.
ALERT_AFTER_ATTEMPTS = 5


def backoff_seconds(
    attempts: int,
    schedule: tuple[int, ...] = BACKOFF_SECONDS,
    cap: int = MAX_BACKOFF_SECONDS,
) -> int:
    """Seconds to wait before the attempt AFTER `attempts` failures.

    `attempts` is the number that have already failed, so 1 -> the first
    retry delay. Anything past the schedule returns `cap`, forever.
    """
    if attempts < 1:
        return schedule[0] if schedule else cap
    if attempts <= len(schedule):
        return schedule[attempts - 1]
    return cap


def is_terminal(status: str) -> bool:
    """Has this row finished, successfully or otherwise?"""
    return status in TERMINAL_STATUSES


def is_claimable(status: str) -> bool:
    """Could a worker pick this row up (ignoring whether it is due yet)?"""
    return status in CLAIMABLE_STATUSES


def is_due(
    status: str,
    next_attempt_at: datetime.datetime | None,
    now: datetime.datetime,
) -> bool:
    """Should a worker send this row right now?

    A row with no `next_attempt_at` is due immediately — that is how a
    freshly enqueued row behaves.
    """
    if not is_claimable(status):
        return False
    if next_attempt_at is None:
        return True
    return next_attempt_at <= now


def decide_after_failure(
    attempts: int,
    permanent: bool,
    now: datetime.datetime,
) -> tuple[str, datetime.datetime | None]:
    """Where does a row go after a failed send?

    Returns `(status, next_attempt_at)`.

    A permanent failure is terminal and carries no next attempt — the
    receiver has told us the payload is wrong and repeating it cannot
    help. Everything else retries, indefinitely, because dropping a row
    loses a real sale from head office's books.
    """
    if permanent:
        return FAILED, None
    delay = backoff_seconds(attempts)
    return RETRYING, now + datetime.timedelta(seconds=delay)


def is_stale_sending(
    status: str,
    since: datetime.datetime | None,
    now: datetime.datetime,
    threshold_seconds: int = STALE_SENDING_SECONDS,
) -> bool:
    """Was this row claimed by a worker that then died?

    Only ever true for `Sending`. Without this a single crashed worker
    would strand its claimed rows forever, because nothing else will pick
    up a `Sending` row.
    """
    if status != SENDING or since is None:
        return False
    return (now - since).total_seconds() >= threshold_seconds


def should_alert(
    status: str,
    attempts: int,
    threshold: int = ALERT_AFTER_ATTEMPTS,
) -> bool:
    """Is this row worth telling a human about?

    `Failed` always is — it needs a decision. A retrying row only once it
    has been failing long enough that a stutter has been ruled out;
    alerting on the first failure would train people to ignore alerts.
    """
    if status == FAILED:
        return True
    if status == RETRYING:
        return attempts >= threshold
    return False


def total_backoff_through(attempts: int) -> int:
    """Total seconds of waiting across the first `attempts` retries.

    Only used by tests and diagnostics, to state plainly how long a row
    waits before it starts alerting.
    """
    return sum(backoff_seconds(n) for n in range(1, max(attempts, 0) + 1))
