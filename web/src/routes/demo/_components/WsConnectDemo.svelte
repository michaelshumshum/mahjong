<script lang="ts">
	import { onDestroy } from 'svelte';
	import { MahjongSocket } from '$lib/net/socket';
	import { reduce } from '$lib/net/reducer';
	import { initialClientGameState } from '$lib/game/state';
	import type { Pong } from '$lib/net/protocol';
	import { m } from '$lib/paraglide/messages.js';

	let status = $state<'idle' | 'connecting' | 'connected'>('idle');
	let lastPong = $state<Pong['d'] | null>(null);

	let socket: MahjongSocket | null = null;
	let unsubscribe: (() => void) | null = null;

	// connect, hello, ping, render the pong. Doesn't wire up lib/game/store.svelte.ts --
	// reduce() is called here only to exercise the reducer skeleton, its return value unused.
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

		// poll briefly for OPEN before pinging rather than adding a send queue for this one call.
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

<h2>{m.wsConnectDemo_heading()}</h2>
<button onclick={connectAndPing} disabled={status !== 'idle'}
	>{m.wsConnectDemo_connectButton()}</button
>
<p>status: {status}</p>
{#if lastPong}
	<p data-testid="pong-result">pong: t0={lastPong.t0} t1={lastPong.t1}</p>
{/if}
