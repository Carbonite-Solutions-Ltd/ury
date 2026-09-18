<template>
  <!-- Compact kitchen navbar (2026-07-16): tighter padding, smaller logo, and
       the Active/Served switch lives here instead of floating above the board. -->
  <header
    class="bg-white px-3 py-1.5 flex items-center justify-between gap-3 shadow-sm"
  >
    <div class="flex items-center gap-2 min-w-0">
      <img :src="imagePath" alt="Logo" class="w-24 h-auto shrink-0" />
      <!-- Which screen this is, and a way to move to another one when the
           user has more than one (2026-09-18). -->
      <button
        v-if="unitLabel && canSwitch"
        type="button"
        class="flex items-center gap-1 min-w-0 rounded-md border border-gray-300 px-2 py-1 text-sm font-semibold text-gray-800 hover:bg-gray-100"
        title="Switch to another screen"
        @click="$emit('switch')"
      >
        <span class="truncate max-w-[10rem]">{{ unitLabel }}</span>
        <svg class="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            stroke="currentColor"
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M7 16l-4-4 4-4M3 12h14M17 8l4 4-4 4"
          />
        </svg>
        <span class="hidden md:inline text-gray-500 font-normal">Switch</span>
      </button>
      <span
        v-else-if="unitLabel"
        class="truncate max-w-[10rem] text-sm font-semibold text-gray-800"
      >
        {{ unitLabel }}
      </span>
    </div>

    <div v-if="!pickerMode" class="flex items-center gap-1 rounded-full bg-gray-100 p-1">
      <button
        type="button"
        @click="$emit('set-view', 'active')"
        :class="[
          'px-3 py-1 rounded-full text-sm font-semibold transition',
          viewMode === 'active'
            ? 'bg-gray-900 text-white shadow'
            : 'text-gray-700 hover:bg-gray-200',
        ]"
      >
        Active
      </button>
      <button
        type="button"
        @click="$emit('set-view', 'served')"
        :class="[
          'px-3 py-1 rounded-full text-sm font-semibold transition',
          viewMode === 'served'
            ? 'bg-gray-900 text-white shadow'
            : 'text-gray-700 hover:bg-gray-200',
        ]"
      >
        Served
      </button>
    </div>

    <!-- Right group: refresh + logout kept together so the toggle stays
         centered in the justify-between header. -->
    <div class="flex items-center gap-1 shrink-0">
      <button
        v-if="!pickerMode"
        class="hover:bg-slate-200 text-blue font-semibold px-3 py-1 rounded-md shrink-0"
        title="Refresh"
        @click="reloadKOT"
      >
        <svg
          class="w-5 h-5 text-blue-800"
          aria-hidden="true"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 18 20"
        >
          <path
            stroke="currentColor"
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M16 1v5h-5M2 19v-5h5m10-4a8 8 0 0 1-14.947 3.97M1 10a8 8 0 0 1 14.947-3.97"
          />
        </svg>
      </button>
      <button
        class="hover:bg-red-50 text-red-700 font-semibold px-3 py-1 rounded-md shrink-0 flex items-center gap-1"
        title="Log out"
        @click="$emit('logout')"
      >
        <svg
          class="w-5 h-5"
          aria-hidden="true"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
        >
          <path
            stroke="currentColor"
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M16 17l5-5-5-5M21 12H9M12 19H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h7"
          />
        </svg>
        <span class="hidden sm:inline text-sm">Logout</span>
      </button>
    </div>
  </header>
</template>

<script>
import uriMosaicImage from "@/assets/logos/mosaic.jpg";

export default {
  name: "Header",
  props: {
    /** Which board the KDS is showing — drives the toggle's active state. */
    viewMode: {
      type: String,
      default: "active",
    },
    /** Name of the screen being shown (production unit or department). */
    unitLabel: {
      type: String,
      default: "",
    },
    /** True when the user has more than one screen to move between. */
    canSwitch: {
      type: Boolean,
      default: false,
    },
    /** No board behind the header (picker / no-access screen). */
    pickerMode: {
      type: Boolean,
      default: false,
    },
  },
  emits: ["set-view", "logout", "switch"],
  data() {
    return {
      imagePath: uriMosaicImage,
    };
  },
  methods: {
    reloadKOT() {
      window.location.reload();
    },
  },
};
</script>
