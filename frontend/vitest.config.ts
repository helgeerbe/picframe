import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * Vitest configuration for the frontend test suite (#769).
 *
 * Kept separate from `vite.config.ts` and `vite.overlay.config.ts` (the two
 * production builds) so test-only settings never perturb the SPA/overlay
 * bundle output. The Vue plugin is included so future component tests can
 * mount `.vue` SFCs without a second tooling change.
 *
 * Design decisions:
 *  - `environment: 'happy-dom'` — lighter than jsdom; sufficient for the
 *    synthetic `PointerEvent`/`KeyboardEvent`/`window.picframe` stubs the
 *    overlay tests need.
 *  - `globals: false` — explicit `import { describe, it, expect, vi } from
 *    'vitest'`; zero ESLint churn, keeps `noUnusedLocals` honest without an
 *    `eslint-plugin-vitest`.
 *  - Co-located spec files (`src` + `.test.ts`), flat mirroring of `src/`.
 *  - Coverage is report-only (no threshold) for the initial suite.
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: false,
    include: ['src/**/*.{test,spec}.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json-summary'],
    },
  },
})
