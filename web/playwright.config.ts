import { defineConfig } from '@playwright/test';

// a built preview, not `vite dev`: dev's unbundled message modules made page loads flaky (docs/testing.md §4)
const PORT = 4180;

export default defineConfig({
	webServer: {
		command: `vite build && vite preview --port ${PORT} --strictPort`,
		port: PORT,
		// never reused: a stale build or a dev server must not answer
		reuseExistingServer: false,
		timeout: 120_000,
		gracefulShutdown: { signal: 'SIGTERM', timeout: 500 }
	},
	testMatch: '**/*.e2e.{ts,js}'
});
