<script lang="ts">
	import { onDestroy } from 'svelte';
	import { MahjongSocket } from '$lib/net/socket';
	import { reduce } from '$lib/net/reducer';
	import { initialClientGameState } from '$lib/game/state';
	import type { Pong } from '$lib/net/protocol';

	let status = $state<'idle' | 'connecting' | 'connected'>('idle');
	let lastPong = $state<Pong['d'] | null>(null);

	let socket: MahjongSocket | null = null;
	let unsubscribe: (() => void) | null = null;

	// M0 demo (docs/05-roadmap.md §2): connect, hello, ping, render the pong.
	// This page doesn't wire up lib/game/store.svelte.ts (that's /table/[id]'s job, a later
	// sub-task) — reduce() is called here only to exercise the reducer skeleton, its return
	// value is unused.
	function connectAndPing(): void {
		if (socket) return;
		status = 'connecting';

		const s = new MahjongSocket();
		socket = s;
		unsubscribe = s.onEvent((event) => {
			reduce(initialClientGameState(), event);
			if (event.t === 'pong') lastPong = event.d;
		});
		s.connect();

		// hello fires on open inside socket.ts; poll briefly for OPEN before
		// pinging rather than adding a send queue for this one demo call.
		const trySend = () => {
			if (s.readyState === WebSocket.OPEN) {
				status = 'connected';
				s.ping();
			} else if (s.readyState === WebSocket.CONNECTING) {
				setTimeout(trySend, 50);
			}
		};
		trySend();
	}

	onDestroy(() => {
		unsubscribe?.();
		socket?.disconnect();
	});
</script>

<h2>WS connect/ping/pong demo</h2>
<button onclick={connectAndPing} disabled={status !== 'idle'}>Connect + ping</button>
<p>status: {status}</p>
{#if lastPong}
	<p data-testid="pong-result">pong: t0={lastPong.t0} t1={lastPong.t1}</p>
{/if}
