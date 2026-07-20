<template>
  <!-- Compact kitchen navbar (2026-07-16): tighter padding, smaller logo, and
       the Active/Served switch lives here instead of floating above the board. -->
  <header
    class="bg-white px-3 py-1.5 flex items-center justify-between gap-3 shadow-sm"
  >
    <img :src="imagePath" alt="Logo" class="w-24 h-auto shrink-0" />

    <div class="flex items-center gap-1 rounded-full bg-gray-100 p-1">
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

    <button
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
  },
  emits: ["set-view"],
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
