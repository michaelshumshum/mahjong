<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { fetchServerStatus, type StatusResponse } from '$lib/net/server-status';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import CircleX from '@lucide/svelte/icons/circle-x';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import TriangleAlert from '@lucide/svelte/icons/triangle-alert';
	import Sparkline from './_components/Sparkline.svelte';

	claimMuralVisible();

	const REFRESH_MS = 15_000;

	let status = $state<StatusResponse | null>(null);
	let unreachable = $state(false);
	let updatedAt = $state<Date | null>(null);
	let updatedLabel = $derived(
		updatedAt
			? updatedAt.toLocaleTimeString(getLocale(), { hour: 'numeric', minute: '2-digit' })
			: null
	);

	async function refresh(): Promise<void> {
		try {
			status = await fetchServerStatus();
			unreachable = false;
			updatedAt = new Date();
		} catch {
			unreachable = true;
		}
	}

	$effect(() => {
		refresh();
		const timer = setInterval(refresh, REFRESH_MS);
		return () => clearInterval(timer);
	});

	type Banner = 'checking' | 'ok' | 'degraded' | 'draining' | 'unreachable';
	let banner = $derived<Banner>(unreachable ? 'unreachable' : (status?.status ?? 'checking'));
	const BANNER_TEXT: Record<Banner, () => string> = {
		checking: m.statusPage_checking,
		ok: m.statusPage_ok,
		degraded: m.statusPage_degraded,
		draining: m.statusPage_draining,
		unreachable: m.statusPage_unreachable
	};

	function ms(value: number): string {
		return m.statusPage_ms({ value: value < 10 ? value.toFixed(1) : String(Math.round(value)) });
	}

	function count(value: number | null): string {
		return value === null ? m.statusPage_notAvailable() : value.toLocaleString(getLocale());
	}

	function uptime(seconds: number): string {
		const days = Math.floor(seconds / 86_400);
		const hours = Math.floor((seconds % 86_400) / 3_600);
		const minutes = Math.floor((seconds % 3_600) / 60);
		return days > 0
			? m.statusPage_uptimeDays({ days, hours })
			: m.statusPage_uptimeHours({ hours, minutes });
	}

	let tiles = $derived(
		status === null
			? []
			: [
					{
						id: 'players',
						label: m.statusPage_playersOnline(),
						value: count(status.players_online),
						detail: m.statusPage_spectatorsDetail({ count: status.spectators })
					},
					{
						id: 'tables',
						label: m.statusPage_tablesPlaying(),
						value: count(status.tables_playing),
						detail: m.statusPage_tablesWaitingDetail({ count: status.tables_waiting })
					},
					{
						id: 'games',
						label: m.statusPage_gamesFinished(),
						value: count(status.games_finished_24h),
						detail: m.statusPage_gamesFinishedDetail()
					},
					{
						id: 'bots',
						label: m.statusPage_botResponse(),
						value: status.bot_decision_ms
							? ms(status.bot_decision_ms.p50_ms)
							: m.statusPage_notAvailable(),
						detail: status.bot_decision_ms
							? m.statusPage_botResponseDetail({
									ms: Math.round(status.bot_decision_ms.p95_ms)
								})
							: m.statusPage_botIdle()
					},
					{
						id: 'responsiveness',
						label: m.statusPage_responsiveness(),
						value: ms(status.loop_lag_ms),
						detail: m.statusPage_responsivenessDetail()
					},
					{
						id: 'capacity',
						label: m.statusPage_capacity(),
						value:
							status.capacity_pct === null
								? m.statusPage_notAvailable()
								: m.statusPage_percent({ value: status.capacity_pct }),
						detail: null
					},
					{
						id: 'uptime',
						label: m.statusPage_uptime(),
						value: uptime(status.uptime_seconds),
						detail: null
					}
				]
	);

	let playersSeries = $derived(
		(status?.history ?? []).map((p) => ({ ts: p.ts, value: p.players }))
	);
	let botSeries = $derived((status?.history ?? []).map((p) => ({ ts: p.ts, value: p.bot_p95_ms })));
</script>

<svelte:head>
	<title>{m.statusPage_pageTitle()}</title>
</svelte:head>

<div class="status-page">
	<header class="page-header">
		<BackButton label={m.statusPage_backLabel()} href="/" />
		<h1>{m.statusPage_title()}</h1>
		{#if updatedLabel}
			<span class="updated" data-testid="status-updated"
				>{m.statusPage_updatedAt({ time: updatedLabel })}</span
			>
		{/if}
	</header>

	<p class="banner banner-{banner}" data-testid="status-banner" data-status={banner} role="status">
		{#if banner === 'ok'}
			<CircleCheck size={20} aria-hidden="true" />
		{:else if banner === 'degraded'}
			<TriangleAlert size={20} aria-hidden="true" />
		{:else if banner === 'draining'}
			<RefreshCw size={20} aria-hidden="true" />
		{:else if banner === 'unreachable'}
			<CircleX size={20} aria-hidden="true" />
		{/if}
		<span>{BANNER_TEXT[banner]()}</span>
	</p>

	{#if status !== null}
		<dl class="tiles" class:stale={unreachable}>
			{#each tiles as tile (tile.id)}
				<div class="tile" data-testid="status-tile-{tile.id}">
					<dt>{tile.label}</dt>
					<dd class="value">{tile.value}</dd>
					{#if tile.detail}
						<dd class="detail">{tile.detail}</dd>
					{/if}
				</div>
			{/each}
		</dl>

		<div class="charts" class:stale={unreachable}>
			<Sparkline
				testid="status-chart-players"
				label={m.statusPage_playersChart()}
				points={playersSeries}
				format={count}
			/>
			<Sparkline
				testid="status-chart-bots"
				label={m.statusPage_botChart()}
				points={botSeries}
				format={ms}
			/>
		</div>

		<p class="note">{m.statusPage_historyNote()}</p>
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/layout';

	.status-page {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(60rem, 100%);
		margin: 0 auto;
		padding: var(--space-5);

		@include layout.phone-only {
			padding: var(--space-4);
		}
	}

	.page-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3) var(--space-4);

		h1 {
			margin: 0;
			margin-inline-end: auto;
			font-size: var(--font-size-xl);
		}
	}

	.updated,
	.note {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.note {
		margin: 0;
	}

	.banner {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin: 0;
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-left: 4px solid var(--banner-color, var(--color-border));
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface-raised) 92%, transparent);
		font-weight: 600;

		:global(svg) {
			flex-shrink: 0;
			color: var(--banner-color, var(--color-text-muted));
		}
	}

	.banner-ok {
		--banner-color: var(--color-positive);
	}

	.banner-degraded,
	.banner-draining {
		--banner-color: var(--color-brass);
	}

	.banner-unreachable {
		--banner-color: var(--color-status-error);
	}

	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
		gap: var(--space-4);
		margin: 0;

		@include layout.phone-only {
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: var(--space-3);
		}
	}

	.tile {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface-raised) 92%, transparent);

		dt {
			color: var(--color-text-muted);
			font-size: var(--font-size-sm);
		}

		dd {
			margin: 0;
		}
	}

	.value {
		font-size: var(--font-size-2xl);
		font-weight: 700;

		@include layout.phone-only {
			font-size: var(--font-size-xl);
		}
	}

	.detail {
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
	}

	.charts {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
		gap: var(--space-4);
	}

	// last good numbers stay up while unreachable, dimmed so they don't read as live
	.stale {
		opacity: 0.5;
	}
</style>
