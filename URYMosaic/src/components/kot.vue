<template>
  <!-- Single root on purpose: masonryLoading() uses this.$el.querySelector,
       and a multi-root (fragment) component would make $el a comment node. -->
  <div>
    <Header
      :view-mode="viewMode"
      :unit-label="boardActive ? production : ''"
      :can-switch="canSwitchUnit"
      :picker-mode="!boardActive"
      @set-view="onSetView"
      @logout="logout"
      @switch="unitPickerMode = 'modal'"
    />

    <!-- Screen picker (2026-09-18): /Mosaic landing, the Switch button, and
         the "not your screen" case. Only once the user's units are loaded,
         so a signed-out visitor still gets the Not Permitted modal. -->
    <UnitPicker
      v-if="unitsLoaded && unitPickerMode"
      :mode="unitPickerMode"
      :units="myUnits"
      :departments="myDepartments"
      :current="production"
      :full-name="myFullName"
      @pick="openScreen"
      @close="unitPickerMode = ''"
      @logout="logout"
    />

    <!-- mb-16 keeps the kitchen board clear of the bottom edge; the stock
         sheet sizes itself to the window instead, so it drops the margin
         (measureStockPanel reserves only the p-4 below it). -->
    <div
      class="mx-auto p-4 relative"
      :class="viewMode === 'served' && servedTab === 'stock' ? 'mb-0' : 'mb-16'"
    >
    <!-- Bar handover (2026-09-18). A Bar unit has to be "opened" before the
         stock report has a starting point, so the prompt sits above every
         view - the barman taking over cannot miss it. Kitchen units never
         see any of this. -->
    <div
      v-if="isBarUnit && !barSession"
      class="mb-4 rounded-xl border-2 border-amber-400 bg-amber-50 p-4 flex items-center justify-between gap-4 flex-wrap"
    >
      <div class="min-w-0">
        <h2 class="text-lg font-extrabold text-amber-900">Open the bar</h2>
        <p class="text-sm text-amber-800">
          Taking over? Open the bar to record the stock you are starting with.
          At the end of your watch you can print a handover sheet.
        </p>
      </div>
      <button
        type="button"
        @click="openBar"
        :disabled="openingBar"
        class="rounded-lg bg-amber-600 px-5 py-2.5 text-white text-sm font-bold hover:bg-amber-700 disabled:opacity-50"
      >
        {{ openingBar ? "Opening…" : "Open the bar" }}
      </button>
    </div>
    <div
      v-else-if="isBarUnit && barSession"
      class="mb-4 flex items-center justify-between gap-3 flex-wrap rounded-lg bg-white shadow px-4 py-2 text-sm"
    >
      <span class="text-gray-700">
        Bar open since
        <strong>{{ fmtWhen(barSession.opened_at) }}</strong>
        · {{ barSession.opened_by_name }}
      </span>
      <button
        type="button"
        @click="goToStockReport"
        class="rounded-md bg-gray-900 text-white px-3 py-1.5 text-xs font-semibold hover:bg-gray-700"
      >
        Stock report
      </button>
    </div>
    <!-- Served view (2026-07-16 / sidebar 2026-07-23): a sidebar toggles
         Recently Served (reinstate list) vs Items Served (sold summary).
         Recently Served is first + the default; it's hidden when the
         production unit has reinstate disabled. -->
    <div v-if="viewMode === 'served'" class="flex gap-4 items-start">
      <aside class="w-40 shrink-0 space-y-1 sticky top-4 self-start">
        <button
          v-if="reinstateEnabled"
          type="button"
          @click="servedTab = 'recent'"
          :class="[
            'w-full text-left px-3 py-2 rounded-lg text-sm font-semibold transition',
            servedTab === 'recent'
              ? 'bg-gray-900 text-white shadow'
              : 'bg-white text-gray-700 hover:bg-gray-100',
          ]"
        >
          Recently Served
        </button>
        <button
          type="button"
          @click="servedTab = 'summary'"
          :class="[
            'w-full text-left px-3 py-2 rounded-lg text-sm font-semibold transition',
            servedTab === 'summary'
              ? 'bg-gray-900 text-white shadow'
              : 'bg-white text-gray-700 hover:bg-gray-100',
          ]"
        >
          Items Served
        </button>
        <!-- Orders taken off this screen (2026-09-19): Cancelled went through
             the kitchen (or its grace window), Deleted was a manager's call
             that never asked. -->
        <button
          v-for="tab in removedTabs"
          :key="tab.key"
          type="button"
          @click="openRemovedTab(tab.key)"
          :class="[
            'w-full text-left px-3 py-2 rounded-lg text-sm font-semibold transition',
            servedTab === tab.key
              ? 'bg-gray-900 text-white shadow'
              : 'bg-white text-gray-700 hover:bg-gray-100',
          ]"
        >
          {{ tab.label }}
        </button>
        <button
          v-if="isBarUnit"
          type="button"
          @click="openStockTab"
          :class="[
            'w-full text-left px-3 py-2 rounded-lg text-sm font-semibold transition',
            servedTab === 'stock'
              ? 'bg-gray-900 text-white shadow'
              : 'bg-white text-gray-700 hover:bg-gray-100',
          ]"
        >
          Stock Report
        </button>
      </aside>

      <div
        class="flex-1 min-w-0"
        :class="servedTab === 'stock' ? 'max-w-5xl' : 'max-w-3xl'"
      >
        <!-- Recently served (reinstate) — default view -->
        <div v-if="servedTab === 'recent' && reinstateEnabled">
          <p v-if="servedLoading" class="text-gray-600">
            Loading served orders…
          </p>
          <p v-else-if="!servedKots.length" class="text-gray-600">
            No orders served in the last {{ reinstateWindowHours }} hours.
          </p>
          <div v-else class="space-y-3">
            <div
              v-for="s in servedKots"
              :key="s.name"
              class="flex items-center justify-between gap-4 rounded-xl bg-white shadow p-4"
            >
              <div class="min-w-0">
                <div class="flex items-center gap-2 flex-wrap">
                  <span
                    class="rounded-full bg-gray-900 text-white px-3 py-0.5 text-lg font-extrabold leading-none"
                  >
                    #{{ orderLabel(s) }}
                  </span>
                  <span
                    v-if="s.waiter_name"
                    class="rounded-full bg-[#2563EB] text-white px-2 py-0.5 text-xs font-bold leading-none"
                  >
                    {{ s.waiter_name }}
                  </span>
                  <span class="text-sm text-gray-500">
                    {{ s.restaurant_table || "Takeaway" }}
                  </span>
                </div>
                <div class="mt-1 text-xs text-gray-500">
                  Served {{ servedTimeLabel(s) }} ·
                  {{ (s.kot_items && s.kot_items.length) || 0 }} item(s)
                </div>
              </div>
              <button
                type="button"
                :disabled="reinstatingKot === s.name"
                @click="reinstateKot(s)"
                class="shrink-0 rounded-md border-2 border-[#DC2626] px-4 py-2 font-semibold text-[#991B1B] hover:bg-[#FEF2F2] disabled:opacity-50"
              >
                {{ reinstatingKot === s.name ? "Undoing…" : "Reinstate" }}
              </button>
            </div>
          </div>
        </div>

        <!-- Cancelled / Deleted orders (2026-09-19), one day at a time. -->
        <div v-else-if="servedTab === 'cancelled' || servedTab === 'deleted'">
          <div class="rounded-xl bg-white shadow p-4">
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h2 class="text-lg font-bold text-gray-900">
                  {{ servedTab === "deleted" ? "Deleted Orders" : "Cancelled Orders" }}
                </h2>
                <p class="text-xs text-gray-500">
                  {{ production || "All" }} · {{ removedDate }} ·
                  {{
                    servedTab === "deleted"
                      ? "removed by a manager without asking the kitchen"
                      : "accepted by the kitchen, pulled before cooking, or cancelled by the waiter"
                  }}
                </p>
              </div>
              <input
                type="date"
                v-model="removedDate"
                :max="todayIso()"
                @change="fetchRemovedOrders"
                class="rounded-md border border-gray-300 px-2 py-1 text-sm"
              />
            </div>
          </div>

          <p v-if="removedLoading" class="mt-3 text-sm text-gray-500">Loading…</p>
          <p v-else-if="!removedList.length" class="mt-3 text-sm text-gray-600">
            No {{ servedTab === "deleted" ? "deleted" : "cancelled" }} orders on this day.
          </p>
          <div v-else class="mt-3 space-y-3">
            <div
              v-for="r in removedList"
              :key="r.kot"
              class="rounded-xl bg-white shadow p-4 border-l-4"
              :class="servedTab === 'deleted' ? 'border-red-600' : 'border-amber-500'"
            >
              <div class="flex items-center gap-2 flex-wrap">
                <span
                  class="rounded-full bg-gray-900 text-white px-3 py-0.5 text-lg font-extrabold leading-none"
                >
                  #{{ orderLabel(r) }}
                </span>
                <span
                  v-if="r.waiter_name"
                  class="rounded-full bg-[#2563EB] text-white px-2 py-0.5 text-xs font-bold leading-none"
                >
                  {{ r.waiter_name }}
                </span>
                <span class="text-sm text-gray-500">{{ r.table || "Takeaway" }}</span>
                <span
                  v-if="r.was_served"
                  class="rounded-full bg-green-100 text-green-800 px-2 py-0.5 text-xs font-semibold"
                >
                  Was served
                </span>
                <span class="ml-auto text-xs text-gray-500">{{ timeLabel(r.removed_at) }}</span>
              </div>
              <div class="mt-2 text-sm text-gray-700">
                <template v-if="servedTab === 'deleted'">
                  Deleted by <span class="font-semibold">{{ r.removed_by || "a manager" }}</span>
                </template>
                <template v-else-if="r.by_waiter">
                  Cancelled by the waiter
                </template>
                <template v-else>
                  Cancelled by <span class="font-semibold">{{ r.removed_by || "a captain" }}</span>
                  <span v-if="r.accepted_by"> · accepted by {{ r.accepted_by }}</span>
                  <span v-else> · before cooking started</span>
                </template>
              </div>
              <div
                v-if="r.reason"
                class="mt-1 rounded-md bg-gray-50 px-3 py-1.5 text-sm text-gray-800"
              >
                <span class="font-semibold">Reason:</span> {{ r.reason }}
              </div>
              <ul class="mt-2 text-sm text-gray-800 space-y-0.5">
                <li v-for="(it, idx) in r.items" :key="idx">
                  <span class="font-semibold">{{ it.quantity }}×</span> {{ it.item_name }}
                  <span v-if="it.comments" class="text-gray-500"> — {{ it.comments }}</span>
                </li>
              </ul>
            </div>
          </div>
        </div>

        <!-- Items sold summary (2026-07-23): per-item quantities +
             per-waiter, printable for end-of-day accounting. -->
        <div v-else-if="servedTab === 'summary'">
          <div class="rounded-xl bg-white shadow p-4">
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <h2 class="text-lg font-bold text-gray-900">Items Sold</h2>
                <p class="text-xs text-gray-500">
                  {{ production || "All" }} · {{ summaryDate }}
                </p>
              </div>
              <div class="flex items-center gap-2">
                <input
                  type="date"
                  v-model="summaryDate"
                  :max="todayIso()"
                  @change="fetchServedSummary"
                  class="rounded-md border border-gray-300 px-2 py-1 text-sm"
                />
                <button
                  type="button"
                  @click="printServedSummary"
                  :disabled="!servedSummary || !servedSummary.items.length"
                  class="rounded-md bg-gray-900 text-white px-3 py-1.5 text-sm font-semibold hover:bg-gray-700 disabled:opacity-50"
                >
                  Print
                </button>
              </div>
            </div>

            <p v-if="summaryLoading" class="mt-3 text-sm text-gray-500">
              Loading summary…
            </p>
            <template v-else-if="servedSummary && servedSummary.items.length">
              <div class="mt-3 flex items-center gap-3 flex-wrap text-sm">
                <span class="rounded-lg bg-gray-100 px-3 py-1 font-semibold">
                  Total qty: {{ fmtQty(servedSummary.total_qty) }}
                </span>
                <span class="rounded-lg bg-gray-100 px-3 py-1 font-semibold">
                  {{ servedSummary.distinct_items }} item(s)
                </span>
                <span class="rounded-lg bg-gray-100 px-3 py-1 font-semibold">
                  {{ servedSummary.ticket_count }} ticket(s)
                </span>
              </div>
              <ul class="mt-3 divide-y divide-gray-100">
                <li
                  v-for="it in servedSummary.items"
                  :key="it.item_name"
                  class="flex items-center justify-between py-1.5"
                >
                  <span class="text-gray-800">{{ it.item_name }}</span>
                  <span class="font-bold text-gray-900">{{
                    fmtQty(it.total_qty)
                  }}</span>
                </li>
              </ul>
              <div v-if="servedSummary.by_waiter.length" class="mt-4">
                <button
                  type="button"
                  @click="showWaiterBreakdown = !showWaiterBreakdown"
                  class="text-sm font-semibold text-blue-700"
                >
                  {{ showWaiterBreakdown ? "Hide" : "Show" }} by waiter
                </button>
                <div v-if="showWaiterBreakdown" class="mt-2 space-y-2">
                  <div
                    v-for="w in servedSummary.by_waiter"
                    :key="w.waiter"
                    class="rounded-lg bg-gray-50 p-2"
                  >
                    <div
                      class="flex items-center justify-between text-sm font-semibold text-gray-800"
                    >
                      <span>{{ w.waiter }}</span>
                      <span>{{ fmtQty(w.total_qty) }}</span>
                    </div>
                    <ul class="mt-1 text-xs text-gray-600">
                      <li
                        v-for="it in w.items"
                        :key="it.item_name"
                        class="flex items-center justify-between"
                      >
                        <span>{{ it.item_name }}</span>
                        <span>{{ fmtQty(it.qty) }}</span>
                      </li>
                    </ul>
                  </div>
                </div>
              </div>
            </template>
            <p v-else class="mt-3 text-sm text-gray-500">
              No items sold on this day.
            </p>
          </div>
        </div>

        <!-- Bar stock handover sheet (2026-09-18). The card is sized to the
             space left in the window (stockPanelHeight, measured) so the page
             itself never scrolls: the list scrolls inside it under a sticky
             column header, and pages keep it short. Print still prints ALL
             rows, not just the page on screen. -->
        <div v-else-if="servedTab === 'stock'">
          <div
            ref="stockPanel"
            class="rounded-xl bg-white shadow p-4 flex flex-col"
            :style="stockPanelHeight ? { maxHeight: stockPanelHeight + 'px' } : null"
          >
            <div class="shrink-0 flex items-start justify-between gap-3 flex-wrap">
              <div class="min-w-0">
                <h2 class="text-lg font-bold text-gray-900">Stock Report</h2>
                <p v-if="stockReport && stockReport.has_session" class="text-xs text-gray-500">
                  {{ production }} · opened
                  {{ fmtWhen(stockReport.opened_at) }} by
                  {{ stockReport.opened_by_name }}
                  <span v-if="stockReport.status === 'Closed'">
                    · closed {{ fmtWhen(stockReport.closed_at) }}</span
                  >
                </p>
              </div>
              <div class="flex items-center gap-2 flex-wrap">
                <label class="flex items-center gap-1 text-xs text-gray-600">
                  <input
                    type="checkbox"
                    v-model="stockShowAll"
                    @change="fetchStockReport"
                  />
                  Show all items
                </label>
                <button
                  type="button"
                  @click="fetchStockReport"
                  class="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-700 hover:bg-gray-100"
                >
                  Generate
                </button>
                <button
                  type="button"
                  @click="printStockReport"
                  :disabled="!stockReport || !stockReport.rows || !stockReport.rows.length"
                  class="rounded-md bg-gray-900 text-white px-3 py-1.5 text-sm font-semibold hover:bg-gray-700 disabled:opacity-50"
                >
                  Print
                </button>
              </div>
            </div>

            <p v-if="stockLoading" class="mt-3 shrink-0 text-sm text-gray-500">
              Loading stock…
            </p>

            <div
              v-else-if="stockReport && !stockReport.has_session"
              class="mt-3 shrink-0 rounded-lg bg-amber-50 border border-amber-300 p-3 text-sm text-amber-900"
            >
              The bar has not been opened yet, so there is no starting stock to
              compare against. Open the bar to begin.
            </div>

            <template v-else-if="stockReport && stockReport.rows">
              <div class="mt-3 shrink-0 flex items-center gap-3 flex-wrap text-sm">
                <span class="rounded-lg bg-gray-100 px-3 py-1 font-semibold">
                  {{ stockReport.totals.line_count }} item(s)
                </span>
                <span class="rounded-lg bg-gray-100 px-3 py-1 font-semibold">
                  {{ stockReport.totals.moved_count }} moved
                </span>
                <span
                  v-if="stockReport.totals.negative_count"
                  class="rounded-lg bg-red-100 text-red-800 px-3 py-1 font-semibold"
                >
                  {{ stockReport.totals.negative_count }} negative
                </span>
                <span v-if="stockReport.hidden_count" class="text-xs text-gray-500">
                  {{ stockReport.hidden_count }} idle item(s) hidden
                </span>
                <input
                  v-model="stockSearch"
                  type="search"
                  placeholder="Find an item…"
                  class="ml-auto w-48 rounded-md border border-gray-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-gray-400"
                />
              </div>

              <!-- The only scrolling region. min-h-0 lets it shrink inside
                   the capped card instead of pushing the card taller. -->
              <div
                ref="stockScroll"
                class="mt-3 min-h-0 flex-auto overflow-auto border-t border-gray-100"
              >
                <table class="w-full text-sm">
                  <thead class="sticky top-0 z-[1] bg-white">
                    <tr class="text-left text-xs uppercase text-gray-500 shadow-[0_1px_0_#e5e7eb]">
                      <th class="py-1.5 pr-2">Item</th>
                      <th class="py-1.5 pr-2">Group</th>
                      <th class="py-1.5 pr-2 text-right">Opening</th>
                      <th class="py-1.5 pr-2 text-right">Sold</th>
                      <th class="py-1.5 text-right">Expected</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-gray-100">
                    <tr v-for="r in stockPageRows" :key="r.item_code">
                      <td class="py-1 pr-2 text-gray-800">
                        {{ r.item_name }}
                        <span class="text-xs text-gray-400">{{ r.stock_uom }}</span>
                      </td>
                      <td class="py-1 pr-2 text-xs text-gray-500">
                        {{ r.item_group }}
                      </td>
                      <td class="py-1 pr-2 text-right">{{ fmtQty(r.opening_qty) }}</td>
                      <td class="py-1 pr-2 text-right font-semibold">
                        {{ fmtQty(r.sold_qty) }}
                      </td>
                      <td
                        class="py-1 text-right font-bold"
                        :class="r.is_negative ? 'text-red-600' : 'text-gray-900'"
                      >
                        {{ fmtQty(r.expected_qty) }}
                      </td>
                    </tr>
                    <tr v-if="!stockPageRows.length">
                      <td colspan="5" class="py-6 text-center text-sm text-gray-500">
                        No item matches "{{ stockSearch }}".
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- Pager -->
              <div
                class="shrink-0 mt-2 pt-2 border-t border-gray-100 flex items-center justify-between gap-3 flex-wrap text-sm"
              >
                <span class="text-gray-600">
                  <template v-if="stockFilteredRows.length">
                    {{ stockRangeStart }}–{{ stockRangeEnd }} of
                    {{ stockFilteredRows.length }}
                  </template>
                  <template v-else>0 items</template>
                </span>
                <div class="flex items-center gap-1">
                  <button
                    type="button"
                    @click="goStockPage(1)"
                    :disabled="stockCurrentPage <= 1"
                    class="rounded-md border border-gray-300 px-2 py-1 font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                    title="First page"
                  >
                    «
                  </button>
                  <button
                    type="button"
                    @click="goStockPage(stockCurrentPage - 1)"
                    :disabled="stockCurrentPage <= 1"
                    class="rounded-md border border-gray-300 px-3 py-1 font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                  >
                    ‹ Prev
                  </button>
                  <span class="px-2 text-gray-700 whitespace-nowrap">
                    Page <strong>{{ stockCurrentPage }}</strong> of
                    {{ stockPageCount }}
                  </span>
                  <button
                    type="button"
                    @click="goStockPage(stockCurrentPage + 1)"
                    :disabled="stockCurrentPage >= stockPageCount"
                    class="rounded-md border border-gray-300 px-3 py-1 font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                  >
                    Next ›
                  </button>
                  <button
                    type="button"
                    @click="goStockPage(stockPageCount)"
                    :disabled="stockCurrentPage >= stockPageCount"
                    class="rounded-md border border-gray-300 px-2 py-1 font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-40"
                    title="Last page"
                  >
                    »
                  </button>
                </div>
                <label class="flex items-center gap-1 text-xs text-gray-600">
                  Rows
                  <select
                    v-model="stockRowsSetting"
                    class="rounded-md border border-gray-300 px-1 py-0.5 text-sm"
                  >
                    <option value="fit">Fit screen</option>
                    <option :value="20">20</option>
                    <option :value="50">50</option>
                    <option :value="100">100</option>
                  </select>
                </label>
              </div>

              <div class="shrink-0 mt-2 flex items-end justify-between gap-3">
                <p class="text-xs text-gray-500">
                  Expected = what should be on the shelf now. POS sales are only
                  deducted from stock when the shift is consolidated, so this
                  already allows for drinks sold but not yet deducted.
                </p>
                <button
                  v-if="stockReport.status === 'Open'"
                  type="button"
                  @click="closeBar"
                  :disabled="closingBar"
                  class="shrink-0 rounded-md border border-gray-300 px-3 py-1.5 text-sm font-semibold text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                >
                  {{ closingBar ? "Closing…" : "Close the bar" }}
                </button>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Card action dialog (2026-07-16): replaces the per-card buttons. -->
    <div
      v-if="showActionModal"
      class="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4"
      @click.self="closeActions"
    >
      <div class="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
        <h2 class="text-2xl font-extrabold text-gray-900">
          #{{ actionKot ? orderLabel(actionKot) : "" }}
        </h2>
        <p v-if="actionKot && actionKot.waiter_name" class="text-sm text-gray-500 mt-1">
          Waiter: {{ actionKot.waiter_name }}
        </p>

        <div
          v-if="actionKot && actionKot.change_status === 'Awaiting Confirmation'"
          class="mt-4 rounded border-2 border-[#F59E0B] bg-[#FFFBEB] px-3 py-2 text-sm font-semibold text-[#92400E]"
        >
          On hold — waiting for the waiter to confirm with the customer.
        </div>

        <!-- Waiter sent something back: the only next step is to accept it. -->
        <div v-if="hasPendingResponse(actionKot)" class="mt-4">
          <div
            class="rounded border-2 px-3 py-2 text-sm"
            :class="
              actionKot.change_status === 'Cancelled'
                ? 'border-[#DC2626] bg-[#FEF2F2] text-[#991B1B]'
                : 'border-[#2563EB] bg-[#EFF6FF] text-[#1E3A8A]'
            "
          >
            <div class="font-bold">
              {{
                actionKot.change_status === "Cancelled"
                  ? "Order cancelled by the waiter"
                  : actionKot.change_status === "Updated"
                  ? "Special request updated"
                  : "Confirmed by the waiter"
              }}
            </div>
            <div v-if="actionKot.change_response" class="mt-1">
              {{ actionKot.change_response }}
            </div>
          </div>
          <button
            type="button"
            :disabled="acceptingKot === actionKot.name"
            @click="acceptChange(actionKot)"
            class="mt-3 w-full py-3 rounded-md bg-gray-900 text-white font-semibold hover:bg-black disabled:opacity-50"
          >
            {{
              acceptingKot === actionKot.name
                ? "Accepting…"
                : actionKot.change_status === "Cancelled"
                ? "Accept & remove"
                : "Accept"
            }}
          </button>
          <button
            type="button"
            @click="closeActions"
            class="mt-2 w-full py-2 text-gray-600 hover:text-gray-800"
          >
            Close
          </button>
        </div>

        <!-- Captain -> kitchen cancellation (2026-07-31). Takes priority
             over every other action: the order is LOCKED in the POS until
             this is accepted, so nobody can pay that table until a cook
             taps here. Shown as its own branch rather than another button
             in the list so it cannot be missed on a busy board. -->
        <div
          v-else-if="actionKot && actionKot.cancel_status === 'Awaiting Kitchen'"
          class="mt-5"
        >
          <div class="rounded border-2 border-[#DC2626] bg-[#FEF2F2] px-3 py-3">
            <div class="font-bold text-[#991B1B] text-lg">
              {{
                actionKot.cancel_scope === "Items"
                  ? "ITEMS CANCELLED"
                  : "ORDER CANCELLED"
              }}
            </div>
            <div
              v-if="actionKot.cancel_scope === 'Items'"
              class="mt-2 text-[#991B1B]"
            >
              <div
                v-for="(it, i) in cancelledItems(actionKot)"
                :key="i"
                class="font-semibold"
              >
                • {{ it.quantity }}x {{ it.item_name || it.item_code }}
              </div>
            </div>
            <div class="mt-2 text-[#991B1B]">
              <span class="font-semibold">Reason:</span>
              {{ actionKot.cancel_reason }}
            </div>
            <div class="mt-1 text-xs text-[#991B1B] italic">
              Requested by {{ actionKot.cancel_requested_by }}
            </div>
          </div>
          <button
            type="button"
            :disabled="acceptingCancel === actionKot.name"
            @click="acceptCancellation(actionKot)"
            class="mt-3 w-full py-3 rounded-md bg-[#DC2626] text-white font-semibold hover:bg-[#B91C1C] disabled:opacity-50"
          >
            {{
              acceptingCancel === actionKot.name
                ? "Accepting…"
                : actionKot.cancel_scope === "Items"
                ? "Accept & remove items"
                : "Accept & remove order"
            }}
          </button>
          <button
            type="button"
            @click="closeActions"
            class="mt-2 w-full py-2 text-gray-600 hover:text-gray-800"
          >
            Close
          </button>
        </div>

        <div v-else class="mt-5 space-y-2">
          <button
            type="button"
            :disabled="actionKot && actionKot.change_status === 'Awaiting Confirmation'"
            @click="serveFromDialog"
            class="w-full py-3 rounded-md bg-blue-600 text-white font-semibold hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed"
          >
            {{ isCancelType(actionKot) ? "Confirm" : "Serve" }}
          </button>
          <button
            v-if="actionKot && actionKot.change_status !== 'Awaiting Confirmation'"
            type="button"
            @click="requestChangeFromDialog"
            class="w-full py-3 rounded-md border-2 border-[#F59E0B] text-[#92400E] font-semibold hover:bg-[#FFFBEB]"
          >
            Request change
          </button>
          <button
            type="button"
            @click="closeActions"
            class="w-full py-2 text-gray-600 hover:text-gray-800"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>

    <!-- Kitchen -> waiter change request modal (2026-07-16) -->
    <div
      v-if="showChangeModal"
      class="fixed inset-0 z-30 flex items-center justify-center bg-black/50 p-4"
    >
      <div class="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
        <h2 class="text-xl font-bold text-gray-900">Request a change</h2>
        <p class="mt-1 text-sm text-gray-500">
          The order goes on hold until the waiter checks with the customer.
        </p>

        <label class="mt-4 block text-sm font-medium text-gray-700">
          Item (optional)
        </label>
        <select
          v-model="changeItem"
          class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
        >
          <option value="">— whole order —</option>
          <option
            v-for="it in (changeKot && changeKot.kot_items) || []"
            :key="it.name"
            :value="it.item_name"
          >
            {{ it.item_name }}
          </option>
        </select>

        <label class="mt-4 block text-sm font-medium text-gray-700">
          What needs to change?
        </label>
        <textarea
          v-model="changeMessage"
          rows="3"
          placeholder="e.g. out of prawns — swap for chicken?"
          class="mt-1 w-full rounded-md border border-gray-300 px-3 py-2"
        ></textarea>

        <div class="mt-5 flex justify-end gap-3">
          <button
            type="button"
            @click="closeChangeRequest"
            class="rounded-md border border-gray-300 px-4 py-2 font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="button"
            :disabled="!changeMessage.trim() || changeSubmitting"
            @click="submitChangeRequest"
            class="rounded-md bg-[#F59E0B] px-4 py-2 font-semibold text-white hover:bg-[#D97706] disabled:opacity-50"
          >
            {{ changeSubmitting ? "Sending…" : "Send & hold" }}
          </button>
        </div>
      </div>
    </div>

    <!-- Alert Modal div start-->
    <div
      v-if="this.showModal"
      class="fixed inset-0 z-10 overflow-y-auto bg-gray-100"
    >
      <div class="flex items-center justify-center">
        <div class="w-full rounded-lg bg-white p-6 shadow-lg md:max-w-md">
          <p
            class="block text-left text-xl font-medium text-gray dark:text-gray"
          >
            <span
              class="w-3 h-3 rounded-full inline-block mr-1 bg-red-500"
            ></span>
            Not Permitted
          </p>
          <hr class="border-gray-200" />

          <p class="text-left text-xl mt-6 font-medium text-gray-500">
            Log in to access this page.
          </p>

          <div class="flex justify">
            <button
              @click="
                this.showModal = false;
                this.redirectToLogin();
              "
              class="mt-8 rounded bg-blue-500 px-3 py-2 text-white hover:bg-blue-600"
            >
              Login
            </button>
          </div>
        </div>
      </div>
    </div>
    <!-- Alert Modal div end-->

    <!-- Target-not-found banner -->
    <div
      v-if="targetError"
      class="mx-auto max-w-2xl mt-24 rounded-2xl border border-red-200 bg-red-50 p-8 text-center shadow"
    >
      <p class="text-2xl font-semibold text-red-700 mb-2">
        Kitchen display not available
      </p>
      <p class="text-base text-red-600">{{ targetError }}</p>
      <p class="text-sm text-gray-500 mt-4">
        Tried to open <code class="bg-white px-1 rounded">/Mosaic/{{ production }}</code>.
      </p>
    </div>

    <div
      v-else-if="viewMode === 'active'"
      class="grid grid-cols-1 gap-10 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
    >
      <div v-for="kot in this.kot" :key="kot.name">
        <div
          :class="[
            kot.color,
            { 'ury-served-flash': kot.served, 'ury-drag-over': dragOverKot === kot.name },
          ]"
          class="relative inline-block shadow-lg gap-4 p-3 rounded-2xl w-90 h-auto masonry-item cursor-pointer"
          style="margin-top: 28px"
          v-if="!kot.showDiv && kot.production === production"
          draggable="true"
          @dragstart="onDragStart(kot, $event)"
          @dragover.prevent="onDragOver(kot)"
          @dragleave="onDragLeave(kot)"
          @drop.prevent="onDrop(kot)"
          @dragend="onDragEnd"
          @click="openActions(kot)"
        >
          <!-- Protruding badges (2026-07-16): order number + waiter. They sit
               half outside the top edge so they're the first thing a cook sees
               scanning the board. The card's 28px top margin leaves room. -->
          <div
            class="absolute -top-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 whitespace-nowrap"
          >
            <span
              class="rounded-full bg-gray-900 text-white border-4 border-white shadow-lg px-4 py-1 text-xl font-extrabold leading-none"
            >
              #{{ orderLabel(kot) }}
            </span>
            <span
              v-if="kot.waiter_name"
              class="rounded-full bg-[#2563EB] text-white border-4 border-white shadow-lg px-3 py-1 text-sm font-bold leading-none max-w-[9rem] truncate"
              :title="kot.waiter_name"
            >
              {{ kot.waiter_name }}
            </span>
          </div>
          <div class="w-64 check">
              <!-- Card Header: Table. The order number + waiter live on the
                   protruding badges above, so they're not repeated here.
                   The click handler is on the CARD (not here) so tapping
                   anywhere — including the "Tap for options" strip — opens
                   the action dialog. 2026-07-16. -->
              <div class="flex justify-between">
                <div class="text-sm w-48">
                  <span
                    v-if="kot.tableortakeaway !== 'Takeaway'"
                    class="text-sm font-medium text-[#6B7280]"
                    >Table
                  </span>
                  <span class="text-black-500 font-semibold">
                    {{ kot.tableortakeaway }}
                    <span class="text-sm font-medium text-[#6B7280]"
                      >( {{ kot.user }} )</span
                    ></span
                  ><br />
                  <span v-if="kot.is_aggregator" class="text-sm font-medium text-[#6B7280]">Aggregator</span>
                  <span v-if="kot.is_aggregator" class="text-black-500 ml-2 font-semibold"
                    >{{ kot.customer_name }}
                  </span><br v-if="kot.is_aggregator" />
                  <span v-if="kot.is_aggregator" class="text-sm font-medium text-[#6B7280]">Aggregator ID</span>
                  <span v-if="kot.is_aggregator" class="text-black-500 ml-2 font-semibold"
                    >{{ kot.aggregator_id }}
                  </span><br v-if="kot.is_aggregator"/>
                  <span
                    class="text-black-500 font-semibold"
                    v-if="
                      kot.type === 'Partially cancelled' ||
                      kot.type === 'Cancelled'
                    "
                  >
                    ( {{ kot.type }} )</span
                  >
                </div>
                <div
                  :class="kot.timecolor"
                  class="font-inter font-semibold text-2xl leading-10"
                >
                  {{ kot.timeRemaining }}
                </div>
              </div>
              <div
                v-if="kot.type === 'Duplicate'"
                class="text-[#DC0000] font-medium"
              >
                ( Duplicate KOT ( CHECK WITH CAPTAIN ) )
              </div>
              <!-- Order-level note. Highlighted so the kitchen can't miss
                   it on a busy screen (2026-07-16). -->
              <div
                v-show="kot.comments"
                class="mt-1 rounded border-2 border-[#F59E0B] bg-[#FEF3C7] px-2 py-1 text-[#92400E] font-bold"
              >
                ORDER NOTE: {{ kot.comments }}
              </div>
              <div></div>
              <div>
                <div
                  class="font-semibold justify-between items-center mt-2"
                  v-for="kotitem in sortedKotItems(kot)"
                  :key="kotitem.name"
                >
                  <div
                    @click.stop="toggleItemStrikeThrough(kotitem, kot)"
                    :class="{
                      'line-through text-green-700': kotitem.striked,
                    }"
                    class="flex font-semibold justify-between items-center"
                  >
                    <div>
                      <span class="ml-2 text-black-100">{{
                        kotitem.item_name
                      }}<span v-show="kotitem.indicate_course" class="text-sm text-gray-500 ml-1"> ( {{kotitem.course}} )</span>
                      </span
                      ><br />
                      <span
                        class="ml-2 text-black-100"
                        v-if="
                          kot.type === 'Partially cancelled' ||
                          kot.type === 'Cancelled'
                        "
                        >[Old Qty = {{ kotitem.quantity }}]</span
                      >
                    </div>
                    <div>
                      <span class="ml-2 text-black-100">{{ kotitem.qty }}</span>
                    </div>
                  </div>
                  <div>
                    <!-- Per-item special instruction. Loud styling so a cook
                         scanning the board catches it (2026-07-16). -->
                    <p
                      v-show="kotitem.comments"
                      class="ml-2 mt-1 rounded border-2 border-[#DC2626] bg-[#FEE2E2] px-2 py-1 text-[#991B1B] font-bold"
                    >
                      NOTE: {{ kotitem.comments }}
                    </p>
                    <hr class="my-1 border-gray-200 mt-2" />
                  </div>
                </div>
              </div>

              <!-- Captain -> kitchen cancellation (2026-07-31). Red and
                   first, above the change-request panel: this is the cook
                   being told to STOP, and the table cannot be paid until
                   somebody accepts it. -->
              <div
                v-if="kot.cancel_status === 'Awaiting Kitchen'"
                class="mt-3 rounded border-2 border-[#DC2626] bg-[#FEF2F2] px-2 py-2"
              >
                <div class="font-bold text-[#991B1B]">
                  {{
                    kot.cancel_scope === "Items"
                      ? "ITEMS CANCELLED"
                      : "ORDER CANCELLED"
                  }}
                </div>
                <div
                  v-if="kot.cancel_scope === 'Items'"
                  class="text-[#991B1B] text-sm mt-1 font-semibold"
                >
                  <div v-for="(it, i) in cancelledItems(kot)" :key="i">
                    • {{ it.quantity }}x {{ it.item_name || it.item_code }}
                  </div>
                </div>
                <div class="text-[#991B1B] text-sm mt-1">
                  Reason: {{ kot.cancel_reason }}
                </div>
                <div class="text-[#991B1B] text-xs mt-1 italic">
                  Tap the card to accept.
                </div>
              </div>

              <!-- Kitchen -> waiter change request state (2026-07-16) -->
              <div
                v-else-if="kot.change_status === 'Awaiting Confirmation'"
                class="mt-3 rounded border-2 border-[#F59E0B] bg-[#FFFBEB] px-2 py-2"
              >
                <div class="font-bold text-[#92400E]">
                  ON HOLD — AWAITING CONFIRMATION
                </div>
                <div class="text-[#92400E] text-sm mt-1">
                  <span v-if="kot.change_item">{{ kot.change_item }}: </span
                  >{{ kot.change_request }}
                </div>
                <div class="text-[#92400E] text-xs mt-1 italic">
                  Waiting for the waiter to check with the customer.
                </div>
              </div>
              <!-- Waiter answered — the kitchen must Accept before the card
                   clears, so nothing is missed. 2026-07-16. -->
              <div
                v-else-if="kot.change_status === 'Confirmed'"
                class="mt-3 rounded border-2 border-[#16A34A] bg-[#F0FDF4] px-2 py-2 text-[#166534]"
              >
                <div class="font-bold">CONFIRMED — proceed</div>
                <div v-if="kot.change_response" class="text-sm mt-1">
                  {{ kot.change_response }}
                </div>
                <div class="text-xs mt-1 italic">Tap the card to accept.</div>
              </div>
              <div
                v-else-if="kot.change_status === 'Updated'"
                class="mt-3 rounded border-2 border-[#2563EB] bg-[#EFF6FF] px-2 py-2 text-[#1E3A8A]"
              >
                <div class="font-bold">SPECIAL REQUEST UPDATED</div>
                <div v-if="kot.change_response" class="text-sm mt-1">
                  {{ kot.change_response }}
                </div>
                <div class="text-xs mt-1 italic">
                  Item note updated above. Tap the card to accept.
                </div>
              </div>
              <div
                v-else-if="kot.change_status === 'Cancelled'"
                class="mt-3 rounded border-2 border-[#DC2626] bg-[#FEF2F2] px-2 py-2 text-[#991B1B]"
              >
                <div class="font-bold">ORDER CANCELLED — stop cooking</div>
                <div v-if="kot.change_response" class="text-sm mt-1">
                  {{ kot.change_response }}
                </div>
                <div class="text-xs mt-1 italic">
                  Tap the card to accept; it will leave the board.
                </div>
              </div>

              <!-- No action buttons on the card any more (2026-07-16) — they
                   made every card look like a form. Tap the card to open the
                   Serve / Request change dialog. -->
              <div class="mt-3 pt-2 border-t border-black/10 text-center text-xs text-[#6B7280] italic">
                Tap for options
              </div>

          </div>
          <!-- You can add more item/quantity pairs here as needed -->
        </div>
      </div>
    </div>

    <!-- Audio Alert Message -->
    <div
      v-if="showAudioAlertMessage"
      class="absolute top-1 left-1/2 transform -translate-x-1/2 p-2 font-bold text-2xl text-red-500 text-center"
    >
      Audio notifications disabled. Click anywhere to enable.
    </div>

    <div
      v-if="statusMessage"
      :class="[
        'fixed',
        'bottom-10',
        'right-10',
        'p-4',
        'rounded',
        'text-white',
        {
          'bg-green-500': isOnline,
          'bg-red-500': !isOnline,
        },
      ]"
      @transitionend="handleTransitionEnd"
    >
      {{ statusMessage }}
    </div>
    </div>
  </div>
