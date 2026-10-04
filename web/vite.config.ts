import { paraglideVitePlugin } from '@inlang/paraglide-js';
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
		}),

		paraglideVitePlugin({
			project: './project.inlang',
			outdir: './src/lib/paraglide',
			emitTsDeclarations: true,
			// no 'url' strategy: table invite links (/table/ABC123) must stay locale-agnostic
			// (docs/frontend.md §9's locale strategy).
			strategy: ['cookie', 'baseLocale'],
			// pinned: "locale-modules" (the dev default) drops the per-call `{ locale }` override
			// LocaleSwitcher needs to render each option in its own language regardless of UI locale.
			outputStructure: 'message-modules'
		})
	],
	test: {
		expect: { requireAssertions: true },
		coverage: {
			provider: 'v8',
			reporter: ['text', 'json-summary'],
			reportsDirectory: './coverage',
			exclude: ['src/lib/paraglide/**']
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
					// runes ($effect) no-op under Vite's SSR compile target (jsdom doesn't change that) --
					// real browser mode actually executes them. See web/AGENTS.md's "Testing a *.svelte.ts file's runes" note.
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
