// src/lib/pos-display.ts
// Ury POS Dual Screen Display - Production Version

import { usePOSStore, type OrderItem } from "../store/pos-store";

const BRIDGE_URL = "http://localhost:8000";
const DEFAULT_DWELL_MS = 5000; // Default 5 seconds if no setting
const EPSILON = 0.005;

let lastTotal: number | null = null;
let lastChange: number | null = null;
let lastCollect: number | null = null;
let isDialogOpen = false;
let enabled = false;
let posType = "";
let dwellMs = DEFAULT_DWELL_MS;
let observer: MutationObserver | null = null;
let initialized = false;
let loopTimer: ReturnType<typeof setTimeout> | null = null;
let loopIndex = 0; // cycles through the active payment display types

// Which values the customer screen should show (from POS Dual Screen Settings).
// Defaults preserve the previous behaviour (total + change) until settings load.
let showTotal = true;
let showPrice = false;
let showChange = true;
let showCollect = false;

// Cart-phase (pre-payment) tracking, driven by the Zustand store.
let lastCartTotal: number | null = null;
let lastItemCount = 0;
let cartUnsub: (() => void) | null = null;

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
      const totalSec = (h * 3600) + (mi * 60) + se;
      const ms = totalSec * 1000;
      return ms || DEFAULT_DWELL_MS;
    }
  }
  
  return DEFAULT_DWELL_MS;
}

async function fetchSettings(): Promise<boolean> {
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

    const isOn = (m: unknown) => m === 1 || m === "1";

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
  } catch {}
  
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

// Build the list of values to cycle on the customer screen during payment,
// honouring the enabled flags. Change is only shown once there's change due.
function activePaymentTypes(): Array<{ type: string; value: number }> {
  const types: Array<{ type: string; value: number }> = [];
  if (showTotal && lastTotal != null) types.push({ type: "total", value: lastTotal });
  if (showCollect) types.push({ type: "collect", value: lastCollect ?? 0 });
  if (showChange && (lastChange ?? 0) > 0) types.push({ type: "change", value: lastChange ?? 0 });
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

function isPaymentDialogVisible(): boolean {
  const h2s = document.querySelectorAll("h2");
  const h3s = document.querySelectorAll("h3");

  let hasPayment = false;
  let hasOrderSummary = false;

  for (const h2 of h2s) {
    if (h2.textContent?.trim() === "Payment") { hasPayment = true; break; }
  }
  for (const h3 of h3s) {
    if (h3.textContent?.trim() === "Order Summary") { hasOrderSummary = true; break; }
  }

  return hasPayment && hasOrderSummary;
}

function extractFinalTotal(): number | null {
  const h3s = document.querySelectorAll("h3");

  for (const h3 of h3s) {
    if (h3.textContent?.trim() !== "Order Summary") continue;

    const container = h3.parentElement;
    if (!container) continue;

    const borderTDiv = container.querySelector(".border-t");
    if (borderTDiv) {
      const text = borderTDiv.textContent || "";
      const matches = text.match(/[\d,]+\.?\d*/g);
      if (matches) {
        for (const match of matches) {
          const value = parseFloat(match.replace(/,/g, ""));
          if (value > 0) return value;
        }
      }
    }
  }
  return null;
}

function extractPaymentsTotal(): number {
  // Look for "Total Entered" section which shows paymentsTotal / finalTotal
  const spans = document.querySelectorAll("span");
  
  for (const span of spans) {
    if (span.textContent?.includes("Total Entered")) {
      // Find the sibling or nearby element with the amounts
      const parent = span.closest("div");
      if (parent) {
        const text = parent.textContent || "";
        // Pattern: "123.45 / 100.00" - we want the first number (payments total)
        const matches = text.match(/[\d,]+\.?\d*/g);
        if (matches && matches.length >= 1) {
          const paymentsTotal = parseFloat(matches[0].replace(/,/g, ""));
          if (!isNaN(paymentsTotal)) return paymentsTotal;
        }
      }
    }
  }
  
  // Alternative: Look for payment input fields and sum them
  const paymentInputs = document.querySelectorAll('input[type="number"]');
  let total = 0;
  
  paymentInputs.forEach(input => {
    const value = parseFloat((input as HTMLInputElement).value || "0");
    if (!isNaN(value) && value > 0) {
      total += value;
    }
  });
  
  return total;
}

function calculateChange(finalTotal: number, paymentsTotal: number): number {
  if (paymentsTotal > finalTotal) {
    return paymentsTotal - finalTotal;
  }
  return 0;
}

async function checkAndUpdate(): Promise<void> {
  if (!shouldRun()) return;

  const dialogVisible = isPaymentDialogVisible();

  // Dialog just opened
  if (dialogVisible && !isDialogOpen) {
    isDialogOpen = true;
    lastTotal = null;
    lastChange = null;
    lastCollect = null;
  }

  // Dialog just closed
  if (!dialogVisible && isDialogOpen) {
    isDialogOpen = false;
    lastTotal = null;
    lastChange = null;
    lastCollect = null;
    lastCartTotal = null; // force the cart total to resend when we return
    stopLoop();
    await clearDisplay();
    return;
  }

  // Dialog is open - extract values and update
  if (dialogVisible) {
    const total = extractFinalTotal();
    const paymentsTotal = extractPaymentsTotal();
    const change = total !== null ? calculateChange(total, paymentsTotal) : 0;

    const totalChanged = total !== null && total !== lastTotal;
    const collectChanged = paymentsTotal !== lastCollect;
    const changeChanged = change !== lastChange;

    if (totalChanged || collectChanged || changeChanged) {
      lastTotal = total;
      lastCollect = paymentsTotal;
      lastChange = change;

      // Restart the loop with new values
      startLoop();
    }
  }
}

// Unit price of a cart line (mirrors calculateItemPrice() in pos-store.ts).
function unitPrice(item: OrderItem): number {
  const base = item.selectedVariant?.price || item.price;
  const addons = item.selectedAddons?.reduce((sum, a) => sum + a.price, 0) || 0;
  return base + addons;
}

// While building the order (payment dialog not open), push the running cart
// total and the price of each item as it's added, straight from the store.
function startCartWatch(): void {
  if (cartUnsub) return;
  cartUnsub = usePOSStore.subscribe((state) => {
    if (!shouldRun() || isDialogOpen) return;

    if (showTotal) {
      const total = state.getCartTotals().total;
      if (lastCartTotal === null || Math.abs(total - lastCartTotal) > EPSILON) {
        lastCartTotal = total;
        void sendToDisplay("total", total);
      }
    }

    if (showPrice) {
      const count = state.activeOrders.reduce((s, i) => s + i.quantity, 0);
      if (count > lastItemCount) {
        const last = state.activeOrders[state.activeOrders.length - 1];
        if (last) void sendToDisplay("price", unitPrice(last));
      }
      lastItemCount = count;
    }
  });
}

function stopCartWatch(): void {
  if (cartUnsub) {
    cartUnsub();
    cartUnsub = null;
  }
}

export async function initPosDisplay(): Promise<void> {
  if (initialized) return;

  await fetchSettings();

  if (!shouldRun()) return;

  observer = new MutationObserver(() => {
    setTimeout(checkAndUpdate, 50);
  });

  observer.observe(document.body, { childList: true, subtree: true });
  startCartWatch();
  checkAndUpdate();

  initialized = true;
}

export function destroyPosDisplay(): void {
  if (observer) {
    observer.disconnect();
    observer = null;
  }
  stopCartWatch();
  stopLoop();
  initialized = false;
}