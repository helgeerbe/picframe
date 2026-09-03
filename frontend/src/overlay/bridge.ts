/**
 * JS bridge between the overlay shell and the out-of-process worker (#739).
 *
 * The worker injects `window.picframe.send` (a thin wrapper over
 * `webkit.messageHandlers.picframe.postMessage`) so the shell can emit input
 * actions back to the main process. The shell *adds* `applyConfig` to the same
 * object so the worker can push the live shell config via `evaluate_javascript`
 * without round-tripping through the message handler.
 *
 * In dev/preview (no WebKitGTK), `window.picframe` is absent; calls degrade to
 * no-ops so the shell can still be inspected with `vite preview`.
 */

import type { InputAction, OverlayShellConfig } from './types'

type ApplyConfigHandler = (config: OverlayShellConfig) => void

interface PicframeBridge {
  send: (action: InputAction | { action: InputAction }) => void
  applyConfig?: ApplyConfigHandler
}

declare global {
  var picframe: PicframeBridge | undefined
}

/** Ensure the bridge object exists with at least a no-op `send`. */
function ensureBridge(): PicframeBridge {
  if (!window.picframe) {
    window.picframe = {
      send: () => {
        /* no-op outside WebKitGTK (dev/preview) */
      }
    }
  }
  return window.picframe
}

/** Emit an input action to the worker (prev / next / toggle / hide). */
export function sendAction(action: InputAction): void {
  const bridge = ensureBridge()
  try {
    bridge.send({ action })
  } catch (e) {
    console.warn('picframe bridge send failed', e)
  }
}

/** Register the handler the worker calls to push the live shell config. */
export function registerApplyConfig(handler: ApplyConfigHandler): void {
  ensureBridge().applyConfig = handler
}
