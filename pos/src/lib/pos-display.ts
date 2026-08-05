// src/lib/pos-display.ts
// Ury POS Dual Screen Display - Production Version
//
// Two sources, no DOM scraping:
//   - Cart phase: the Zustand cart store drives the price of each item as it's
//     added and the running cart total (while no payment dialog is open).
//   - Payment phase: PaymentDialog pushes the amount due / collected / change
//     imperatively via the exported display* functions.
// Everything POSTs to the local bridge as { type, value }.

import { usePOSStore, type OrderItem } from "../store/pos-store";

const BRIDGE_URL = "http://localhost:8000";
const DEFAULT_DWELL_MS = 5000; // Default 5 seconds if no setting
const EPSILON = 0.005;
const PRICE_HOLD_MS = 4000; // how long a just-added item's price stays before the total returns

let isDialogOpen = false;
let enabled = false;
let posType = "";
let dwellMs = DEFAULT_DWELL_MS;
let initialized = false;

// Which values the customer screen should show (from POS Dual Screen Settings).
// Defaults preserve the previous behaviour (total + change) until settings load.
let showTotal = true;
let showPrice = false;
let showChange = true;
let showCollect = false;

// Payment-phase values + the cycling loop that rotates them on the screen.
let payTotal: number | null = null;
let payCollect: number | null = null;
let payChange: number | null = null;
let loopTimer: ReturnType<typeof setTimeout> | null = null;
let loopIndex = 0;

// Cart-phase (pre-payment) tracking, driven by the store subscription.
let lastCartTotal: number | null = null;
let lastItemCount = 0;
let cartUnsub: (() => void) | null = null;
let priceHoldUntil = 0;
let holdTimer: ReturnType<typeof setTimeout> | null = null;

function parseLoopTimerToMs(val: unknown): number {
  if (val == null) return DEFAULT_DWELL_MS;

  if (typeof val === "number" && Number.isFinite(val)) {
    const ms = Math.max(0, val) * 1000;
    return ms || DEFAULT_DWELL_MS;
  }

  if (typeof val === "string") {
    const s = val.trim();
    // Accept plain number of seconds as string
    if (/^\d+(\.\d+)?$/.test(s)) {
      const ms = Math.max(0, parseFloat(s)) * 1000;
      return ms || DEFAULT_DWELL_MS;
    }
    // Accept HH:MM:SS (Frappe Time field)
    const m = s.match(/^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?$/);
    if (m) {
      const h = parseInt(m[1], 10) || 0;
      const mi = parseInt(m[2], 10) || 0;
      const se = parseInt(m[3] || "0", 10) || 0;
      const totalSec = h * 3600 + mi * 60 + se;
      const ms = totalSec * 1000;
      return ms || DEFAULT_DWELL_MS;
    }
  }

  return DEFAULT_DWELL_MS;
}

// Whether the settings lookup has already been answered this session.
//
// `POS Dual Screen Settings` is a customer-specific doctype that is NOT
// part of this app, so on most sites it does not exist and every field
// lookup 404s. Without this latch that cost SEVEN failed requests every
// time initPosDisplay ran - and it ran repeatedly, because `initialized`
// below is only set when shouldRun() is true, so a site without the
// doctype never latched and re-probed on every App effect pass. The
// result was a console full of DoesNotExistError that buried real
// errors and made a blank screen much harder to diagnose (2026-08-05).
let settingsResolved = false;

async function fetchSettings(): Promise<boolean> {
  if (settingsResolved) return enabled;
  try {
    const getSingle = (field: string) =>
      fetch("/api/method/frappe.client.get_single_value?" + new URLSearchParams({
        doctype: "POS Dual Screen Settings",
        field
      })).then((r) => r.json());

    const [
      enabledData, posTypeData, loopTimerData,
      totalData, priceData, changeData, collectData,
    ] = await Promise.all([
      getSingle("enabled"), getSingle("pos_type"), getSingle("loop_timer"),
      getSingle("total"), getSingle("price"), getSingle("change"), getSingle("collect"),
    ]);

    // A missing doctype comes back as a 404 body, NOT a thrown error -
    // fetch() only rejects on network failure, so the catch below never
    // sees this. Detect it explicitly and stand down quietly: a site
    // without the customer-display doctype simply has no customer
    // display, which is not a fault worth shouting about.
    if (enabledData?.exc_type === "DoesNotExistError") {
      settingsResolved = true;
      enabled = false;
      console.info(
        "[ury_display] POS Dual Screen Settings is not installed on this site — customer display disabled."
      );
      return false;
    }

    const isOn = (m: unknown) => m === 1 || m === "1";

    settingsResolved = true;
    enabled = isOn(enabledData.message);
    posType = (posTypeData.message || "").toLowerCase().trim();
    dwellMs = parseLoopTimerToMs(loopTimerData.message);
    showTotal = isOn(totalData.message);
    showPrice = isOn(priceData.message);
    showChange = isOn(changeData.message);
    showCollect = isOn(collectData.message);

    return true;
  } catch (e) {
    console.error("[ury_display] Settings error:", e);
    // Default to enabled for Ury if fetch fails
    enabled = true;
    posType = "ury";
    dwellMs = DEFAULT_DWELL_MS;
    return false;
  }
}

function shouldRun(): boolean {
  return enabled && posType === "ury";
}

async function sendToDisplay(type: string, value: number): Promise<boolean> {
  if (!shouldRun()) return false;
  try {
    const r = await fetch(`${BRIDGE_URL}/update_display`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, value }),
    });
    const j = await r.json();
    return j?.status === "success";
  } catch {
    return false;
  }
}

