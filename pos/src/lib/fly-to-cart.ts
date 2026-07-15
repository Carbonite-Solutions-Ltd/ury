// "Fly to cart" feedback when a menu item is added to the order.
//
// Animates a small dot on an arc from the tapped menu card to the floating
// cart button, gives the cart a little bump when it lands, and fires a short
// haptic tap. Purely cosmetic — wrapped in try/catch and a feature check so
// it never interferes with the actual add-to-cart. The cart target is found
// via `[data-cart-target]` (the FAB on mobile/tablet); on desktop there's no
// FAB, so the fly is skipped and only the vibration runs. 2026-07-16.

/** Short haptic tap on add-to-cart (Android; no-op on desktop / iOS). */
export const vibrateTap = (): void => {
  try {
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      navigator.vibrate(25);
    }
  } catch {
    /* ignore */
  }
};

export const flyToCart = (source: HTMLElement | null): void => {
  vibrateTap();
  try {
    if (!source || typeof source.animate !== 'function') return;
    // Pick the VISIBLE cart target: the floating FAB in portrait (< lg) or
    // the side cart panel in landscape (lg+). Both carry [data-cart-target];
    // only one is rendered/visible at a time.
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const target =
      (Array.from(
        document.querySelectorAll('[data-cart-target]')
      ) as HTMLElement[]).find((el) => {
        const r = el.getBoundingClientRect();
        // Has size AND is actually on-screen (the mobile drawer keeps its
        // width even when translated off-screen right, so check the bounds).
        return (
          r.width > 0 &&
          r.height > 0 &&
          r.left < vw &&
          r.right > 0 &&
          r.top < vh &&
          r.bottom > 0
        );
      }) || null;
    if (!target) return; // nothing visible to fly to — vibration only

    const s = source.getBoundingClientRect();
    const t = target.getBoundingClientRect();
    if (!s.width || !t.width) return;

    const size = 22;
    const startX = s.left + s.width / 2 - size / 2;
    const startY = s.top + s.height / 2 - size / 2;
    const endX = t.left + t.width / 2 - size / 2;
    const endY = t.top + t.height / 2 - size / 2;
    const dx = endX - startX;
    const dy = endY - startY;

    const dot = document.createElement('div');
    Object.assign(dot.style, {
      position: 'fixed',
      left: `${startX}px`,
      top: `${startY}px`,
      width: `${size}px`,
      height: `${size}px`,
      borderRadius: '9999px',
      background: '#2563eb',
      boxShadow: '0 4px 14px rgba(37,99,235,0.5)',
      zIndex: '60',
      pointerEvents: 'none',
      willChange: 'transform, opacity',
    } as CSSStyleDeclaration);
    document.body.appendChild(dot);

    const anim = dot.animate(
      [
        { transform: 'translate(0px, 0px) scale(1)', opacity: 1 },
        {
          // arc upward before dropping into the cart — the "swish"
          transform: `translate(${dx * 0.5}px, ${dy * 0.5 - 60}px) scale(0.85)`,
          opacity: 1,
          offset: 0.55,
        },
        { transform: `translate(${dx}px, ${dy}px) scale(0.3)`, opacity: 0.35 },
      ],
      { duration: 560, easing: 'cubic-bezier(0.45, 0, 0.35, 1)' }
    );

    anim.onfinish = () => {
      dot.remove();
      // Bump ONLY a small target (the FAB) — scaling the wide side cart
      // panel on desktop would look jarring.
      if (t.width <= 120) {
        try {
          target.animate(
            [
              { transform: 'scale(1)' },
              { transform: 'scale(1.28)' },
              { transform: 'scale(1)' },
            ],
            { duration: 260, easing: 'ease-out' }
          );
        } catch {
          /* ignore */
        }
      }
    };
    // Safety: if onfinish never fires (tab hidden mid-animation), clean up.
    anim.oncancel = () => dot.remove();
  } catch {
    /* animation not supported — ignore */
  }
};
