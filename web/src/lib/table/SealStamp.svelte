<script lang="ts">
	// `position` is the claimer's table side: the hub cell edge facing their pool, never mid-hub.
	// caller keys it to replay the entrance and never renders it under reduced motion.
	let {
		glyph,
		position = null
	}: {
		glyph: string;
		position?: 'self' | 'across' | 'left' | 'right' | null;
	} = $props();
</script>

<span
	class="seal-stamp"
	class:seal-stamp--placed={position}
	data-position={position}
	aria-hidden="true"
>
	{glyph}
</span>

<style lang="scss">
	@use '$lib/styles/layout';

	.seal-stamp {
		z-index: 2;
		display: grid;
		place-items: center;
		width: 4.5rem;
		height: 4.5rem;
		border: 3px solid var(--color-accent);
		border-radius: 50%;
		font-size: var(--font-size-xl);
		font-weight: 700;
		line-height: 1;
		color: var(--color-accent);
		background: rgb(0 0 0 / 0.6);
		box-shadow: 0 4px 14px rgb(0 0 0 / 0.45);
		pointer-events: none;
		opacity: 0;
		animation: seal-stamp var(--dur-4) var(--ease-place) forwards;
	}

	// below tablet-up the pools stack instead of boxing the hub, so the badge just centres.
	.seal-stamp--placed {
		position: absolute;
		top: 50%;
		left: 50%;
		margin: -2.25rem 0 0 -2.25rem;

		@include layout.tablet-up {
			position: relative;
			top: auto;
			left: auto;
			grid-area: hub;
			margin: var(--space-3);
		}
	}

	.seal-stamp--placed[data-position='self'] {
		@include layout.tablet-up {
			align-self: end;
			justify-self: center;
		}
	}

	.seal-stamp--placed[data-position='across'] {
		@include layout.tablet-up {
			align-self: start;
			justify-self: center;
		}
	}

	.seal-stamp--placed[data-position='left'] {
		@include layout.tablet-up {
			align-self: center;
			justify-self: start;
		}
	}

	.seal-stamp--placed[data-position='right'] {
		@include layout.tablet-up {
			align-self: center;
			justify-self: end;
		}
	}

	@keyframes seal-stamp {
		0% {
			opacity: 0;
			scale: 1.4;
			rotate: -8deg;
		}
		25% {
			opacity: 1;
			scale: 1;
			rotate: 3deg;
		}
		70% {
			opacity: 1;
			scale: 1;
			rotate: 0deg;
		}
		100% {
			opacity: 0;
			scale: 1;
			rotate: 0deg;
		}
	}
</style>
