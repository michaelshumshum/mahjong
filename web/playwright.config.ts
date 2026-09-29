import { defineConfig } from '@playwright/test';

export default defineConfig({
	webServer: {
		command: 'vite dev',
		port: 5173,
		reuseExistingServer: !process.env.CI,
		gracefulShutdown: { signal: 'SIGTERM', timeout: 500 }
	},
	testMatch: '**/*.e2e.{ts,js}'
});
