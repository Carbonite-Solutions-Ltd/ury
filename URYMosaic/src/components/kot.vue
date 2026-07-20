<template>
  <div class="mx-auto p-6 mb-16 relative">
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
      v-else
      class="grid grid-cols-1 gap-10 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
    >
      <div v-for="kot in this.kot" :key="kot.name">
        <div
          :class="[kot.color]"
          class="relative inline-block shadow-lg gap-4 p-3 rounded-2xl w-90 h-auto masonry-item"
          style="margin-top: 28px"
          v-if="!kot.showDiv && kot.production === production"
        >
          <!-- Protruding order-number badge (2026-07-16). Sits half outside
               the top edge so the number is the first thing a cook sees when
               scanning the board. The card's 28px top margin leaves room. -->
          <div
            class="absolute -top-4 left-1/2 -translate-x-1/2 z-20 rounded-full bg-gray-900 text-white border-4 border-white shadow-lg px-4 py-1 text-xl font-extrabold leading-none whitespace-nowrap"
          >
            #{{ orderLabel(kot) }}
          </div>
          <div class="w-64 check">
            <div
              :class="[{ hidden: !kot.isRotated }]"
              @click="rotateCard(kot)"
              class="absolute inset-0 bg-white z-50 opacity-80 rounded-2xl flex flex-col justify-center items-center"
            >
              <button
                @click="
                  kot.type === 'Cancelled' || kot.type === 'Partially cancelled'
                    ? confirmOrder(kot)
                    : serveOrder(kot)
                "
                :class="[{ hidden: !kot.isRotated }]"
                class="py-2 px-6 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition duration-300 ease-in-out"
              >
                {{
                  kot.type === "Cancelled" || kot.type === "Partially cancelled"
                    ? "Confirm"
                    : "Serve"
                }}
              </button>
            </div>

            
              <!-- Serve Button -->

              <!-- Card Header: Table Name and Order Number -->
              <div class="flex justify-between" @click="rotateCard(kot)">
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
                  <span class="text-sm font-medium text-[#6B7280]">Order</span>
                  <span class="text-black-500 ml-2 font-semibold"
                    >{{ orderLabel(kot) }}
                  </span>
                  <span
                    class="text-black-500 ml-2 font-semibold"
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
                    @click="
                      () => {
                        toggleItemStrikeThrough(kotitem, kot);
                      }
                    "
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
              <div
                v-else-if="kot.change_status === 'Confirmed'"
                class="mt-3 rounded border-2 border-[#16A34A] bg-[#F0FDF4] px-2 py-2 font-bold text-[#166534]"
              >
                CHANGE CONFIRMED — proceed
              </div>
              <div
                v-else-if="kot.change_status === 'Rejected'"
                class="mt-3 rounded border-2 border-[#DC2626] bg-[#FEF2F2] px-2 py-2 font-bold text-[#991B1B]"
              >
                REJECTED — make as originally ordered
              </div>

              <!-- Visible Serve / Confirm button (always at the bottom of the card) -->
              <div class="mt-3 pt-3 border-t border-black/10 space-y-2">
                <button
                  type="button"
                  :disabled="kot.change_status === 'Awaiting Confirmation'"
                  @click.stop="
                    kot.type === 'Cancelled' || kot.type === 'Partially cancelled'
                      ? confirmOrder(kot)
                      : serveOrder(kot)
                  "
                  :class="[
                    'w-full py-2 rounded-md text-white font-semibold transition',
                    kot.change_status === 'Awaiting Confirmation'
                      ? 'bg-gray-400 cursor-not-allowed'
                      : kot.isLate
                      ? 'bg-red-700 hover:bg-red-800'
                      : 'bg-blue-600 hover:bg-blue-700',
                  ]"
                >
                  {{
                    kot.change_status === 'Awaiting Confirmation'
                      ? 'On hold'
                      : kot.type === 'Cancelled' || kot.type === 'Partially cancelled'
                      ? 'Confirm'
                      : 'Serve'
                  }}
                </button>
                <button
                  v-if="kot.change_status !== 'Awaiting Confirmation'"
                  type="button"
                  @click.stop="openChangeRequest(kot)"
                  class="w-full py-2 rounded-md border-2 border-[#F59E0B] text-[#92400E] font-semibold hover:bg-[#FFFBEB] transition"
                >
                  Request change
                </button>
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
</template>

<script>
import { FrappeApp } from "frappe-js-sdk";
import Masonry from "masonry-layout";
import io from "socket.io-client";

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
    playAlertSound(path) {
      var currentDomain = window.location.origin;
      var audio_path = currentDomain + path;
      const audio = new Audio(audio_path);
      audio.play();
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
    rotateCard(kot) {
      this.masonryLoading();
      kot.isRotated = !kot.isRotated;
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
          // kot.isHidden = !kot.isHidden;
          kot.showDiv = !kot.showDiv;
          // this.showDiv = false;

          this.removeAllItemsFromLocalStorage(kot);
          this.masonryLoading();
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
        this.masonry = new Masonry(this.$el.querySelector(".grid"), {
          itemSelector: ".masonry-item",
          gutter: 28,

          // Other Masonry options can be added here
        });
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
            if (this.audio_alert === 1) {
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
</style>
