/**
 * Overlay shell entry point (#739).
 *
 * Loaded by the out-of-process WebKitGTK worker via `file://.../overlay/index.html`.
 * Mounts the `OverlayShell` on `#overlay-root`.
 */

import './style.css'
import { OverlayShell } from './shell'

const root = document.getElementById('overlay-root')
if (root) {
  const shell = new OverlayShell(root)
  shell.boot()
}
