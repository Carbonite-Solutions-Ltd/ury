/*
 * Pure connectivity hysteresis rule (KDS).
 *
 * Deliberately dependency-free so it can be unit-tested with no DOM and
 * no Vue instance — see URYMosaic/test/connectivity-rule.test.mjs.
 *
 * This is an intentional MIRROR of pos/src/lib/connectivity-rule.ts. The
 * three frontends in this repo share no code by design (see CLAUDE.md
 * "Repository layout"), and the two copies must agree on behaviour: a
 * kitchen screen and a till sitting on the same Wi-Fi should not disagree
 * about whether the venue is online. If you change one, change both.
 *
 * Why it exists: the KDS used to trust `navigator.onLine` outright, which
 * flaps on Android whenever the device roams between access points or
 * parks the Wi-Fi radio for power saving. Every flap popped the red "You
 * are Offline" toast and then a green "You are online" — the repeated
 * offline/online notifications reported from the kitchen, on a connection
 * that was working. (2026-09-24)
 */

/** Consecutive failed probes required before we declare the screen offline. */
export const FAILURES_BEFORE_OFFLINE = 2;

/**
 * Fold one probe result into the current state.
 *
 * - A success is positive proof of reachability: go online at once and
 *   clear the streak. Recovery is intentionally NOT hysteretic.
 * - A failure increments the streak but only flips to offline once the
 *   streak reaches `threshold`, so an isolated blip is absorbed silently.
 *
 * @param {{online: boolean, failures: number}} state
 * @param {boolean} probeOk
 * @param {number} [threshold]
 * @returns {{online: boolean, failures: number}}
 */
export function nextConnectivity(state, probeOk, threshold = FAILURES_BEFORE_OFFLINE) {
  if (probeOk) return { online: true, failures: 0 };
  const failures = state.failures + 1;
  return { online: failures >= threshold ? false : state.online, failures };
}
