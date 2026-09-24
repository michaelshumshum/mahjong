<script lang="ts">
	import type { Seat } from './mock-game-state';

	let {
		seat,
		self = false,
		status,
		name,
		onJoin
	}: {
		seat: Seat;
		self?: boolean;
		status: string;
		name: string | null;
		onJoin: (seat: Seat) => void;
	} = $props();
	let open = $derived(status === 'empty');
</script>

<button
	type="button"
	class="seat-ring-slot seat-ring-slot--pickable"
	class:seat-ring-slot--self={self}
	class:seat-ring-slot--open={open}
	disabled={!open}
	onclick={() => onJoin(seat)}
>
	<span>{open ? 'Open' : status === 'bot' ? 'Bot' : (name ?? 'Taken')}</span>
</button>

<style lang="scss">
	.seat-ring-slot {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2.75rem;
		height: 2.75rem;
		border-radius: 50%;
		border: 1px dashed var(--color-border);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 600;
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	.seat-ring-slot--self {
		border: 1px solid var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 16%, transparent);
		color: var(--color-text);
		animation: none;
	}

	@keyframes seat-ring-breathe {
		0%,
		100% {
			opacity: 0.5;
		}
		50% {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.seat-ring-slot {
			animation: none;
			opacity: 0.85;
		}
	}

	// a taken seat reads as solid/inert rather than breathing; an open one is a clickable button.
	.seat-ring-slot--pickable {
		font: inherit;
		background: none;
		animation: none;
		opacity: 1;

		&:disabled {
			cursor: default;
			opacity: 0.7;
		}
	}

	.seat-ring-slot--open {
		border: 1px solid var(--color-accent);
		color: var(--color-text);
		cursor: pointer;

		&:hover {
			background: color-mix(in srgb, var(--color-accent) 12%, transparent);
		}
	}
</style>
