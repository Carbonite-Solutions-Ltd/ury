// Audible + haptic alert for the "food ready" (order served) notification.
//
// Sound: plays a bundled audio FILE via a SINGLE persistent <audio> element
// unlocked on the first user gesture. The important detail (why the earlier
// attempt failed on Android): a *fresh* `new Audio()` created inside a
// socket/interval callback is NOT unlocked even if the user tapped earlier —
// mobile browsers unlock the specific element that played during a gesture.
// So we keep ONE element, unlock it once (play it at ~0 volume on the first
// pointer/keydown), and replay that same element for every alert.
//
// The file ships in pos/public/sounds and is served under the Vite base at
// /assets/ury/pos/sounds/order-ready.wav (part of the build — can't 404).
//
// Vibration: navigator.vibrate works on Android Chrome (the tablets where
// waiters run the PWA) as long as the page has been interacted with. iOS
// Safari has NO vibration API — silent no-op there.
//
// NOTE: this only fires while the PWA is OPEN and reasonably active. A phone
// that's asleep / the app closed needs Web Push + a service worker (OS-level
// notification) — a separate, larger feature. 2026-07-15.

const SOUND_URL = '/assets/ury/pos/sounds/order-ready.wav';
const FALLBACK_URL = '/assets/frappe/sounds/chime.mp3';

let audioEl: HTMLAudioElement | null = null;
let unlocked = false;

const getEl = (): HTMLAudioElement | null => {
  try {
    if (!audioEl) {
      audioEl = new Audio(SOUND_URL);
      audioEl.preload = 'auto';
    }
    return audioEl;
  } catch {
    return null;
  }
};

/** Unlock the persistent audio element. Call from a user gesture. */
export const primeAlertAudio = (): void => {
  if (unlocked) return;
  const el = getEl();
  if (!el) return;
  const prevVol = el.volume;
  try {
    el.volume = 0.01;
    el
      .play()
      .then(() => {
        el.pause();
        el.currentTime = 0;
        el.volume = prevVol;
        unlocked = true;
      })
      .catch(() => {
        el.volume = prevVol;
      });
  } catch {
    el.volume = prevVol;
  }
};

/** Play the "food ready" alert sound at full volume. */
export const playAlertSound = (): void => {
  const el = getEl();
  if (!el) return;
  try {
    el.currentTime = 0;
    el.volume = 1;
    el.play().catch(() => {
      // The persistent element was blocked (e.g. never unlocked) — try a
      // one-off Frappe sound that exists as a last resort.
      try {
        new Audio(FALLBACK_URL).play().catch(() => {});
      } catch {
        /* ignore */
      }
    });
  } catch {
    /* ignore */
  }
};

/** Vibrate the device (Android only; no-op on desktop / iOS). */
export const vibrateAlert = (): void => {
  try {
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      navigator.vibrate([250, 120, 250]);
    }
  } catch {
    /* ignore */
  }
};
