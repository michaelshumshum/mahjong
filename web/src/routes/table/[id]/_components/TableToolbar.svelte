<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import type { ConnectionStatus } from '$lib/game/state';

	let {
		spectating,
		tableId,
		isPractice,
		connection,
		onLeaveClick,
		onToggleScoreSheet,
		onToggleSettings,
		onOpenGuide
	}: {
		spectating: boolean;
		tableId: string;
		isPractice: boolean;
		connection?: ConnectionStatus;
		onLeaveClick: () => void;
		onToggleScoreSheet: () => void;
		onToggleSettings: () => void;
		onOpenGuide: () => void;
	} = $props();
</script>

<!-- the rim's top edge (frontend.md §3): wind, wall and prevailing live on the SeatPlate and
     CenterHub, never here. -->
<header class="table-toolbar">
	<button type="button" class="rail-btn" onclick={onLeaveClick}>
		<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
			<path d="M15 6 9 12l6 6" />
		</svg>
		<span class="rail-label">{m.tableToolbar_leaveGameLabel()}</span>
	</button>

	<div class="table-ident">
		<span class="table-code" aria-label={m.tableToolbar_codeAriaLabel({ code: tableId })}
			>{tableId}</span
		>
		{#if spectating}
			<span class="table-tag">{m.tableToolbar_spectatingLabel()}</span>
		{:else if isPractice}
			<span class="table-tag">{m.tableToolbar_practiceLabel()}</span>
		{/if}
	</div>

	<div class="table-status" aria-label={m.tableToolbar_tableStatusAriaLabel()}>
		{#if connection === 'resyncing' || connection === 'closed' || connection === 'connecting'}
			<span class="connection-pill" data-testid="connection-pill">
				{connection === 'resyncing'
					? m.tableToolbar_connectionResyncingLabel()
					: m.tableToolbar_connectionReconnectingLabel()}
			</span>
		{/if}
	</div>

	<div class="chrome-toggles">
		<button type="button" class="rail-btn" data-testid="open-guide" onclick={onOpenGuide}>
			<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
				<path
					d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15H5.5A1.5 1.5 0 0 0 4 20.5zM20 5.5A1.5 1.5 0 0 0 18.5 4H13v15h5.5a1.5 1.5 0 0 1 1.5 1.5z"
				/>
			</svg>
			<span class="rail-label">{m.tableToolbar_guideButton()}</span>
		</button>
		<button
			type="button"
			class="rail-btn"
			data-testid="toggle-score-sheet"
			onclick={onToggleScoreSheet}
		>
			<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
				<rect x="4" y="4" width="16" height="16" rx="2" />
				<path d="M4 9.5h16M4 14.5h16M10 4v16" />
			</svg>
			<span class="rail-label">{m.tableToolbar_scoreSheetButton()}</span>
		</button>
		{#if !spectating}
			<button
				type="button"
				class="rail-btn"
				data-testid="toggle-settings"
				onclick={onToggleSettings}
			>
				<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
					<circle cx="12" cy="12" r="3" />
					<path
						d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"
					/>
				</svg>
				<span class="rail-label">{m.tableToolbar_settingsButton()}</span>
			</button>
		{/if}
	</div>
</header>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/a11y';
	@use '$lib/styles/layout';

	// same walnut as .table-surface's border; the page drops the surface's top border so the two
	// read as one frame.
	.table-toolbar {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
		padding: var(--space-1) var(--space-2) 0;
		border-radius: var(--radius-lg) var(--radius-lg) 0 0;
		background: var(--color-rim);
		box-shadow: inset 0 2px 0 -1px var(--color-rim-hi);
	}

	.rail-btn {
		display: inline-flex;
		flex-shrink: 0;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		min-width: var(--tap-target-min);
		min-height: var(--tap-target-min);
		padding: 0 var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-ghost;
		text-shadow: none;

		svg {
			width: 18px;
			height: 18px;
			flex-shrink: 0;
			fill: none;
			stroke: currentColor;
			stroke-width: 1.8;
			stroke-linecap: round;
			stroke-linejoin: round;
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}
	}

	.table-ident {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
	}

	// a small cousin of the waiting room's .pretable-code chip.
	.table-code {
		padding: 2px var(--space-2);
		border-radius: 5px;
		background: var(--color-tile);
		color: var(--color-tile-ink);
		font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
		font-size: var(--font-size-sm);
		font-weight: 700;
		letter-spacing: 0.14em;
		box-shadow:
			0 2px 0 var(--color-tile-edge),
			0 3px 0 var(--color-tile-side);
		user-select: all;
		white-space: nowrap;
	}

	.table-tag {
		padding: 1px var(--space-2);
		border: 1px solid color-mix(in srgb, var(--color-brass) 45%, transparent);
		border-radius: 999px;
		color: var(--color-brass);
		font-size: var(--font-size-xs);
		font-weight: 700;
		white-space: nowrap;
	}

	.table-status {
		display: flex;
		flex: 1;
		justify-content: flex-end;
		min-width: 0;
	}

	.connection-pill {
		padding: 0 var(--space-2);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-accent);
		color: var(--color-accent-on-dark);
		font-size: var(--font-size-xs);
		font-weight: 700;
		white-space: nowrap;
		@include a11y.motion-ok {
			animation: connection-pill-pulse 1.4s ease-in-out infinite;
		}
	}

	@keyframes connection-pill-pulse {
		50% {
			opacity: 0.5;
		}
	}

	.chrome-toggles {
		display: flex;
		gap: var(--space-1);
	}

	// icon-only below tablet-up; the label stays as the accessible name.
	@include layout.phone-only {
		.table-toolbar {
			gap: var(--space-1);
			padding-inline: var(--space-1);
		}

		.rail-btn {
			padding: 0;
		}

		.rail-label {
			@include a11y.sr-only;
		}
	}
</style>
