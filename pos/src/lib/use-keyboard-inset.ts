import { useEffect, useState } from 'react';

/**
 * Number of pixels at the bottom of the screen currently covered by the
 * on-screen keyboard (0 when it's closed or unmeasurable).
 *
 * Why this is needed: a full-screen layout sized with `100vh` / `100dvh`
 * does NOT shrink when a mobile keyboard opens on iOS — the *layout*
 * viewport keeps its full height and the keyboard simply covers the
 * bottom of it. So anything vertically centred stays centred against the
 * full height and ends up hidden behind the keyboard. That is exactly
 * what happened on the POS login card: tapping the name field opened the
 * keyboard and pushed the results list out of sight.
 *
 * `window.visualViewport` reports the part of the page the user can
 * actually SEE, so the difference between it and the layout viewport is
 * the keyboard. Feed the result into `padding-bottom` on a centring
 * container and the content re-centres inside the visible area.
 *
 * Behaviour notes:
 *  - Android Chrome usually resizes the layout viewport too, so the
 *    difference is ~0 there and the layout reflows on its own. Returning
 *    0 is correct — no double compensation.
 *  - Values under a small threshold are ignored so that browser chrome
 *    collapsing (the URL bar hiding on scroll) isn't mistaken for a
 *    keyboard.
 *  - Returns 0 when the API is unavailable (older browsers, SSR), so
 *    callers degrade to their normal layout.
 */
export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);

  useEffect(() => {
    const vv = typeof window !== 'undefined' ? window.visualViewport : null;
    if (!vv) return;

    const update = () => {
      // `offsetTop` matters when the browser scrolls the visual viewport
      // to keep a focused field visible — without it we'd over-report.
      const covered = window.innerHeight - vv.height - vv.offsetTop;
      // 80px threshold: real keyboards are far taller than this, browser
      // chrome changes are not.
      setInset(covered > 80 ? Math.round(covered) : 0);
    };

    update();
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);
    return () => {
      vv.removeEventListener('resize', update);
      vv.removeEventListener('scroll', update);
    };
  }, []);

  return inset;
}
