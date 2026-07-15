// Audible + haptic alert for the "food ready" (order served) notification.
//
// Sound: plays a bundled audio FILE via `new Audio(url).play()` — the exact
// pattern the KDS (URYMosaic kot.vue) uses, which is known to work. An
// earlier attempt used a Web Audio oscillator beep; it didn't reliably play
// on the waiter's tablet, so we switched to a real file. The file ships in
// pos/public/sounds and is served under the Vite base at
// /assets/ury/pos/sounds/order-ready.wav (can't 404 — it's part of the
// build, unlike the old /assets/frappe/sounds/notification.mp3 which never
// existed).
//
// Browsers block audio until the user has interacted with the page, so we
// "unlock" it on the first user gesture by playing it muted once (see
// primeAlertAudio + the Footer's gesture listener). After that, later
// programmatic plays are allowed.
//
// Vibration: navigator.vibrate works on Android Chrome (the tablets/phones
// where waiters run the PWA). iOS Safari has NO vibration API, so it's a
// silent no-op there — nothing we can do about that on iPad. 2026-07-15.

const SOUND_URL = '/assets/ury/pos/sounds/order-ready.wav';
// Frappe ships this one (unlike notification.mp3); used only if the bundled
// file somehow fails to load.
const FALLBACK_URL = '/assets/frappe/sounds/chime.mp3';

let unlocked = false;

/** Unlock audio on a user gesture (play once muted). Call from pointer/keydown. */
export const primeAlertAudio = (): void => {
  if (unlocked) return;
  try {
    const a = new Audio(SOUND_URL);
    a.muted = true;
    a
      .play()
      .then(() => {
        a.pause();
        a.currentTime = 0;
        unlocked = true;
      })
      .catch(() => {
        /* still blocked — will retry on the next gesture */
      });
  } catch {
    /* ignore */
  }
};

/** Play the "food ready" alert sound at full volume. */
export const playAlertSound = (): void => {
  try {
    const a = new Audio(SOUND_URL);
    a.volume = 1;
    a.play().catch(() => {
      // Bundled file blocked/missing — try a Frappe sound that exists.
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
