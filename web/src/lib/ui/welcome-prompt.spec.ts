import { afterEach, describe, expect, it } from 'vitest';
import { dismissWelcome, resetWelcomeForTests, shouldPromptWelcome } from './welcome-prompt';

const LOBBY = new URL('http://localhost/');

describe('shouldPromptWelcome', () => {
	afterEach(resetWelcomeForTests);

	it('asks a nameless guest, with accounts on or off', () => {
		expect(shouldPromptWelcome('guest', null, LOBBY)).toBe(true);
		expect(shouldPromptWelcome('off', null, LOBBY)).toBe(true);
		expect(shouldPromptWelcome('guest', '   ', LOBBY)).toBe(true);
	});

	it('never asks a named guest, a signed-in player, or before /me answers', () => {
		expect(shouldPromptWelcome('guest', 'Mei', LOBBY)).toBe(false);
		expect(shouldPromptWelcome('signedIn', null, LOBBY)).toBe(false);
		expect(shouldPromptWelcome('loading', null, LOBBY)).toBe(false);
	});

	it('leaves a sign-in callback load to its own dialog', () => {
		expect(shouldPromptWelcome('guest', null, new URL('http://localhost/?signin=failed'))).toBe(
			false
		);
		expect(shouldPromptWelcome('guest', null, new URL('http://localhost/?signup=1'))).toBe(false);
	});

	it('stays quiet for the rest of the page load once dismissed', () => {
		dismissWelcome();
		expect(shouldPromptWelcome('guest', null, LOBBY)).toBe(false);
	});
});
