<template>
	<!-- Header is rendered inside KOT (2026-07-16) so the navbar's
	     Active/Served toggle can drive KOT's viewMode directly, instead of
	     lifting that state up through App just to hand it back down. -->
	<div class="bg-slate-300 min-h-screen"><KOT /></div>
</template>

<script>
import KOT from './components/kot.vue';

export default {

	name: "app",
	components: {
		KOT,
	},
};
</script>
