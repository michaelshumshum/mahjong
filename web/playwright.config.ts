import { defineConfig } from '@playwright/test';

// a built preview, not `vite dev`: dev's unbundled message modules made page loads flaky (docs/testing.md §4)
const PORT = 4180;
// the same build previewed again with the sign-in ui on; servers start in order, after the build
export const ACCOUNTS_PORT = 4181;

const shared = {
	// never reused: a stale build or a dev server must not answer
	reuseExistingServer: false,
	timeout: 120_000,
	gracefulShutdown: { signal: 'SIGTERM', timeout: 500 }
} as const;

export default defineConfig({
	webServer: [
		{ ...shared, command: `vite build && vite preview --port ${PORT} --strictPort`, port: PORT },
		{
			...shared,
			command: `vite preview --port ${ACCOUNTS_PORT} --strictPort`,
			port: ACCOUNTS_PORT,
			env: { PUBLIC_ACCOUNTS_ENABLED: '1' }
		}
	],
	// an array of servers sets no baseURL on its own
	use: { baseURL: `http://localhost:${PORT}` },
	testMatch: '**/*.e2e.{ts,js}'
});
