"""Unit tests for the sync queue's decision logic.

`rules.py` is deliberately free of `frappe` imports, so this suite needs
no site, no database and no bench:

    python3 -m unittest ury.ury.sync.test_sync_rules -v

It also exposes `run_sync_rules_tests()` for the repo's usual
`bench --site <site> execute ...` entry point (see CLAUDE.md rule 6),
since `bench run-tests` is blocked by the pre-existing ERPNext bootstrap
issue on these sites.
"""

import datetime
import unittest

from ury.ury.sync import rules

NOW = datetime.datetime(2026, 9, 24, 12, 0, 0)


class BackoffTests(unittest.TestCase):
    def test_schedule_is_front_loaded(self):
        self.assertEqual(
            [rules.backoff_seconds(n) for n in range(1, 6)],
            [60, 120, 300, 600, 1800],
        )

    def test_past_the_schedule_it_caps_and_stays_capped(self):
        for n in (6, 7, 50, 5000):
            self.assertEqual(rules.backoff_seconds(n), rules.MAX_BACKOFF_SECONDS)

    def test_nonsense_attempt_numbers_fall_back_to_the_first_delay(self):
        # Defensive: a corrupt row must not crash the worker.
        self.assertEqual(rules.backoff_seconds(0), 60)
        self.assertEqual(rules.backoff_seconds(-3), 60)

    def test_a_custom_schedule_is_honoured(self):
        self.assertEqual(rules.backoff_seconds(1, schedule=(5, 10), cap=99), 5)
        self.assertEqual(rules.backoff_seconds(2, schedule=(5, 10), cap=99), 10)
        self.assertEqual(rules.backoff_seconds(3, schedule=(5, 10), cap=99), 99)

    def test_an_empty_schedule_degrades_to_the_cap(self):
        self.assertEqual(rules.backoff_seconds(1, schedule=(), cap=42), 42)


class StatusTests(unittest.TestCase):
    def test_only_synced_and_failed_are_terminal(self):
        self.assertTrue(rules.is_terminal(rules.SYNCED))
        self.assertTrue(rules.is_terminal(rules.FAILED))
        for s in (rules.QUEUED, rules.SENDING, rules.RETRYING):
            self.assertFalse(rules.is_terminal(s), s)

    def test_only_queued_and_retrying_are_claimable(self):
        self.assertTrue(rules.is_claimable(rules.QUEUED))
        self.assertTrue(rules.is_claimable(rules.RETRYING))
        for s in (rules.SENDING, rules.SYNCED, rules.FAILED):
            self.assertFalse(rules.is_claimable(s), s)

    def test_an_unknown_status_is_never_claimable_or_terminal(self):
        self.assertFalse(rules.is_claimable("Banana"))
        self.assertFalse(rules.is_terminal("Banana"))


class DueTests(unittest.TestCase):
    def test_a_fresh_row_with_no_schedule_is_due_at_once(self):
        self.assertTrue(rules.is_due(rules.QUEUED, None, NOW))

    def test_a_retry_in_the_past_is_due(self):
        past = NOW - datetime.timedelta(seconds=1)
        self.assertTrue(rules.is_due(rules.RETRYING, past, NOW))

    def test_a_retry_in_the_future_is_not_due(self):
        future = NOW + datetime.timedelta(seconds=1)
        self.assertFalse(rules.is_due(rules.RETRYING, future, NOW))

    def test_exactly_due_counts_as_due(self):
        # Boundary: >= not >, or a row could be skipped for a whole cycle.
        self.assertTrue(rules.is_due(rules.RETRYING, NOW, NOW))

    def test_a_claimed_row_is_never_due(self):
        # Otherwise two workers would send the same row.
        self.assertFalse(rules.is_due(rules.SENDING, None, NOW))

    def test_finished_rows_are_never_due(self):
        for s in (rules.SYNCED, rules.FAILED):
            self.assertFalse(rules.is_due(s, None, NOW), s)


