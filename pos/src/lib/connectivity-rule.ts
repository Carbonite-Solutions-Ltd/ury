/*
 * Pure connectivity hysteresis rule.
 *
 * Deliberately a separate, DEPENDENCY-FREE module: connectivity.ts holds
 * the I/O (fetch probe, timers, zustand store), and this holds the single
 * decision those timers feed. Keeping it free of imports is what lets it
 * be transpiled and unit-tested on its own with no DOM and no store — see
 * test/connectivity-rule.test.mjs.
 *
 * Why the rule exists at all: flipping to offline on ONE failed probe made
 * the POS alarm on every momentary blip and then immediately recover,
 * which is the offline/online flapping reported from the floor on an
 * internet connection that was fine. See connectivity.ts for the full
 * account. (2026-09-24)
 */

/** Consecutive failed probes required before we declare the POS offline. */
export const FAILURES_BEFORE_OFFLINE = 2;

export interface ConnectivityDecision {
  online: boolean;
  failures: number;
}

/**
 * Fold one probe result into the current state.
 *
 * - A success is positive proof of reachability: go online at once and
 *   clear the streak. Recovery is intentionally NOT hysteretic — there is
 *   no benefit to making a working connection look broken for longer.
 * - A failure increments the streak but only flips to offline once the
 *   streak reaches `threshold`. Below that the previous state is held, so
 *   an isolated blip is absorbed with no banner and no toast.
 */
export function nextConnectivity(
  state: ConnectivityDecision,
  probeOk: boolean,
  threshold: number = FAILURES_BEFORE_OFFLINE
): ConnectivityDecision {
  if (probeOk) return { online: true, failures: 0 };
  const failures = state.failures + 1;
  return { online: failures >= threshold ? false : state.online, failures };
}
