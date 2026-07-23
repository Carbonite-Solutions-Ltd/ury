<template>
  <!-- Single root on purpose: masonryLoading() uses this.$el.querySelector,
       and a multi-root (fragment) component would make $el a comment node. -->
  <div>
    <Header :view-mode="viewMode" @set-view="onSetView" @logout="logout" />

    <div class="mx-auto p-4 mb-16 relative">
    <!-- Served view (2026-07-16 / sidebar 2026-07-23): a sidebar toggles
         Recently Served (reinstate list) vs Items Served (sold summary).
         Recently Served is first + the default; it's hidden when the
         production unit has reinstate disabled. -->
    <div v-if="viewMode === 'served'" class="flex gap-4 items-start">
      <aside class="w-40 shrink-0 space-y-1">
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
      </aside>

      <div class="flex-1 min-w-0 max-w-3xl">
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

              <!-- Kitchen -> waiter change request state (2026-07-16) -->
              <div
                v-if="kot.change_status === 'Awaiting Confirmation'"
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
import Masonry from "masonry-layout";
import io from "socket.io-client";
import Header from "./Header.vue";

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
  components: { Header },
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
      // Served-day sold summary (2026-07-23)
      servedSummary: null,
      summaryDate: "",
      summaryLoading: false,
      showWaiterBreakdown: false,
      // Drag-to-reorder (2026-07-16)
      draggingKot: null,
      dragOverKot: null,
      acceptingKot: null,
      production: "",
      branch: "",
      kds_routing_mode: "Menu Course",
      kot_channel: "",
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
      service_policy_time: 0,
      _tickHandle: null,
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
              this.kot_channel = `kot_update_${this.branch}_${this.production}`;
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
              console.error(error);
              reject(error);
            });
        } catch (error) {
          reject(error);
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
    redirectToLogin() {
      var currentDomain = window.location.origin;
      window.location.href =
        currentDomain + "/login?redirect-to=Mosaic/" + this.production;
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
    window.addEventListener("online", this.handleOnline);
    window.addEventListener("offline", this.handleOffline);
    document.addEventListener("click", this.hideAudioAlertMessage);
    const currentUrl = window.location.href;
    const parts = currentUrl.split("/");
    const production = parts[parts.length - 1];
    const decodedProduction = decodeURIComponent(production);
    this.production = decodedProduction;
    const self = this;
    window.addEventListener("resize", this.masonryLoading());
    this.masonryLoading();

    this.auth()
      .then(() => {
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
        });
      })
      .catch((error) => {
        console.error("Authentication error:", error);
        this.showModal = true;
      });
    this._tickHandle = setInterval(this.updateTimeRemaining, 1000);
  },
  beforeUnmount() {
    window.removeEventListener("online", this.handleOnline);
    window.removeEventListener("offline", this.handleOffline);
    document.removeEventListener("click", this.hideAudioAlertMessage);
    if (this._tickHandle) clearInterval(this._tickHandle);
  },
  computed: {
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
