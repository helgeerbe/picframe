import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

/**
 * Second Vite entry for the WebKitGTK overlay shell (#739, item 10).
 *
 * The overlay is loaded by the out-of-process worker via `file://`, so it must
 * use *relative* asset references (`base: './'`) and live in its own output
 * directory (`html/overlay/`) with its own `assets/` — the main SPA keeps
 * `base: '/'` for history-mode routing. The overlay shell is a lightweight
 * TS + DOM page (no Vue/Pinia/router), so no plugins are required.
 */
export default defineConfig({
  base: './',
  build: {
    outDir: '../src/picframe/html/overlay',
    emptyOutDir: true,
    rollupOptions: {
      input: fileURLToPath(new URL('./overlay.html', import.meta.url)),
    },
  },
})
