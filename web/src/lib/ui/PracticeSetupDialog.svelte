<script lang="ts">
	import {
		createTable,
		PRACTICE_DIFFICULTY_OPTIONS,
		PRACTICE_DIFFICULTY_TO_TIER,
		type PracticeDifficulty
	} from '$lib/net/lobby';
	import PanelHeader from './PanelHeader.svelte';
	import FormGroup from './FormGroup.svelte';
	import OptionRow from './OptionRow.svelte';

	let { onCreated, onCancel }: { onCreated: (tableId: string) => void; onCancel: () => void } =
		$props();

	// seats 1-3 only -- seat 0 is the human's own seat (this route's existing seat-picker flow),
	// never configured here. Offsets from your own seat, clockwise, matching
	// mock-game-state.ts's relativeSeat: 1 right, 2 across, 3 left.
	const SEATS = [
		{ seat: 1, label: 'Right opponent' },
		{ seat: 2, label: 'Across' },
		{ seat: 3, label: 'Left opponent' }
	] as const;

	let difficulty = $state<Record<1 | 2 | 3, PracticeDifficulty>>({
		1: 'normal',
		2: 'normal',
		3: 'normal'
	});
	let submitting = $state(false);
	let error = $state<string | null>(null);

	async function handleSubmit(): Promise<void> {
		submitting = true;
		error = null;
		try {
			const { table_id } = await createTable({
				practice: true,
				bot_tiers: {
					1: PRACTICE_DIFFICULTY_TO_TIER[difficulty[1]],
					2: PRACTICE_DIFFICULTY_TO_TIER[difficulty[2]],
					3: PRACTICE_DIFFICULTY_TO_TIER[difficulty[3]]
				}
			});
			onCreated(table_id);
		} catch {
			error = "Couldn't start a practice table — try again.";
			submitting = false;
		}
	}
</script>

<div class="panel-overlay">
	<div
		class="practice-dialog"
		role="dialog"
		aria-modal="true"
		aria-labelledby="practice-setup-heading"
	>
		<PanelHeader title="Practice vs Bots" titleId="practice-setup-heading" />

		{#each SEATS as { seat, label } (seat)}
			<FormGroup legend={label}>
				{#each PRACTICE_DIFFICULTY_OPTIONS as option (option.value)}
					<OptionRow
						type="radio"
						name={`seat-${seat}-difficulty`}
						value={option.value}
						label={option.label}
						checked={difficulty[seat] === option.value}
						onChange={() => (difficulty[seat] = option.value)}
					/>
				{/each}
			</FormGroup>
		{/each}

		{#if error}
			<p class="practice-error">{error}</p>
		{/if}

		<div class="practice-actions">
			<button type="button" onclick={onCancel} disabled={submitting}>Cancel</button>
			<button type="button" class="practice-submit" onclick={handleSubmit} disabled={submitting}>
				{submitting ? 'Starting…' : 'Start'}
			</button>
		</div>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panel-overlay {
		@include buttons.modal-scrim;
	}

	.practice-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: 100%;
		max-width: 28rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	.practice-error {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.practice-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-3);

		button {
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-4);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-secondary;
		}

		.practice-submit {
			@include buttons.btn-primary;
		}
	}
</style>
