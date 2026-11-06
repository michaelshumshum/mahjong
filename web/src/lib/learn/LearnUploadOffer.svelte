<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { learnSync } from './learn-sync.svelte';
</script>

{#if learnSync.offer !== 'none'}
	<section class="upload-offer" data-testid="learn-upload-offer" aria-labelledby="upload-title">
		<h2 id="upload-title">{m.learn_uploadTitle()}</h2>
		{#if learnSync.offer === 'failed'}
			<p class="error" role="alert">{m.learn_uploadFailed()}</p>
			<div class="actions">
				<button type="button" class="secondary" onclick={() => learnSync.decline()}>
					{m.learn_uploadDismiss()}
				</button>
			</div>
		{:else}
			<p>{m.learn_uploadBody()}</p>
			<div class="actions">
				<button
					type="button"
					class="primary"
					data-testid="learn-upload-accept"
					disabled={learnSync.offer === 'uploading'}
					onclick={() => void learnSync.upload()}
				>
					{m.learn_uploadAccept()}
				</button>
				<button
					type="button"
					class="secondary"
					disabled={learnSync.offer === 'uploading'}
					onclick={() => learnSync.decline()}
				>
					{m.learn_uploadDecline()}
				</button>
			</div>
		{/if}
	</section>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/forms';

	.upload-offer {
		@include forms.settings-card;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding-block: var(--space-3);
	}

	h2 {
		margin: 0;
		font-size: var(--font-size-base);
	}

	p {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.error {
		color: var(--color-status-error);
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.primary {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-primary;
	}

	.secondary {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
	}
</style>
