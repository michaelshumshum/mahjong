<script lang="ts">
	import ShieldCheck from '@lucide/svelte/icons/shield-check';
	import ShieldAlert from '@lucide/svelte/icons/shield-alert';
	import Shield from '@lucide/svelte/icons/shield';
	import { m } from '$lib/paraglide/messages.js';
	import type { FairnessState } from '$lib/game/state';
	import { checkFairness, type FairnessCheck } from '$lib/net/fairness';

	let { fairness }: { fairness: FairnessState } = $props();

	let check = $state<FairnessCheck | null>(null);

	$effect(() => {
		const current = fairness;
		let stale = false;
		check = null;
		void checkFairness(current).then((result) => {
			if (!stale) check = result;
		});
		return () => {
			stale = true;
		};
	});

	const copy = $derived(
		check === 'verified'
			? { title: m.fairness_verified(), desc: m.fairness_verifiedDesc() }
			: check === 'mismatch'
				? { title: m.fairness_mismatch(), desc: m.fairness_mismatchDesc() }
				: check === 'unverifiable'
					? { title: m.fairness_unverifiable(), desc: m.fairness_unverifiableDesc() }
					: { title: m.fairness_checking(), desc: '' }
	);
</script>

<section
	class="fairness fairness--{check ?? 'pending'}"
	data-testid="fairness-badge"
	data-check={check}
>
	<p class="status" role="status">
		{#if check === 'verified'}
			<ShieldCheck size={16} aria-hidden="true" />
		{:else if check === 'mismatch'}
			<ShieldAlert size={16} aria-hidden="true" />
		{:else}
			<Shield size={16} aria-hidden="true" />
		{/if}
		<span class="title">{copy.title}</span>
	</p>
	{#if copy.desc}<p class="desc">{copy.desc}</p>{/if}
	<details>
		<summary>{m.fairness_details()}</summary>
		<dl>
			{#if fairness.commit}
				<dt>{m.fairness_commitLabel()}</dt>
				<dd>{fairness.commit}</dd>
			{/if}
			<dt>{m.fairness_handSeedLabel()}</dt>
			<dd>{fairness.handSeed}</dd>
			<dt>{m.fairness_nonceLabel()}</dt>
			<dd>{fairness.nonce}</dd>
		</dl>
	</details>
</section>

<style lang="scss">
	.fairness {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-2) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		font-size: var(--font-size-sm);
	}

	.status {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		font-weight: 600;
	}

	.fairness--verified .status {
		color: var(--color-brass);
	}

	.fairness--mismatch {
		border-color: var(--color-status-error);

		.status {
			color: var(--color-status-error);
		}
	}

	.desc {
		margin: 0;
		color: var(--color-text-muted);
		line-height: 1.35;
	}

	summary {
		color: var(--color-text-muted);
		cursor: pointer;
	}

	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-1) var(--space-3);
		margin: var(--space-2) 0 0;
	}

	dt {
		color: var(--color-text-muted);
	}

	dd {
		margin: 0;
		min-width: 0;
		font-family: ui-monospace, monospace;
		font-size: var(--font-size-xs);
		overflow-wrap: anywhere;
	}
</style>
