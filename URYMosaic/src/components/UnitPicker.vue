<template>
  <!-- Kitchen screen picker (2026-09-18).
       mode "page"   : /Mosaic landing for someone with several screens.
       mode "modal"  : the Switch button on a screen; can be closed.
       mode "denied" : opened a screen they aren't on; offers their own.
       mode "none"   : on no screen at all; only Log out is offered.
       bg-slate-100, not bg-gray-100: kot.vue globally redefines .bg-gray-100
       as a translucent tint. -->
  <div
    class="fixed inset-0 z-40 overflow-y-auto"
    :class="mode === 'modal' ? 'bg-black/40' : 'bg-slate-100'"
    @click.self="mode === 'modal' && $emit('close')"
  >
    <div class="min-h-full flex items-start sm:items-center justify-center p-4">
      <div class="w-full max-w-3xl rounded-2xl bg-white shadow-xl p-5 sm:p-7">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <h1 class="text-2xl font-extrabold text-gray-900">{{ title }}</h1>
            <p class="mt-1 text-gray-600">{{ subtitle }}</p>
          </div>
          <button
            v-if="mode === 'modal'"
            type="button"
            class="shrink-0 rounded-md p-2 text-gray-500 hover:bg-gray-100"
            title="Close"
            @click="$emit('close')"
          >
            <svg class="w-5 h-5" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                stroke="currentColor"
                stroke-linecap="round"
                stroke-width="2"
                d="M6 6l12 12M18 6L6 18"
              />
            </svg>
          </button>
        </div>

        <div v-if="units.length" class="mt-5">
          <h2
            v-if="departments.length"
            class="mb-2 text-xs font-bold uppercase tracking-wide text-gray-500"
          >
            Production units
          </h2>
          <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            <button
              v-for="unit in units"
              :key="unit.name"
              type="button"
              :disabled="unit.name === current"
              class="group relative text-left rounded-xl border-2 p-4 transition"
              :class="
                unit.name === current
                  ? 'border-gray-900 bg-gray-50 cursor-default'
                  : 'border-gray-200 hover:border-blue-500 hover:bg-blue-50'
              "
              @click="$emit('pick', unit.name)"
            >
              <span
                class="inline-block rounded-full px-2 py-0.5 text-xs font-bold"
                :class="typeClass(unit.unit_type)"
              >
                {{ unit.unit_type || "Kitchen" }}
              </span>
              <span class="mt-2 block text-lg font-bold text-gray-900 break-words">
                {{ unit.name }}
              </span>
              <span v-if="unit.branch" class="block text-sm text-gray-500">
                {{ unit.branch }}
              </span>
              <span
                v-if="unit.name === current"
                class="absolute top-3 right-3 text-xs font-semibold text-gray-700"
              >
                Open now
              </span>
            </button>
          </div>
        </div>

        <div v-if="departments.length" class="mt-5">
          <h2
            v-if="units.length"
            class="mb-2 text-xs font-bold uppercase tracking-wide text-gray-500"
          >
            Department screens
          </h2>
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <button
              v-for="dept in departments"
              :key="dept"
              type="button"
              :disabled="dept === current"
              class="rounded-xl border-2 p-4 text-lg font-bold transition"
              :class="
                dept === current
                  ? 'border-gray-900 bg-gray-50 cursor-default'
                  : 'border-gray-200 hover:border-blue-500 hover:bg-blue-50'
              "
              @click="$emit('pick', dept)"
            >
              {{ dept }}
            </button>
          </div>
        </div>

        <div class="mt-6 flex items-center justify-between gap-3 flex-wrap">
          <p v-if="fullName" class="text-sm text-gray-500">
            Signed in as <span class="font-semibold text-gray-700">{{ fullName }}</span>
          </p>
          <button
            type="button"
            class="ml-auto rounded-md px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
            @click="$emit('logout')"
          >
            Log out
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  name: "UnitPicker",
  props: {
    mode: { type: String, default: "page" },
    units: { type: Array, default: () => [] },
    departments: { type: Array, default: () => [] },
    current: { type: String, default: "" },
    fullName: { type: String, default: "" },
  },
  emits: ["pick", "close", "logout"],
  computed: {
    title() {
      if (this.mode === "none") return "No kitchen screen assigned";
      if (this.mode === "denied") return "This screen isn't yours";
      if (this.mode === "modal") return "Switch screen";
      return "Choose your screen";
    },
    subtitle() {
      if (this.mode === "none") {
        return "You aren't on any kitchen screen yet. Ask a manager to add you to a production unit's Screen Access table.";
      }
      if (this.mode === "denied") {
        return `You don't have access to ${this.current}. Pick one of your screens instead.`;
      }
      return "Pick the kitchen or bar screen you are working on.";
    },
  },
  methods: {
    typeClass(type) {
      if (type === "Bar") return "bg-amber-100 text-amber-800";
      if (type === "Other") return "bg-gray-200 text-gray-700";
      return "bg-emerald-100 text-emerald-800";
    },
  },
};
</script>
