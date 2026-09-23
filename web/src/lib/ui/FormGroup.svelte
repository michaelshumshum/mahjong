<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		legend,
		children
	}: {
		legend: string;
		children: Snippet;
	} = $props();
</script>

<fieldset class="form-group">
	<legend>{legend}</legend>
	<div class="form-group-body">
		{@render children()}
	</div>
</fieldset>

<style lang="scss">
	@use '$lib/styles/forms';

	.form-group {
		@include forms.form-group;
	}

	legend {
		@include forms.form-legend;
	}

	.form-group-body {
		@include forms.form-group-body;
	}
</style>
