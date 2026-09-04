import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'

/**
 * Second Vite entry for the WebKitGTK overlay shell (#739, item 10).
 *
 * The overlay is loaded by the out-of-process worker via `file://`, so it must
 * use *relative* asset references (`base: './'`) and live in its own output
 * directory (`html/overlay/`) with its own `assets/` — the main SPA keeps
 * `base: '/'` for history-mode routing. The overlay shell is a lightweight
 * TS + DOM page (no Vue/Pinia/router), so no plugins are required.
 *
 * The build is inlined into a single self-contained `overlay.html` (classic
 * `<script>` + `<style>`, zero external subresources). This is mandatory for
 * `file://`: WebKitGTK (like browsers) blocks *external* `<script type="module">
 * under `file://` because there is no CORS origin to satisfy the module-script
 * requirement, so the Vite-emitted `<script type="module" crossorigin src="...">`
 * never executes and the clock never appears. Inlining removes every external
 * fetch, so the shell boots with no CORS/module constraints (#739).
 */
function overlaySingleFileInline(): Plugin {
  const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return {
    name: 'overlay-single-file-inline',
    apply: 'build',
    enforce: 'post',
    generateBundle(_options, bundle) {
      const htmlKey = Object.keys(bundle).find((k) => k.endsWith('.html'))
      if (!htmlKey) return
      const htmlAsset = bundle[htmlKey]
      if (!htmlAsset || htmlAsset.type !== 'asset') return
      let html = String(htmlAsset.source)

      // Inline each emitted JS chunk as a classic <script> and remove its
      // external module-script tag. The bundled output is an IIFE (see
      // rollupOptions.output.format below), so a plain classic <script> runs
      // it with no module/CORS semantics.
      const inlinedScripts: string[] = []
      for (const [fileName, chunk] of Object.entries(bundle)) {
        if (chunk.type === 'chunk' && fileName.endsWith('.js')) {
          const srcRe = new RegExp(
            `<script\\b[^>]*\\bsrc=["'][^"']*?${escapeRe(fileName)}["'][^>]*></script>`,
            'g',
          )
          html = html.replace(srcRe, '')
          inlinedScripts.push(`<script>\n${chunk.code}\n</script>`)
          delete bundle[fileName]
        } else if (chunk.type === 'asset' && fileName.endsWith('.css')) {
          const css = String(chunk.source)
          const linkRe = new RegExp(
            `<link\\b[^>]*\\bhref=["'][^"']*?${escapeRe(fileName)}["'][^>]*>`,
            'g',
          )
          html = html.replace(linkRe, `<style>\n${css}\n</style>`)
          delete bundle[fileName]
        }
      }
      // Drop any leftover modulepreload/preload hints — with everything inlined
      // there are no external resources to preload.
      html = html.replace(/<link\b[^>]*\brel=["']module?preload["'][^>]*>/gi, '')

      // Place the inlined classic scripts at the end of <body> so #overlay-root
      // exists when the shell boots (a classic script in <head> would run
      // before the body is parsed).
      if (inlinedScripts.length) {
        const block = inlinedScripts.join('\n')
        if (/<\/body>/i.test(html)) {
          html = html.replace(/<\/body>/i, `${block}\n</body>`)
        } else {
          html += `\n${block}`
        }
      }
      htmlAsset.source = html
    },
  }
}

export default defineConfig({
  base: './',
  build: {
    outDir: '../src/picframe/html/overlay',
    emptyOutDir: true,
    // Single IIFE chunk with no external assets -> inlined into overlay.html.
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    rollupOptions: {
      input: fileURLToPath(new URL('./overlay.html', import.meta.url)),
      output: {
        format: 'iife',
        inlineDynamicImports: true,
      },
    },
  },
  plugins: [overlaySingleFileInline()],
})

