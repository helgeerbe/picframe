/**
 * Overlay shell entry point (#739).
 *
 * Loaded by the out-of-process WebKitGTK worker via `file://.../overlay/index.html`.
 * Mounts the `OverlayShell` on `#overlay-root`.
 */

import './style.css'
import { OverlayShell } from './shell'

declare global {
  interface Window {
    // Set by the boot try/catch below so the worker's bridge-independent JS
    // probe (`_probe_shell_state`) can report a synchronous boot throw even
    // when the message-handler bridge itself is broken (#739).
    __pfBootErr?: string
  }
}

const root = document.getElementById('overlay-root')
if (root) {
  try {
    const shell = new OverlayShell(root)
    shell.boot()
  } catch (e) {
    // Record the boot failure for the worker probe (the TS shell emits no
    // console output, so without this a throw is invisible in the journal),
    // then re-throw so the window.onerror forwarder still reports it when
    // the bridge works (#739).
    try {
      window.__pfBootErr = e instanceof Error && e.stack ? e.stack : String(e)
    } catch {
      /* ignore */
    }
    throw e
  }
}