async function clearDisplay(): Promise<void> {
  if (!shouldRun()) return;

  // Try clear command first
  try {
    const r = await fetch(`${BRIDGE_URL}/update_display`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "clear" }),
    });
    const j = await r.json();
    if (j?.status === "success") return;
  } catch {
    /* fall through to zeros */
  }

  // Fallback to sending zeros
  await sendToDisplay("total", 0);
  await sendToDisplay("change", 0);
}

function stopLoop(): void {
  if (loopTimer) {
    clearTimeout(loopTimer);
    loopTimer = null;
  }
  loopIndex = 0;
}

// The values to rotate on the customer screen during payment, honouring the
// enabled flags. Change is only shown once there's change due.
function activePaymentTypes(): Array<{ type: string; value: number }> {
  const types: Array<{ type: string; value: number }> = [];
  if (showTotal && payTotal != null) types.push({ type: "total", value: payTotal });
  if (showCollect) types.push({ type: "collect", value: payCollect ?? 0 });
  if (showChange && (payChange ?? 0) > 0) types.push({ type: "change", value: payChange ?? 0 });
  return types;
}

async function loopStep(): Promise<void> {
  if (!isDialogOpen || !shouldRun()) {
    stopLoop();
    return;
  }

  const types = activePaymentTypes();
  if (types.length === 0) {
    loopTimer = setTimeout(loopStep, dwellMs);
    return;
  }

  const { type, value } = types[loopIndex % types.length];
  await sendToDisplay(type, value);
  loopIndex++;
  loopTimer = setTimeout(loopStep, dwellMs);
}

function startLoop(): void {
  stopLoop();
  loopIndex = 0;
  loopStep();
}

// Unit price of a cart line (mirrors calculateItemPrice() in pos-store.ts).
function unitPrice(item: OrderItem): number {
  const base = item.selectedVariant?.price || item.price;
  const addons = item.selectedAddons?.reduce((sum, a) => sum + a.price, 0) || 0;
  return base + addons;
}

function clearHoldTimer(): void {
  if (holdTimer) {
    clearTimeout(holdTimer);
    holdTimer = null;
  }
}

// While building the order (payment dialog not open), push the running cart
// total and the price of each item as it's added, straight from the store.
// When an item is added we show its price first and hold it for PRICE_HOLD_MS
// before letting the running total take the screen back.
function startCartWatch(): void {
  if (cartUnsub) return;
  cartUnsub = usePOSStore.subscribe((state) => {
    if (!shouldRun() || isDialogOpen) return;

    const count = state.activeOrders.reduce((s, i) => s + i.quantity, 0);
    const itemAdded = count > lastItemCount;
    lastItemCount = count;

    if (showPrice && itemAdded) {
      const last = state.activeOrders[state.activeOrders.length - 1];
      if (last) void sendToDisplay("price", unitPrice(last));
      priceHoldUntil = Date.now() + PRICE_HOLD_MS;
      lastCartTotal = null; // force the total to re-send once the hold expires
      clearHoldTimer();
      if (showTotal) {
        holdTimer = setTimeout(() => {
          holdTimer = null;
          if (!shouldRun() || isDialogOpen) return;
          const t = usePOSStore.getState().getCartTotals().total;
          lastCartTotal = t;
          void sendToDisplay("total", t);
        }, PRICE_HOLD_MS);
      }
      return;
    }

    // Outside a price hold, push the running total whenever it changes.
    if (showTotal && Date.now() >= priceHoldUntil) {
      const total = state.getCartTotals().total;
      if (lastCartTotal === null || Math.abs(total - lastCartTotal) > EPSILON) {
        lastCartTotal = total;
        void sendToDisplay("total", total);
      }
    }
  });
}

function stopCartWatch(): void {
  clearHoldTimer();
  if (cartUnsub) {
    cartUnsub();
    cartUnsub = null;
  }
}

export async function initPosDisplay(): Promise<void> {
  if (initialized) return;

  await fetchSettings();

  if (!shouldRun()) {
    // Latch even when the display is off. This used to return without
    // setting `initialized`, so a site with no customer display re-ran
    // the whole settings probe on every effect pass - seven 404s each
    // time. There is nothing to retry: the answer cannot change without
    // a reload.
    initialized = true;
    return;
  }

  startCartWatch();
  initialized = true;
}

export function destroyPosDisplay(): void {
  stopCartWatch();
  stopLoop();
  initialized = false;
}

// ─── Payment screen API — called by PaymentDialog (no DOM scraping) ──────────

/** Payment dialog opened; `due` is the amount payable. */
export function displayPaymentOpen(due: number): void {
  if (!shouldRun()) return;
  isDialogOpen = true;
  payTotal = Number.isFinite(due) ? due : null;
  payCollect = 0;
  payChange = 0;
  startLoop();
}

/** Live update of amount due / collected (tendered) / change. */
export function displayPaymentUpdate(due: number, collect: number, change: number): void {
  if (!shouldRun() || !isDialogOpen) return;
  const t = Number.isFinite(due) ? due : payTotal;
  const c = Number.isFinite(collect) ? collect : 0;
  const ch = Number.isFinite(change) ? change : 0;
  if (t === payTotal && c === payCollect && ch === payChange) return;
  payTotal = t;
  payCollect = c;
  payChange = ch;
  startLoop();
}

/** Payment dialog closed; clear the screen and let the cart total resume. */
export function displayPaymentClose(): void {
  isDialogOpen = false;
  payTotal = null;
  payCollect = null;
  payChange = null;
  lastCartTotal = null; // force the cart total to resend when we return
  stopLoop();
  void clearDisplay();
}
