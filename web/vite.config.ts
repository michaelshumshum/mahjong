import { defineConfig } from 'vitest/config';
import adapter from '@sveltejs/adapter-node';
import { sveltekit } from '@sveltejs/kit/vite';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import { playwright } from '@vitest/browser-playwright';

export default defineConfig({
	plugins: [
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},
			adapter: adapter(),
			// passing options here (vs. a svelte.config.js) means this is also where <style
			// lang="scss"> preprocessing gets wired up — see web/AGENTS.md's SCSS convention.
			preprocess: vitePreprocess()
		})
	],
	test: {
		expect: { requireAssertions: true },
		coverage: {
			provider: 'v8',
			reporter: ['text', 'json-summary'],
			reportsDirectory: './coverage'
		},
		projects: [
			{
				extends: './vite.config.ts',
				test: {
					name: 'server',
					environment: 'node',
					include: ['src/**/*.{test,spec}.{js,ts}'],
					exclude: ['src/**/*.svelte.{test,spec}.{js,ts}']
				}
			},
			{
				extends: './vite.config.ts',
				test: {
					// Runes-based reactive code ($effect/$effect.root — e.g. lib/game/store.svelte.ts)
					// no-ops under Vite's SSR compile target, which is what every other test here uses
					// (Svelte's server runtime never runs effects — there's no DOM to react into, and
					// Vitest's `environment: 'jsdom'` doesn't change that: modules still load through
					// Vite's SSR module runner even with jsdom's globals polyfilled in, so $effect still
					// never fires). Real browser mode (already have playwright installed for e2e/
					// screenshots, so this reuses it rather than adding a second browser toolchain) is
					// the only way Vitest compiles a module client-side, so this is the one project
					// where effects actually execute — for the one kind of test that needs that: a
					// *.svelte.{test,spec}.ts file.
					name: 'client',
					include: ['src/**/*.svelte.{test,spec}.{js,ts}'],
					browser: {
						enabled: true,
						provider: playwright(),
						instances: [{ browser: 'chromium' }]
					}
				}
			}
		]
	}
});