</template>

<script>
import { FrappeApp } from "frappe-js-sdk";
import {
  startConnectivityWatch,
  stopConnectivityWatch,
} from "../lib/connectivity";
import Masonry from "masonry-layout";
import io from "socket.io-client";
import Header from "./Header.vue";
import UnitPicker from "./UnitPicker.vue";

let host = window.location.hostname;
let port = window.location.port;
let protocol = window.location.protocol;
let url = port ? `${protocol}//${host}:${port}` : `${protocol}//${host}`;
window.globalSiteName = '';
let socket; 

async function fetchAndSetSiteName() {
    try {
        const response = await fetch('/api/method/ury.ury.api.ury_kot_display.get_site_name', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        const data = await response.json();
        window.globalSiteName = data.message.site_name;
        // console.log('Global Site Name:', window.globalSiteName);
    } catch (error) {
        console.error('Failed to fetch site name:', error);
    }
}

async function initializeSocket() {
    await fetchAndSetSiteName();
    if (window.globalSiteName) {
        let site = window.globalSiteName;
        let site_url = `${url}/${site}`;
        socket = io(site_url,{ withCredentials: true });
        console.log("socket == >",socket)
        socket.on('connect_error', (err) => {
            console.error("Socket connection error:", err);
        }); 
        socket.on('connect', () => {
            console.log('Socket connected:', socket.connected);
        });
    } else {
        console.error('Site name is not set. Socket cannot be initialized.');
    }
}

initializeSocket(); // Initialize the socket after fetching the site name


const frappe = new FrappeApp(url);
export default {
  // inject: ["$auth", "$socket"],
  components: { Header, UnitPicker },
  data() {
    return {
      kot: [],
      masonry: null,
      call: frappe.call(),
      // Kitchen -> waiter change request modal (2026-07-16)
      showChangeModal: false,
      changeKot: null,
      changeItem: "",
      changeMessage: "",
      changeSubmitting: false,
      // Tap-a-card action dialog (2026-07-16)
      showActionModal: false,
      actionKot: null,
      // Served-orders view + reinstate (2026-07-16)
      viewMode: "active",
      servedKots: [],
      servedLoading: false,
      reinstatingKot: null,
      // Served sub-view sidebar (2026-07-23): "recent" (reinstate) is the
      // default; "summary" is the Items Sold report. reinstate config comes
      // from the URY Production Unit (enable + window hours).
      servedTab: "recent",
      reinstateEnabled: true,
      reinstateWindowHours: 3,
      // Bar stock handover (2026-09-18). Only a URY Production Unit whose
      // unit_type is "Bar" gets any of this; kitchens are untouched.
      isBarUnit: false,
      barSession: null,
      openingBar: false,
      closingBar: false,
      stockReport: null,
      stockLoading: false,
      stockShowAll: false,
      // Stock list paging (2026-09-18): keep the sheet inside the window.
      stockSearch: "",
      stockPage: 1,
      // "fit" = as many rows as fit the card without scrolling (stockFitRows,
      // measured); a number = a fixed page size the barman picked.
      stockRowsSetting: "fit",
      stockFitRows: 15,
      stockPanelHeight: null,
      // Served-day sold summary (2026-07-23)
      servedSummary: null,
      summaryDate: "",
      // Cancelled / Deleted lists (2026-09-19)
      removedOrders: null,
      removedDate: "",
      removedLoading: false,
      removedTabs: [
        { key: "cancelled", label: "Cancelled" },
        { key: "deleted", label: "Deleted" },
      ],
      summaryLoading: false,
      showWaiterBreakdown: false,
      // Drag-to-reorder (2026-07-16)
      draggingKot: null,
      dragOverKot: null,
      acceptingKot: null,
      acceptingCancel: null,
      production: "",
      branch: "",
      kds_routing_mode: "Menu Course",
      kot_channel: "",
      // Realtime channel for a waiter's reply to a kitchen change request
      // (2026-07-23) — so the card updates without a manual reload.
      change_channel: "",
      cancel_channel: "",
      clickedItems: new Set(),
      struckThroughItems: {},
      loggeduser: "",
      showModal: false,
      kot_alert_time: "",
      showAudioAlertMessage: false,
      audio_alert: 0,
      isOnline: navigator.onLine,
      statusMessage: "",
      daily_order_number:0,
      targetError: "",
      // Screen access (2026-09-18). boardActive stays false on the /Mosaic
      // picker and on a screen the user may not open, so nothing is
      // fetched or subscribed behind the picker.
      myUnits: [],
      myDepartments: [],
      myFullName: "",
      unitsLoaded: false,
      unitPickerMode: "",
      boardActive: false,
      service_policy_time: 0,
      _tickHandle: null,
      _refreshHandle: null,
      // Guards the 30s board refresh against overlapping when the server
      // is slow — see the interval in mounted(). (2026-09-24)
      _refreshInFlight: false,
    };
  },
  methods: {
    /** Ring for a new order. Uses the POS Profile's configured sound when
     *  one is set, otherwise the bundled default bell — so the kitchen has
     *  an audible alert out of the box. 2026-07-16. */
    playAlertSound(path) {
      try {
        const src = path
          ? window.location.origin + path
          : "/assets/ury/URYMosaic/sounds/kitchen-bell.wav";
        const audio = new Audio(src);
        audio.play().catch(() => {
          // Autoplay blocked until the user interacts with the page — the
          // existing "click anywhere to enable" hint covers this.
          this.showAudioAlertMessage = true;
        });
      } catch (e) {
        /* ignore */
      }
    },
    /** Always ring on a new order (2026-07-16).
     *
     *  This used to gate on `custom_kot_alert`, which sounded reasonable but
     *  is a **Check** field — so it's ALWAYS 0 or 1, never null. There is no
     *  "unset" state to fall back on, which meant every site that hadn't
     *  explicitly ticked it sat at 0 and got no sound at all. The bell is
     *  meant to be the out-of-the-box default, so it always rings; the POS
     *  Profile's `custom_kot_alert_sound` overrides WHICH sound plays, not
     *  whether it plays. */
    shouldRing() {
      return true;
    },
    auth() {
      return new Promise((resolve, reject) => {
        const auth = frappe.auth();
        auth
          .getLoggedInUser()
          .then((user) => {
            this.loggeduser = user;
            resolve();
          })
          .catch((error) => {
            console.error(error);
            reject(error);
          });
      });
    },
    fetchKOT() {
      return new Promise((resolve, reject) => {
        try {
          // Pass the URL target (production-name OR department OR
          // "All") so the backend can decide how to filter. In
          // Menu Course mode the target is a department name and
          // the backend trims each KOT's kot_items accordingly;
          // in URY Production Unit mode the target is ignored
          // server-side and the v-if filter below still works.
          this.call
            .get("ury.ury.api.ury_kot_display.kot_list", {
              target: this.production,
            })
            .then((result) => {
              const msg = result.message || {};
              if (msg.access_denied) {
                this.boardActive = false;
                this.kot = [];
                this.unitPickerMode = this.screenCount ? "denied" : "none";
                resolve();
                return;
              }
              if (msg.error) {
                this.targetError = msg.error;
                this.kot = [];
                resolve();
                return;
              }
              this.targetError = "";
              this.branch = msg.Branch;
              this.kot_alert_time = msg.kot_alert_time;
              this.service_policy_time = parseInt(msg.service_policy_time) || 0;
              this.audio_alert = msg.audio_alert;
              this.daily_order_number = msg.daily_order_number;
              this.kds_routing_mode = msg.kds_routing_mode || "Menu Course";
              // Cache the branch: the realtime channel names are derived
              // from it, and without it an offline boot cannot even name the
              // channel to subscribe to. See restoreCachedBranch(). (2026-09-24)
              try {
                localStorage.setItem("ury_kds_branch", this.branch || "");
              } catch (e) {
                /* private mode / storage disabled — non-fatal */
              }
              this.kot_channel = `kot_update_${this.branch}_${this.production}`;
              this.change_channel = `kot_change_resolved_${this.branch}_${this.production}`;
              this.cancel_channel = `kot_cancel_requested_${this.branch}_${this.production}`;
              // Stamp the moment we received each KOT so the timer can tick
              // forward from the server-computed elapsed_seconds base.
              const fetchedAt = Date.now();
              const list = msg.KOT || [];
              list.forEach((k) => {
                k._fetchedAt = fetchedAt;
              });
              this.kot = list;
              // Restore the cook's drag order so a refresh/poll doesn't
              // shuffle the board back. 2026-07-16.
              this.applySavedOrder();
              this.updateQtyColorTable();
              this.updateTimeRemaining();
              this.masonryLoading();
              resolve();
            })
            .catch((error) => {
              // RESOLVE, don't reject. The boot path in mounted() subscribes
              // to the realtime KOT channel inside this promise's .then().
              // Rejecting here meant a kitchen screen that booted during an
              // outage never ran that block — so it subscribed to NOTHING and
              // stayed permanently deaf, even after the network came back,
              // until somebody reloaded it while online. That is a silent
              // "kitchen never sees the order" failure. The 30s safety-net
              // poll then repopulates the board on its own. (2026-09-24)
              console.error(error);
              resolve();
            });
        } catch (error) {
          console.error(error);
          resolve();
        }
      });
    },
    confirmOrder(kot) {
      const now = new Date();
      this.currentTime = now.toLocaleTimeString();
      this.call
        .post("ury.ury.api.ury_kot_display.confirm_cancel_kot", {
          name: kot.name,
          user: this.loggeduser,
        })
        .then((result) => {
          // kot.isHidden = !kot.isHidden;
          kot.showDiv = !kot.showDiv;
          // this.showDiv = false;

          this.removeAllItemsFromLocalStorage(kot);
          this.masonryLoading();
        })
        .catch((error) => console.error(error));
    },
    /** Order number shown on the card + the protruding badge. Uses the
     *  daily order number when the profile enables it, else the last 4 of
     *  the invoice name. 2026-07-16. */
    orderLabel(kot) {
      return this.daily_order_number
        ? kot.order_no
        : (kot.invoice || "").slice(-4);
    },

    // --- Drag to reorder the board (2026-07-16) ------------------------
    // Cooks want their own running order. The chosen sequence is kept in
    // localStorage per production, so a reload (or the 30s poll) doesn't
    // shuffle the board back.
    /**
     * Rebuild the realtime channel names from the branch cached on the last
     * successful fetch, so a screen that boots offline still subscribes and
     * wakes up by itself when the connection returns. A fresh fetch
     * overwrites these with authoritative values. (2026-09-24)
     */
    restoreCachedBranch() {
      if (this.branch) return;
      let cached = "";
      try {
        cached = localStorage.getItem("ury_kds_branch") || "";
      } catch (e) {
        cached = "";
      }
      if (!cached) return;
      this.branch = cached;
      this.kot_channel = `kot_update_${cached}_${this.production}`;
      this.change_channel = `kot_change_resolved_${cached}_${this.production}`;
      this.cancel_channel = `kot_cancel_requested_${cached}_${this.production}`;
    },
    orderStorageKey() {
      return "ury_kds_order_" + (this.production || "all");
    },
    savedOrder() {
      try {
        return JSON.parse(localStorage.getItem(this.orderStorageKey()) || "[]");
      } catch (e) {
        return [];
      }
    },
    persistOrder() {
      try {
        localStorage.setItem(
          this.orderStorageKey(),
          JSON.stringify(this.kot.map((k) => k.name))
        );
      } catch (e) {
        /* storage full / unavailable — ordering just won't persist */
      }
    },
    /** Re-sort freshly fetched KOTs onto the cook's saved sequence. Anything
     *  not in the saved list (a NEW order) goes to the front so it can't be
     *  buried at the bottom of a long board. */
    applySavedOrder() {
      const saved = this.savedOrder();
      if (!saved.length) return;
      const rank = new Map(saved.map((n, i) => [n, i]));
      this.kot.sort((a, b) => {
        const ra = rank.has(a.name) ? rank.get(a.name) : -1;
        const rb = rank.has(b.name) ? rank.get(b.name) : -1;
        return ra - rb;
      });
    },
    onDragStart(kot, event) {
      this.draggingKot = kot.name;
      try {
        event.dataTransfer.effectAllowed = "move";
        // Firefox needs data set for a drag to start at all.
        event.dataTransfer.setData("text/plain", kot.name);
      } catch (e) {
        /* ignore */
      }
    },
    onDragOver(kot) {
      if (this.draggingKot && this.draggingKot !== kot.name) {
        this.dragOverKot = kot.name;
      }
    },
    onDragLeave(kot) {
      if (this.dragOverKot === kot.name) this.dragOverKot = null;
    },
    onDrop(targetKot) {
      const from = this.kot.findIndex((k) => k.name === this.draggingKot);
      const to = this.kot.findIndex((k) => k.name === targetKot.name);
      this.dragOverKot = null;
      if (from < 0 || to < 0 || from === to) return;
      const [moved] = this.kot.splice(from, 1);
      this.kot.splice(to, 0, moved);
      this.persistOrder();
      this.masonryLoading();
    },
    onDragEnd() {
      this.draggingKot = null;
      this.dragOverKot = null;
    },

    /** Kitchen accepts whatever the waiter sent back. On a cancellation the
     *  card leaves the board. 2026-07-16. */
    async acceptChange(kot) {
      this.acceptingKot = kot.name;
      try {
        await this.call.post(
          "ury.ury.api.ury_kot_display.kitchen_ack_change",
          { kot: kot.name }
        );
        const wasCancelled = kot.change_status === "Cancelled";
        this.closeActions();
        if (wasCancelled) {
          kot.served = true; // reuse the collapse animation
          setTimeout(() => {
            kot.showDiv = true;
            this.masonryLoading();
          }, 620);
        } else {
          kot.change_status = "";
          kot.change_request = null;
          kot.change_response = null;
          kot.change_item = null;
          this.masonryLoading();
        }
      } catch (error) {
        console.error(error);
      } finally {
        this.acceptingKot = null;
      }
    },

    // --- Captain -> kitchen cancellation (2026-07-31) -----------------
    // `cancel_items` is a JSON STRING on the KOT, not a child table, so it
    // has to be parsed for display. Defensive: a malformed payload must
    // never blank the whole card -- the reason and the Accept button
    // matter far more than the itemised list.
    cancelledItems(kot) {
      if (!kot || !kot.cancel_items) return [];
      try {
        const parsed = JSON.parse(kot.cancel_items);
        return Array.isArray(parsed) ? parsed : [];
      } catch (error) {
        console.error("bad cancel_items payload", error);
        return [];
      }
    },

    async acceptCancellation(kot) {
      this.acceptingCancel = kot.name;
      try {
        const res = await this.call.post(
          "ury.ury.api.ury_kot_display.kitchen_accept_cancellation",
          { kot: kot.name }
        );
        const wholeOrder = (kot.cancel_scope || "Order") !== "Items";
        this.closeActions();
        if (wholeOrder) {
          // Reuse the serve collapse animation so the card visibly
          // leaves rather than blinking out.
          kot.served = true;
          setTimeout(() => {
            kot.showDiv = true;
            this.masonryLoading();
          }, 620);
        } else {
          // Item scope: the ticket carries on with fewer lines, so
          // re-fetch rather than patching the list by hand.
          kot.cancel_status = "";
          kot.cancel_reason = null;
          kot.cancel_items = null;
          await this.fetchKOT();
          this.masonryLoading();
        }
        return res;
      } catch (error) {
        console.error(error);
      } finally {
        this.acceptingCancel = null;
      }
    },

    // --- Tap-a-card action dialog (2026-07-16) -------------------------
    // The card used to carry Serve / Request-change buttons, which made the
    // board look like a wall of forms. Now tapping the card opens this.
    openActions(kot) {
      this.actionKot = kot;
      this.showActionModal = true;
    },
    closeActions() {
      this.showActionModal = false;
      this.actionKot = null;
    },
    /** Waiter has answered and the kitchen hasn't accepted it yet. */
    hasPendingResponse(kot) {
      return (
        !!kot &&
        ["Confirmed", "Updated", "Cancelled"].includes(kot.change_status)
      );
    },
    isCancelType(kot) {
      return (
        kot &&
        (kot.type === "Cancelled" || kot.type === "Partially cancelled")
      );
    },
    serveFromDialog() {
      const kot = this.actionKot;
      this.closeActions();
      if (!kot) return;
      if (this.isCancelType(kot)) this.confirmOrder(kot);
      else this.serveOrder(kot);
    },
    requestChangeFromDialog() {
      const kot = this.actionKot;
      this.closeActions();
      if (kot) this.openChangeRequest(kot);
    },

    // --- Served orders + reinstate (2026-07-16) ------------------------
    /** Navbar toggle handler (Header emits 'set-view'). */
    onSetView(mode) {
      if (mode === "served") this.showServed();
      else this.showActive();
    },
    async showServed() {
      this.viewMode = "served";
      this.servedTab = "recent";
      if (!this.summaryDate) this.summaryDate = this.todayIso();
      this.fetchServedSummary();
      this.servedLoading = true;
      try {
        const res = await this.call.get(
          "ury.ury.api.ury_kot_display.served_kot_list",
          { production: this.production || "All" }
        );
        const msg = res.message || res;
        this.servedKots = (msg && msg.KOT) || [];
        this.reinstateEnabled = !(msg && msg.reinstate_enabled === 0);
        this.reinstateWindowHours = (msg && msg.reinstate_window_hours) || 3;
        // Reinstate disabled for this unit → no "Recently Served" tab;
        // land on the Items Sold summary instead.
        if (!this.reinstateEnabled) this.servedTab = "summary";
      } catch (error) {
        console.error(error);
        this.servedKots = [];
      } finally {
        this.servedLoading = false;
      }
    },
    /** Today's local date as YYYY-MM-DD (for the summary date input). */
    todayIso() {
      const d = new Date();
      const p = (n) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
    },
    /** Format a numeric quantity: integers as-is, else trimmed to 2dp. */
    fmtQty(n) {
      const v = Number(n) || 0;
      return Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
    },
    /** Load the day's SOLD summary for this screen's production/department. */
    /** Is this a Bar unit, and is somebody's session already open? */
    async fetchBarState() {
      if (!this.production || this.production === "All") return;
      try {
        const res = await this.call.get(
          "ury.ury.api.ury_bar_stock.get_bar_session_state",
          { production: this.production }
        );
        const msg = res.message || res;
        this.isBarUnit = !!(msg && msg.is_bar);
        this.barSession = (msg && msg.session) || null;
      } catch (error) {
        // A kitchen unit (or an older backend) simply has no bar state —
        // never let that break the board.
        console.error(error);
        this.isBarUnit = false;
        this.barSession = null;
      }
    },
    /** Take over the bar: snapshot the stock and start a session. */
    async openBar() {
      if (this.openingBar) return;
      this.openingBar = true;
      try {
        const res = await this.call.post(
          "ury.ury.api.ury_bar_stock.open_bar_session",
          { production: this.production }
        );
        const msg = res.message || res;
        await this.fetchBarState();
        this.setStatusMessage(
          `Bar opened — ${msg.item_count} item(s) recorded.`
        );
        await this.goToStockReport();
      } catch (error) {
        console.error(error);
        this.setStatusMessage("Could not open the bar.");
      } finally {
        this.openingBar = false;
      }
    },
    /** Hand over: close the session. The next person opens their own. */
    async closeBar() {
      if (this.closingBar) return;
      this.closingBar = true;
      try {
        await this.call.post("ury.ury.api.ury_bar_stock.close_bar_session", {
          production: this.production,
        });
        await this.fetchBarState();
        await this.fetchStockReport();
        this.setStatusMessage("Bar closed.");
      } catch (error) {
        console.error(error);
        this.setStatusMessage("Could not close the bar.");
      } finally {
        this.closingBar = false;
      }
    },
    openStockTab() {
      this.servedTab = "stock";
      this.fetchStockReport();
    },
    goStockPage(n) {
      this.stockPage = Math.min(Math.max(1, n), this.stockPageCount);
      const el = this.$refs.stockScroll;
      if (el) el.scrollTop = 0;
    },
    /** Cap the stock card at the space left below it in the window, so the
     * page never scrolls and the navbar, sidebar and bar strip stay put.
     *
     * Measured rather than a CSS calc(): the height above the card varies
     * (open-the-bar banner vs. the "open since" strip). The 24px reserve is
     * the wrapper's p-4 below the card plus a little breathing room (the
     * wrapper drops its mb-16 on this tab); without it the page scrolls by
     * that margin. */
    measureStockPanel() {
      this.$nextTick(() => {
        const el = this.$refs.stockPanel;
        if (!el) return;
        const top = el.getBoundingClientRect().top + window.scrollY;
        this.stockPanelHeight = Math.max(
          320,
          Math.floor(window.innerHeight - top - 24)
        );
        this.$nextTick(this.fitStockRows);
      });
    },
    /** "Fit screen" page size: how many rows fit the list area without it
     * scrolling. The card's non-list chrome (title, chips, pager, note) does
     * not depend on the row count, so card height minus list height is a
     * stable number and this does not feed back on itself. A row that wraps
     * onto two lines can still leave a small scroll — that is the fallback,
     * not a bug. */
    fitStockRows() {
      const panel = this.$refs.stockPanel;
      const scroller = this.$refs.stockScroll;
      if (!panel || !scroller || !this.stockPanelHeight) return;
      const chrome = panel.offsetHeight - scroller.offsetHeight;
      const head = scroller.querySelector("thead");
      const row = scroller.querySelector("tbody tr");
      const rowH = (row && row.offsetHeight) || 33;
      const room =
        this.stockPanelHeight - chrome - ((head && head.offsetHeight) || 0) - 2;
      this.stockFitRows = Math.max(5, Math.floor(room / rowH));
    },
    /** Jump straight to the handover sheet.
     *
     * showServed() is awaited on purpose: it resets servedTab itself (and
     * lands on "summary" when the unit has reinstate turned off), so setting
     * the tab before it resolves would be overwritten. */
    async goToStockReport() {
      if (this.viewMode !== "served") await this.showServed();
      this.openStockTab();
    },
    async fetchStockReport() {
      if (!this.isBarUnit) return;
      this.stockLoading = true;
      try {
        const res = await this.call.get(
          "ury.ury.api.ury_bar_stock.get_bar_stock_report",
          {
            production: this.production,
            show_all: this.stockShowAll ? 1 : 0,
          }
        );
        this.stockReport = res.message || res;
        this.goStockPage(1);
      } catch (error) {
        console.error(error);
        this.stockReport = null;
      } finally {
        this.stockLoading = false;
        this.measureStockPanel();
      }
    },
    /** Handover sheet via the browser print dialog — same self-contained
     * print-window pattern as the Items Sold summary (no printer wiring in
     * the KDS, so the cashier can print or save a PDF). */
    printStockReport() {
      const r = this.stockReport;
      if (!r || !r.rows || !r.rows.length) return;
      const esc = (x) =>
        String(x == null ? "" : x).replace(
          /[&<>"']/g,
          (c) =>
            ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              '"': "&quot;",
              "'": "&#39;",
            })[c]
        );
      const fmt = (n) => this.fmtQty(n);
      const rows = r.rows
        .map(
          (it) =>
            `<tr><td>${esc(it.item_name)}</td><td class="g">${esc(
              it.item_group || ""
            )}</td><td class="q">${fmt(it.opening_qty)}</td><td class="q">${fmt(
              it.sold_qty
            )}</td><td class="q${it.is_negative ? " neg" : ""}">${fmt(
              it.expected_qty
            )}</td><td class="c"></td></tr>`
        )
        .join("");
      const w = window.open("", "_blank");
      if (!w) return;
      w.document.write(`<!doctype html><html><head><meta charset="utf-8">
<title>Stock Report — ${esc(r.production)}</title>
<style>
  body{font-family:system-ui,Arial,sans-serif;margin:24px;color:#111}
  h1{font-size:18px;margin:0 0 2px}
  p.meta{font-size:12px;color:#555;margin:0 0 12px}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{text-align:left;padding:5px 6px;border-bottom:1px solid #ddd}
  th{font-size:10px;text-transform:uppercase;color:#555}
  td.q,th.q{text-align:right;white-space:nowrap}
  td.g{color:#666;font-size:11px}
  td.c{width:70px;border-bottom:1px solid #999}
  td.neg{color:#b00020;font-weight:700}
  .sign{margin-top:28px;font-size:12px;display:flex;gap:48px}
  .sign div{flex:1;border-top:1px solid #999;padding-top:4px}
</style></head><body>
<h1>Bar Stock Handover — ${esc(r.production)}</h1>
<p class="meta">
  Opened ${esc(r.opened_at)} by ${esc(r.opened_by_name)}${
    r.closed_at ? ` · closed ${esc(r.closed_at)}` : ""
  }<br>
  Printed ${esc(r.generated_at)} by ${esc(r.generated_by)} ·
  ${r.totals.line_count} item(s), ${r.totals.moved_count} moved${
    r.totals.negative_count
      ? `, ${r.totals.negative_count} negative`
      : ""
  }
</p>
<table>
  <thead><tr><th>Item</th><th>Group</th><th class="q">Opening</th><th class="q">Sold</th><th class="q">Expected</th><th>Counted</th></tr></thead>
  <tbody>${rows}</tbody>
</table>
<div class="sign"><div>Handed over by</div><div>Received by</div></div>
<script>window.onload=function(){window.print()};window.onafterprint=function(){window.close()}<\/script>
</body></html>`);
      w.document.close();
    },
    /** "2026-09-18 12:20:13.345748" -> "18 Sep, 12:20" */
    fmtWhen(value) {
      if (!value) return "";
      const d = new Date(String(value).replace(" ", "T"));
      if (isNaN(d.getTime())) return String(value);
      return d.toLocaleString([], {
        day: "2-digit",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    },
    async fetchServedSummary() {
      if (!this.summaryDate) this.summaryDate = this.todayIso();
      this.summaryLoading = true;
      try {
        const res = await this.call.get(
          "ury.ury.api.ury_kot_display.get_served_summary",
          { production: this.production || "All", date: this.summaryDate }
        );
        this.servedSummary = res.message || res;
      } catch (error) {
        console.error(error);
        this.servedSummary = null;
      } finally {
        this.summaryLoading = false;
      }
    },
    /** Print the sold summary via a self-contained print window (no printer
     * wiring in the KDS — the browser print dialog handles printer / PDF). */
    printServedSummary() {
      const s = this.servedSummary;
      if (!s || !s.items || !s.items.length) return;
      const esc = (x) =>
        String(x == null ? "" : x).replace(
          /[&<>"']/g,
          (c) =>
            ({
              "&": "&amp;",
              "<": "&lt;",
              ">": "&gt;",
              '"': "&quot;",
              "'": "&#39;",
            })[c]
        );
      const fmt = (n) => this.fmtQty(n);
      const itemRows = s.items
        .map(
          (it) =>
            `<tr><td>${esc(it.item_name)}</td><td class="q">${fmt(
              it.total_qty
            )}</td></tr>`
        )
        .join("");
      const waiterBlocks = (s.by_waiter || [])
        .map((w) => {
          const wr = w.items
            .map(
              (it) =>
                `<tr><td>${esc(it.item_name)}</td><td class="q">${fmt(
                  it.qty
                )}</td></tr>`
            )
            .join("");
          return `<h3>${esc(w.waiter)} — ${fmt(
            w.total_qty
          )}</h3><table><tbody>${wr}</tbody></table>`;
        })
        .join("");
      const win = window.open("", "_blank", "width=720,height=900");
      if (!win) return;
      win.document.write(
        `<!doctype html><html><head><meta charset="utf-8">` +
          `<title>Items Sold — ${esc(s.production)} — ${esc(s.date)}</title>` +
          `<style>` +
          `body{font-family:Arial,Helvetica,sans-serif;color:#111;padding:24px;}` +
          `h1{font-size:20px;margin:0 0 2px;}` +
          `.sub{color:#555;font-size:12px;margin:0 0 16px;}` +
          `.tot{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;margin:0 0 16px;}` +
          `.tot span{background:#f3f4f6;border-radius:6px;padding:4px 10px;font-weight:600;}` +
          `table{width:100%;border-collapse:collapse;margin:0 0 16px;}` +
          `td,th{padding:6px 4px;border-bottom:1px solid #eee;text-align:left;font-size:14px;}` +
          `td.q,th.q{text-align:right;font-weight:700;}` +
          `h2{font-size:15px;margin:18px 0 6px;border-top:2px solid #111;padding-top:8px;}` +
          `h3{font-size:13px;margin:12px 0 4px;color:#333;}` +
          `.foot{margin-top:20px;color:#888;font-size:11px;}` +
          `</style></head><body>` +
          `<h1>Items Sold — ${esc(s.production)}</h1>` +
          `<p class="sub">${esc(s.branch)} · ${esc(s.date)}</p>` +
          `<div class="tot"><span>Total qty: ${fmt(
            s.total_qty
          )}</span><span>${esc(s.distinct_items)} item(s)</span><span>${esc(
            s.ticket_count
          )} ticket(s)</span></div>` +
          `<table><thead><tr><th>Item</th><th class="q">Qty</th></tr></thead>` +
          `<tbody>${itemRows}</tbody></table>` +
          (waiterBlocks ? `<h2>By waiter</h2>${waiterBlocks}` : "") +
          `<p class="foot">Generated ${esc(
            new Date().toLocaleString()
          )}</p>` +
          `<script>window.onload=function(){window.print();setTimeout(function(){window.close();},300);}<\/script>` +
          `</body></html>`
      );
      win.document.close();
    },
    async logout() {
      try {
        await frappe.auth().logout();
      } catch (e) {
        console.error("Logout failed:", e);
      } finally {
        this.redirectToLogin();
      }
    },
    showActive() {
      this.viewMode = "active";
      this.masonryLoading();
    },
    async reinstateKot(kot) {
      this.reinstatingKot = kot.name;
      try {
        await this.call.post("ury.ury.api.ury_kot_display.reinstate_kot", {
          name: kot.name,
        });
        this.servedKots = this.servedKots.filter((k) => k.name !== kot.name);
        // Pull it back onto the active board.
        await this.fetchKOT();
        this.masonryLoading();
      } catch (error) {
        console.error(error);
      } finally {
        this.reinstatingKot = null;
      }
    },
    /** Open the Cancelled or Deleted list; one fetch serves both tabs. */
    openRemovedTab(kind) {
      this.servedTab = kind;
      if (!this.removedDate) this.removedDate = this.todayIso();
      if (!this.removedOrders || this.removedOrders.date !== this.removedDate) {
        this.fetchRemovedOrders();
      }
    },
    async fetchRemovedOrders() {
      this.removedLoading = true;
      try {
        const res = await this.call.get(
          "ury.ury.api.ury_kot_display.get_removed_orders",
          { production: this.production || "All", date: this.removedDate }
        );
        this.removedOrders = res.message || null;
      } catch (error) {
        console.error(error);
        this.removedOrders = null;
      } finally {
        this.removedLoading = false;
      }
    },
    timeLabel(raw) {
      if (!raw) return "";
      const d = new Date(String(raw).replace(" ", "T"));
      if (isNaN(d.getTime())) return String(raw);
      return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    },
    servedTimeLabel(kot) {
      const raw = kot.served_at || kot.modified;
      if (!raw) return "";
      const d = new Date(String(raw).replace(" ", "T"));
      if (isNaN(d.getTime())) return String(raw);
      return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    },

    // --- Kitchen -> waiter change request (2026-07-16) -----------------
    openChangeRequest(kot) {
      this.changeKot = kot;
      this.changeItem = "";
      this.changeMessage = "";
      this.showChangeModal = true;
    },
    closeChangeRequest() {
      this.showChangeModal = false;
      this.changeKot = null;
    },
    async submitChangeRequest() {
      const msg = (this.changeMessage || "").trim();
      if (!msg || !this.changeKot) return;
      const kot = this.changeKot;
      this.changeSubmitting = true;
      try {
        await this.call.post(
          "ury.ury.api.ury_kot_display.request_kot_change",
          {
            kot: kot.name,
            message: msg,
            item: this.changeItem || null,
          }
        );
        // Reflect the hold immediately; the next poll re-syncs from server.
        kot.change_status = "Awaiting Confirmation";
        kot.change_request = msg;
        kot.change_item = this.changeItem || null;
        this.closeChangeRequest();
        this.masonryLoading();
      } catch (error) {
        console.error(error);
      } finally {
        this.changeSubmitting = false;
      }
    },

    async serveOrder(kot) {
      const now = new Date();
      this.currentTime = now.toLocaleTimeString();

      this.call
        .post("ury.ury.api.ury_kot_display.serve_kot", {
          name: kot.name,
          time: this.currentTime,
        })
        .then((result) => {
          // Visible confirmation (2026-07-16): flash the card green and let
          // it collapse away, THEN re-lay the board so the remaining cards
          // animate up into the gap. Previously it vanished instantly with
          // nothing to show the tap had registered.
          kot.served = true;
          this.removeAllItemsFromLocalStorage(kot);
          setTimeout(() => {
            kot.showDiv = true;
            this.masonryLoading();
          }, 620);
        })
        .catch((error) => console.error(error));
    },

    async orderDelayNotify(kot) {
      const now = new Date();
      this.currentTime = now.toLocaleTimeString();

      this.call
        .post(
          "ury.ury.api.ury_kot_notification.order_delay_notification",
          {
            id: kot.name,
          }
        )
        .then((result) => {
          // console.log("call backed ", result);
        })
        .catch((error) => console.error(error));
    },
    toggleItemStrikeThrough(kotitem, kot) {
      kotitem.striked = !kotitem.striked;
      localStorage.setItem(
        `${kot.name}_${kotitem.name}_strike`,
        JSON.stringify(kotitem.striked)
      );
    },

    updateColorandTable(kot, restaurant_table, type, table_takeaway) {
      if (restaurant_table === undefined) {
        kot.tableortakeaway = "Takeaway";
      } else {
        if (table_takeaway == 1) {
          kot.tableortakeaway = "Takeaway";
        } else {
          kot.tableortakeaway = restaurant_table;
        }
      }
      kot.baseColor = this._baseColorFor(type, restaurant_table, table_takeaway);
      kot.color = kot.isLate
        ? "bg-red-100 border-2 border-red-500"
        : kot.baseColor;
    },
    _baseColorFor(type, restaurant_table, table_takeaway) {
      if (type == "Order Modified") {
        return "bg-[#FFD493] border border-[#FFC700]";
      }
      if (type == "Partially cancelled" || type == "Cancelled") {
        return "bg-[#FFD2D2] border border-[#FAA7A7]";
      }
      if (restaurant_table === undefined || table_takeaway == 1) {
        return "bg-blue-100 border border-blue-200";
      }
      return "bg-white";
    },
    updateQtyColorTable() {
      this.kot.forEach((kot) => {
        console.log(kot,"kot............")
        this.updateColorandTable(
          kot,
          kot.restaurant_table,
          kot.type,
          kot.table_takeaway
        );

        kot.kot_items.forEach((kotitem) => {
          const savedState = localStorage.getItem(
            `${kot.name}_${kotitem.name}_strike`
          );
          if (savedState) {
            kotitem.striked = JSON.parse(savedState);
          }
          this.calculateQty(
            kotitem,
            kotitem.quantity,
            kot.type,
            kotitem.cancelled_qty
          );
        });
      });
    },
    calculateQty(kotitem, qty, type, cancelled_qty) {
      kotitem.qty = qty;
      if (type == "Partially cancelled" || type == "Cancelled") {
        kotitem.qty = qty - cancelled_qty;
      }
    },
    removeAllItemsFromLocalStorage(kot) {
      // Get all keys in local storage
      const keys = Object.keys(localStorage);
      // Remove keys that start with `${kot.name}_`
      keys.forEach((key) => {
        if (key.startsWith(`${kot.name}_`)) {
          localStorage.removeItem(key);
        }
      });
    },

    updateTimeRemaining() {
      this.kot.forEach((kot) => {
        const elapsedSec = this._elapsedSeconds(kot);
        kot.timeRemaining = this._formatElapsed(elapsedSec);
        const elapsedMin = Math.floor(elapsedSec / 60);

        const alert = parseInt(this.kot_alert_time);
        const policy = parseInt(this.service_policy_time);
        const live = kot.type !== "Cancelled" && kot.type !== "Partially cancelled";

        if (alert && live && elapsedMin >= alert && !kot._notifiedAt) {
          this.orderDelayNotify(kot);
          kot._notifiedAt = elapsedMin;
        }

        const wasLate = !!kot.isLate;
        kot.isLate = !!(policy && live && elapsedMin >= policy);

        if (kot.isLate !== wasLate || !kot.color) {
          kot.color = kot.isLate
            ? "bg-red-100 border-2 border-red-500"
            : kot.baseColor || this._baseColorFor(kot.type, kot.restaurant_table, kot.table_takeaway);
        }

        kot.timecolor = kot.isLate
          ? "text-[#DC0000] font-bold"
          : alert && elapsedMin >= alert
          ? "text-[#DC0000]"
          : "text-black";
      });
    },
    _elapsedSeconds(kot) {
      // Prefer the SERVER-computed elapsed base (`elapsed_seconds`) and
      // tick forward from when the client received this KOT. This is
      // timezone-safe: the server computed the base entirely in its own
      // timezone, so the timer is correct regardless of the KDS browser's
      // timezone. (The old path parsed Frappe's site-local creation string
      // as browser-local time — when the server tz was ahead of the
      // browser the diff went negative and the timer stuck at 00:00.)
      // Falls back to creation parsing only for legacy payloads with no
      // elapsed_seconds / no _fetchedAt stamp.
      if (kot._fetchedAt) {
        const base = Number(kot.elapsed_seconds);
        const since = (Date.now() - kot._fetchedAt) / 1000;
        const total = (isNaN(base) ? 0 : base) + since;
        return total > 0 ? Math.floor(total) : 0;
      }
      const raw = kot.creation || `${kot.date || ""} ${kot.time || ""}`.trim();
      if (!raw) return 0;
      const iso = raw.replace(" ", "T").split(".")[0];
      const target = new Date(iso);
      const diff = Date.now() - target.getTime();
      if (isNaN(diff) || diff < 0) return 0;
      return Math.floor(diff / 1000);
    },
    _formatElapsed(totalSec) {
      const pad = (n) => String(n).padStart(2, "0");
      const h = Math.floor(totalSec / 3600);
      const m = Math.floor((totalSec % 3600) / 60);
      const s = totalSec % 60;
      return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
    },
    fetchkotwithmasonry() {
      return this.fetchKOT().then(() => {
        this.masonryLoading();
      });
    },
    /** The screens this user may open, from their Screen Access rows. */
    async loadMyUnits() {
      const res = await this.call.get(
        "ury.ury.api.ury_kds_access.get_my_production_units",
        { current: this.production || "" }
      );
      const data = res.message || {};
      this.myUnits = data.units || [];
      this.myDepartments = data.departments || [];
      this.myFullName = data.full_name || "";
      this.unitsLoaded = true;
      return data;
    },
    openScreen(name) {
      if (!name) return;
      window.location.href = "/Mosaic/" + encodeURIComponent(name);
    },
    /** Decide what this page shows. Resolves true to start the board.
     *
     *  /Mosaic (no screen): one screen -> go straight to it; several -> the
     *  picker; none -> "not assigned". A screen the user isn't on -> the
     *  picker with their own screens instead. */
    async routeToScreen() {
      let data;
      try {
        data = await this.loadMyUnits();
      } catch (error) {
        console.error(error);
        if (!this.production) {
          this.targetError = "Couldn't load your screens. Refresh to try again.";
          return false;
        }
        // The board endpoints still enforce access; don't block on this.
        return true;
      }
      const count = this.screenCount;
      if (!this.production) {
        if (count === 1) {
          const only = this.myUnits.length
            ? this.myUnits[0].name
            : this.myDepartments[0];
          window.location.replace("/Mosaic/" + encodeURIComponent(only));
          return false;
        }
        this.unitPickerMode = count ? "page" : "none";
        return false;
      }
      if (!data.current_allowed) {
        this.unitPickerMode = count ? "denied" : "none";
        return false;
      }
      return true;
    },
    redirectToLogin() {
      var currentDomain = window.location.origin;
      const target = this.production
        ? "Mosaic/" + encodeURIComponent(this.production)
        : "Mosaic";
      window.location.href = currentDomain + "/login?redirect-to=" + target;
    },
    masonryLoading() {
      this.$nextTick(() => {
        const grid = this.$el.querySelector(".grid");
        if (!grid) return;
        // Re-USE the instance (2026-07-16). This used to build a brand new
        // Masonry on every call, which snaps every card into place with no
        // animation. Keeping one instance and calling reloadItems()+layout()
        // lets `transitionDuration` animate the re-flow, so when a card is
        // served you can see the rest slide up into the gap.
        if (!this.masonry || this.masonry.element !== grid) {
          if (this.masonry) {
            try {
              this.masonry.destroy();
            } catch (e) {
              /* ignore */
            }
          }
          this.masonry = new Masonry(grid, {
            itemSelector: ".masonry-item",
            gutter: 28,
            transitionDuration: "0.4s",
          });
        } else {
          this.masonry.reloadItems();
        }
        this.masonry.layout();
      });
    },
    hideAudioAlertMessage() {
      this.showAudioAlertMessage = false;
    },
    handleOnline() {
      this.isOnline = true;
      this.setStatusMessage("You are online");
      this.hideStatusMessageAfterDelay();
      if (!this.boardActive) return;
      this.fetchKOT().then(() => {
        this.masonryLoading();
      });
    },
    handleOffline() {
      this.isOnline = false;
      this.setStatusMessage("You are Offline");
    },
    setStatusMessage(message) {
      this.statusMessage = message;
    },
    hideStatusMessageAfterDelay() {
      setTimeout(() => {
        this.statusMessage = "";
      }, 3000);
    },
    handleTransitionEnd() {
      if (!this.isOnline) {
        // Reset the status message after transition end
        this.setStatusMessage("");
      }
    },
  },
  mounted() {
    // Connectivity is decided by a real reachability probe with two-strike
    // hysteresis, NOT by `navigator.onLine` — that signal flaps on Android
    // whenever the screen sleeps or the device roams between access points,
    // and every flap used to pop the red "You are Offline" toast followed by
    // a green "You are online". The watcher only calls back on a SETTLED
    // change, so these handlers can no longer be spammed. (2026-09-24)
    startConnectivityWatch((online) => {
      if (online) this.handleOnline();
      else this.handleOffline();
    });
    window.addEventListener("resize", this.measureStockPanel);
    document.addEventListener("click", this.hideAudioAlertMessage);
    // The screen is the last path segment: /Mosaic/<unit or department>.
    // Plain /Mosaic (where a kitchen user lands after login) has none.
    const parts = window.location.pathname.split("/").filter(Boolean);
    const last = decodeURIComponent(parts[parts.length - 1] || "");
    this.production = last.toLowerCase() === "mosaic" ? "" : last;
    // Derive the realtime channels from the LAST KNOWN branch before the
    // first kot_list call. If the screen boots with no connection that call
    // fails, and without this the channel names would be empty strings and
    // the board would subscribe to nothing. (2026-09-24)
    this.restoreCachedBranch();
    const self = this;
    window.addEventListener("resize", this.masonryLoading());
    this.masonryLoading();

    this.auth()
      .then(() => this.routeToScreen())
      .then((startBoard) => {
        if (!startBoard) return;
        self.boardActive = true;
        self.fetchBarState();
        self.fetchKOT().then(() => {
          if (this.audio_alert === 1) {
            this.showAudioAlertMessage = true;
          }
          socket.on(this.kot_channel, (doc) => {
            // Rings unless the admin explicitly muted it; falls back to the
            // bundled bell when no profile sound is configured. 2026-07-16.
            if (this.shouldRing()) {
              this.playAlertSound(doc.audio_file);
            }
            let kottime = localStorage.getItem("kot_time");
            if (doc.last_kot_time !== null) {
              if (doc.last_kot_time !== kottime) {
                this.fetchKOT().then(() => {
                  this.masonryLoading();
                });
              }
            }
            // A realtime KOT is brand-new (~0 elapsed); stamp its receipt
            // time so the timer ticks up from 0 (it carries no
            // elapsed_seconds, so base defaults to 0).
            doc.kot._fetchedAt = Date.now();
            this.kot.unshift(doc.kot);
            this.masonryLoading();
            this.updateQtyColorTable();
            this.updateTimeRemaining();
            setTimeout(()=>{
              if (doc.kot.type === "Cancelled"){
                this.fetchKOT().then(() => {
                  this.masonryLoading();
                });
              }
            },1500)
            localStorage.setItem("kot_time", doc.kot.time);
          });
          // A waiter answered a kitchen change request (confirm / update /
          // cancel) → refresh so the card shows the response + the Accept
          // button without a manual reload. 2026-07-23.
          socket.on(this.change_channel, () => {
            this.fetchKOT().then(() => {
              this.masonryLoading();
            });
          });
          // Captain -> kitchen cancellation (2026-07-31). Same targeted
          // per-screen channel shape as the change loop: an untargeted
          // publish gets scoped to the CALLING user's room, i.e. the
          // captain's browser, which is exactly not the kitchen. Without
          // this the cook only sees the cancellation on the next 30s
          // poll -- and the table's bill is locked until they accept.
          socket.on(this.cancel_channel, () => {
            this.fetchKOT().then(() => {
              this.masonryLoading();
            });
          });
        });
      })
      .catch((error) => {
        console.error("Authentication error:", error);
        this.showModal = true;
      });
    this._tickHandle = setInterval(this.updateTimeRemaining, 1000);
    // Safety-net board refresh every 30s (2026-08-24).
    //
    // The board is driven by the realtime socket, which is fine until the
    // socket drops — a kitchen screen left running all service then sits
    // there silently stale, and nobody notices because there is nothing to
    // notice. This re-fetches on a timer regardless.
    //
    // It deliberately does NOT ring: the bell belongs to the socket handler
    // for genuinely new KOTs. A poll that rang would chime every 30s for
    // tickets already sitting on the board.
    this._refreshHandle = setInterval(() => {
      if (document.hidden) return; // don't poll a backgrounded screen
      if (!this.boardActive) return; // picker / no-access screen
      // Never let ticks overlap. On a slow server an unguarded poll stacks
      // up, and each pending request holds one of the six connections a
      // browser allows per origin on HTTP/1.1 — which starves everything
      // else on the page, including the connectivity probe. Same failure
      // the POS hit with its KOT poller. (2026-09-24)
      if (this._refreshInFlight) return;
      this._refreshInFlight = true;
      this.fetchKOT()
        .then(() => this.masonryLoading())
        .catch(() => {
          /* transient — the next tick tries again */
        })
        .finally(() => {
          this._refreshInFlight = false;
        });
    }, 30000);
  },
  beforeUnmount() {
    stopConnectivityWatch();
    window.removeEventListener("resize", this.measureStockPanel);
    document.removeEventListener("click", this.hideAudioAlertMessage);
    if (this._tickHandle) clearInterval(this._tickHandle);
    if (this._refreshHandle) clearInterval(this._refreshHandle);
  },
  watch: {
    stockSearch() {
      this.goStockPage(1);
    },
    // Keep the first row on screen in view when the page size changes
    // (window resized, or a different Rows choice) instead of jumping back
    // to page 1.
    stockPageSize(size, oldSize) {
      const first = (Math.max(1, this.stockPage) - 1) * (oldSize || size);
      this.goStockPage(Math.floor(first / size) + 1);
    },
    stockRowsSetting() {
      this.measureStockPanel();
    },
    // Anything that changes what sits ABOVE the stock card changes how much
    // room is left for it, so re-measure.
    servedTab() {
      this.measureStockPanel();
    },
    viewMode() {
      this.measureStockPanel();
    },
    barSession() {
      this.measureStockPanel();
    },
  },
  computed: {
    removedList() {
      if (!this.removedOrders) return [];
      return (
        (this.servedTab === "deleted"
          ? this.removedOrders.deleted
          : this.removedOrders.cancelled) || []
      );
    },
    screenCount() {
      return this.myUnits.length + this.myDepartments.length;
    },
    /** Offer Switch only when there is somewhere else to go. */
    canSwitchUnit() {
      if (!this.boardActive) return false;
      const names = this.myUnits
        .map((u) => u.name)
        .concat(this.myDepartments);
      return names.some((n) => n !== this.production);
    },
    stockPageSize() {
      return this.stockRowsSetting === "fit"
        ? this.stockFitRows
        : Number(this.stockRowsSetting) || 20;
    },
    stockFilteredRows() {
      const rows = (this.stockReport && this.stockReport.rows) || [];
      const q = (this.stockSearch || "").trim().toLowerCase();
      if (!q) return rows;
      return rows.filter((r) =>
        [r.item_name, r.item_code, r.item_group].some((v) =>
          String(v || "").toLowerCase().includes(q)
        )
      );
    },
    stockPageCount() {
      return Math.max(
        1,
        Math.ceil(this.stockFilteredRows.length / this.stockPageSize)
      );
    },
    // Clamped, so a regenerate that returns fewer rows can't strand the
    // barman on a page that no longer exists.
    stockCurrentPage() {
      return Math.min(Math.max(1, this.stockPage), this.stockPageCount);
    },
    stockPageRows() {
      const start = (this.stockCurrentPage - 1) * this.stockPageSize;
      return this.stockFilteredRows.slice(start, start + this.stockPageSize);
    },
    stockRangeStart() {
      if (!this.stockFilteredRows.length) return 0;
      return (this.stockCurrentPage - 1) * this.stockPageSize + 1;
    },
    stockRangeEnd() {
      return Math.min(
        this.stockCurrentPage * this.stockPageSize,
        this.stockFilteredRows.length
      );
    },
    sortedKotItems() {
      return (kot) => {
        return kot.kot_items.sort((a, b) => a.serve_priority - b.serve_priority);
      };
    },
  },
};
</script>
<style>
.bg-gray-100 {
  background-color: rgba(0, 0, 0, 0.2);
}

/* Drop target while dragging a card to reorder the board (2026-07-16). */
.ury-drag-over {
  outline: 3px dashed #2563eb;
  outline-offset: 3px;
}

/* Served confirmation (2026-07-16): the card pulses green, then collapses
   away — so the cook can see the tap registered. Masonry then animates the
   remaining cards up into the gap (transitionDuration in masonryLoading). */
.ury-served-flash {
  animation: uryServed 620ms ease-out forwards;
  pointer-events: none;
}
@keyframes uryServed {
  0% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(22, 163, 74, 0);
  }
  30% {
    transform: scale(1.04);
    box-shadow: 0 0 0 8px rgba(22, 163, 74, 0.5);
  }
  100% {
    transform: scale(0.82);
    opacity: 0;
    box-shadow: 0 0 0 0 rgba(22, 163, 74, 0);
  }
}
</style>
