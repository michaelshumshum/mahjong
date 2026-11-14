<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchMyGames, type MyGame } from '$lib/net/account';
	import { m } from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import BotBadge from '$lib/table/BotBadge.svelte';
	import { formatGameDate, modeLabel, seatName } from './my-games';
	import { formatSigned } from './score-format';
	import { rankLabel, RANK_TONE } from './rank';

	let games = $state<MyGame[]>([]);
	let next = $state<number | null>(null);
	let phase = $state<'loading' | 'ready' | 'error'>('loading');
	let loadingMore = $state(false);
	let moreFailed = $state(false);

	async function loadFirst(): Promise<void> {
		phase = 'loading';
		try {
			({ games, next } = await fetchMyGames({}));
			phase = 'ready';
		} catch {
			phase = 'error';
		}
	}

	async function loadMore(): Promise<void> {
		if (next === null) return;
		loadingMore = true;
		moreFailed = false;
		try {
			const page = await fetchMyGames({ before: next });
			games = [...games, ...page.games];
			next = page.next;
		} catch {
			moreFailed = true;
		} finally {
			loadingMore = false;
		}
	}

	onMount(() => {
		void loadFirst();
	});
</script>

<div class="my-games" data-testid="my-games">
	{#if phase === 'loading'}
		<p class="note" role="status">{m.myGames_loading()}</p>
	{:else if phase === 'error'}
		<p class="note note--error" role="alert">{m.myGames_error()}</p>
		<button type="button" class="secondary" onclick={loadFirst}>{m.myGames_retry()}</button>
	{:else if games.length === 0}
		<p class="note" data-testid="my-games-empty">{m.myGames_empty()}</p>
	{:else}
		<ol class="games">
			{#each games as game (game.game_id)}
				<li class="game" data-testid="my-game">
					<div class="result">
						<span class="place" style:--rank-tone={RANK_TONE[game.placement - 1]}>
							{rankLabel(game.placement - 1)}
						</span>
						<span class="score">{formatSigned(game.final_score)}</span>
					</div>
					<div class="meta">
						<time datetime={game.created_at}>{formatGameDate(game.created_at, getLocale())}</time>
						{#if modeLabel(game.mode)}<span>{modeLabel(game.mode)}</span>{/if}
						{#if game.hand_count !== null}
							<span>{m.myGames_handCount({ count: game.hand_count })}</span>
						{/if}
					</div>
					<ul class="opponents" aria-label={m.myGames_opponentsLabel()}>
						{#each game.others as seat (seat.seat)}
							<li>
								{#if seat.kind === 'bot'}
									<BotBadge level={seat.bot_tier} />
								{:else}
									{seatName(seat)}
								{/if}
							</li>
						{/each}
					</ul>
				</li>
			{/each}
		</ol>
		{#if moreFailed}
			<p class="note note--error" role="alert">{m.myGames_error()}</p>
		{/if}
		{#if next !== null}
			<button
				type="button"
				class="secondary"
				disabled={loadingMore}
				data-testid="my-games-more"
				onclick={loadMore}
			>
				{loadingMore ? m.myGames_loadingMore() : m.myGames_loadMore()}
			</button>
		{/if}
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/forms';

	.my-games {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
	}

	.games {
		display: flex;
		flex-direction: column;
		align-self: stretch;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.game {
		@include forms.settings-card;
		display: grid;
		grid-template-columns: 5rem 1fr;
		gap: var(--space-1) var(--space-3);
		padding-block: var(--space-3);
	}

	.result {
		display: flex;
		flex-direction: column;
		grid-row: span 2;
	}

	.place {
		color: var(--rank-tone, var(--color-text));
		font-weight: 700;
	}

	.score {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.meta {
		display: flex;
		flex-wrap: wrap;
		gap: 0 var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.opponents {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.note {
		margin: 0;
		color: var(--color-text-muted);
	}

	.note--error {
		color: var(--color-status-error);
	}

	.secondary {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
	}
</style>
