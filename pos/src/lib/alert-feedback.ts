// Audible + haptic alert for the "food ready" (order served) notification.
//
// Sound: a Web Audio "ding-ding" beep. Self-contained — the old code
// pointed `new Audio()` at `/assets/frappe/sounds/notification.mp3`, which
// does NOT exist in Frappe (the sounds folder has chime/alert/etc. but no
// notification.mp3), so the play() silently 404'd and no sound ever
// played. A generated tone has no asset dependency and can't 404.
//
// Browsers block audio until the user has interacted with the page, so the
// AudioContext is created lazily and ALSO primed on the first user gesture
// (see primeAlertAudio + the Footer's gesture listener).
//
// Vibration: navigator.vibrate works on Android Chrome (the tablets/phones
// where waiters run the PWA). iOS Safari has NO vibration API, so it's a
// silent no-op there — there is nothing we can do about that on iOS.
// 2026-07-15.

let audioCtx: AudioContext | null = null;

const getCtx = (): AudioContext | null => {
  try {
    if (!audioCtx) {
      const Ctor =
        window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      audioCtx = new Ctor();
    }
    return audioCtx;
  } catch {
    return null;
  }
};

/** Unlock the AudioContext. Call once from a user gesture (pointer/keydown). */
export const primeAlertAudio = (): void => {
  const ctx = getCtx();
  if (ctx && ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
};

/** Play a short two-tone "ding-ding" alert. */
export const playAlertSound = (): void => {
  const ctx = getCtx();
  if (!ctx) {
    // Fallback to an mp3 that DOES exist in Frappe, if WebAudio is absent.
    try {
      new Audio('/assets/frappe/sounds/chime.mp3').play().catch(() => {});
    } catch {
      /* ignore */
    }
    return;
  }
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  try {
    const now = ctx.currentTime;
    [0, 0.18].forEach((offset, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = i === 0 ? 880 : 1108;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.35, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.16);
      osc.connect(gain).connect(ctx.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.18);
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
