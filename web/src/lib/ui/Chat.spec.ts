import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Chat, { CANNED_PHRASES } from './Chat.svelte';
import type { ChatEntry } from './Chat.svelte';

// `onSend` firing on click is exercised end-to-end (routes/page.e2e.ts) against the demo section
// on `/`, same as ClaimButtons' `onChoose` — svelte/server only renders markup, there's no DOM to
// dispatch a real click event against here.
describe('Chat', () => {
	const noop = () => {};

	it('renders one button per canned phrase, nothing else', () => {
		const { body } = render(Chat, { props: { messages: [], onSend: noop } });
		expect([...body.matchAll(/<button/g)]).toHaveLength(CANNED_PHRASES.length);
		for (const phrase of CANNED_PHRASES) {
			expect(body).toContain(`>${phrase}<`);
		}
	});

	it('renders scrollback entries with seat label, phrase, and time', () => {
		const messages: ChatEntry[] = [
			{ seat: 0, phrase: 'Good game', ts: Date.UTC(2026, 0, 1, 12, 30) },
			{ seat: 2, phrase: 'Nice hand!', ts: Date.UTC(2026, 0, 1, 12, 31) }
		];
		const { body } = render(Chat, { props: { messages, onSend: noop } });
		expect(body).toContain('East');
		expect(body).toContain('West');
		expect(body).toContain('Good game');
		expect(body).toContain('Nice hand!');
	});

	it('renders an empty scrollback with no entries when there are no messages', () => {
		const { body } = render(Chat, { props: { messages: [], onSend: noop } });
		expect(body).not.toContain('class="entry"');
	});
});