class FailureDecisionTests(unittest.TestCase):
    def test_a_permanent_rejection_is_terminal_with_no_next_attempt(self):
        status, nxt = rules.decide_after_failure(1, permanent=True, now=NOW)
        self.assertEqual(status, rules.FAILED)
        self.assertIsNone(nxt)

    def test_a_transient_failure_schedules_the_next_attempt(self):
        status, nxt = rules.decide_after_failure(1, permanent=False, now=NOW)
        self.assertEqual(status, rules.RETRYING)
        self.assertEqual(nxt, NOW + datetime.timedelta(seconds=60))

    def test_the_next_attempt_follows_the_backoff_schedule(self):
        _, nxt = rules.decide_after_failure(4, permanent=False, now=NOW)
        self.assertEqual(nxt, NOW + datetime.timedelta(seconds=600))

    def test_THE_INVARIANT_a_transient_failure_never_becomes_terminal(self):
        # This is the load-bearing difference from gra_evat's queue, which
        # gives up after ~20 attempts. Abandoning a sync row would silently
        # lose a real sale from head office's books, so no number of
        # transient failures may ever produce a terminal status.
        for attempts in (1, 5, 20, 100, 10_000):
            status, nxt = rules.decide_after_failure(
                attempts, permanent=False, now=NOW
            )
            self.assertFalse(rules.is_terminal(status), attempts)
            self.assertEqual(status, rules.RETRYING)
            self.assertIsNotNone(nxt)

    def test_a_long_outage_costs_one_attempt_an_hour(self):
        # The other half of retrying forever: it must stay cheap.
        _, nxt = rules.decide_after_failure(500, permanent=False, now=NOW)
        self.assertEqual(nxt, NOW + datetime.timedelta(seconds=3600))


class StaleClaimTests(unittest.TestCase):
    def test_a_long_claimed_row_is_stale(self):
        since = NOW - datetime.timedelta(seconds=rules.STALE_SENDING_SECONDS + 1)
        self.assertTrue(rules.is_stale_sending(rules.SENDING, since, NOW))

    def test_a_recently_claimed_row_is_not_stale(self):
        since = NOW - datetime.timedelta(seconds=5)
        self.assertFalse(rules.is_stale_sending(rules.SENDING, since, NOW))

    def test_exactly_at_the_threshold_is_stale(self):
        since = NOW - datetime.timedelta(seconds=rules.STALE_SENDING_SECONDS)
        self.assertTrue(rules.is_stale_sending(rules.SENDING, since, NOW))

    def test_only_sending_rows_can_be_stale(self):
        ancient = NOW - datetime.timedelta(days=30)
        for s in (rules.QUEUED, rules.RETRYING, rules.SYNCED, rules.FAILED):
            self.assertFalse(rules.is_stale_sending(s, ancient, NOW), s)

    def test_a_missing_timestamp_is_not_stale(self):
        self.assertFalse(rules.is_stale_sending(rules.SENDING, None, NOW))

    def test_the_threshold_exceeds_any_plausible_transport_timeout(self):
        # If this dropped below the transport timeout the sweeper would
        # reclaim rows that are still legitimately in flight, and the same
        # sale would be pushed twice.
        self.assertGreaterEqual(rules.STALE_SENDING_SECONDS, 300)


class AlertTests(unittest.TestCase):
    def test_a_permanent_failure_always_alerts(self):
        self.assertTrue(rules.should_alert(rules.FAILED, 0))

    def test_a_retry_below_the_threshold_stays_quiet(self):
        # Alerting on the first stutter trains people to ignore alerts.
        for n in range(0, rules.ALERT_AFTER_ATTEMPTS):
            self.assertFalse(rules.should_alert(rules.RETRYING, n), n)

    def test_a_retry_at_or_past_the_threshold_alerts(self):
        self.assertTrue(
            rules.should_alert(rules.RETRYING, rules.ALERT_AFTER_ATTEMPTS)
        )
        self.assertTrue(
            rules.should_alert(rules.RETRYING, rules.ALERT_AFTER_ATTEMPTS + 50)
        )

    def test_healthy_states_never_alert(self):
        for s in (rules.QUEUED, rules.SENDING, rules.SYNCED):
            self.assertFalse(rules.should_alert(s, 999), s)

    def test_the_alert_threshold_is_under_an_hour_of_failure(self):
        # A regression guard on the tuning. The first guess (10 attempts)
        # worked out at nearly six hours, which is far too late to be worth
        # telling anyone about. It must fire inside the same service.
        minutes = rules.total_backoff_through(rules.ALERT_AFTER_ATTEMPTS) / 60
        self.assertLess(minutes, 60, f"alerts after {minutes:.0f} min — too late")
        self.assertGreater(minutes, 15, f"alerts after {minutes:.0f} min — too jumpy")


def run_sync_rules_tests():
    """bench --site <site> execute ury.ury.sync.test_sync_rules.run_sync_rules_tests"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(__import__(__name__, fromlist=["*"]))
    unittest.TextTestRunner(verbosity=2).run(suite)
