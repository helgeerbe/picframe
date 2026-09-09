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

import type { CurrentMedia, InputAction, OverlayShellConfig } from './types'

type ApplyConfigHandler = (config: OverlayShellConfig) => void
type ApplyMediaHandler = (media: CurrentMedia) => void
/** Per-plugin data push (e.g. clock extra-text file source, #761). */
type ApplyPluginDataHandler = (pluginId: string, key: string, value: unknown) => void

/**
 * Payloads the shell posts to the native worker bridge
 * (`window.webkit.messageHandlers.picframe.postMessage`). Navigation /
 * danger-menu actions are bare `InputAction`s; the dock-driven
 * visible-plugin change (#765) carries the next list; the boot handshake is
 * `__request_config`.
 */
type BridgeSendPayload =
  InputAction | { action: InputAction } | { action: '__set_visible_plugins'; plugins: string[] }

interface PicframeBridge {
  send: (payload: BridgeSendPayload) => void
  applyConfig?: ApplyConfigHandler
  applyMedia?: ApplyMediaHandler
  applyPluginData?: ApplyPluginDataHandler
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

/**
 * Persist a dock-driven change to the expanded plugin set (#765).
 *
 * Sends `{ action: '__set_visible_plugins', plugins: [...] }` to the worker,
 * which emits a `VisiblePluginsChangedEvent` the renderer republishes as
 * `CommandEvent(SET_CONFIG, {overlay:{visible_plugins}})` — the same command
 * the Remote/Appearance REST endpoint publishes — so the dock and the web UI
 * share one persisted source of truth (`overlay.visible_plugins` in
 * `config.db3`). The dock updates optimistically; the next config push
 * reconciles it if the persist fails.
 */
export function setVisiblePlugins(pluginIds: string[]): void {
  const bridge = ensureBridge()
  try {
    bridge.send({ action: '__set_visible_plugins', plugins: pluginIds })
  } catch (e) {
    console.warn('picframe bridge setVisiblePlugins failed', e)
  }
}

/** Register the handler the worker calls to push the live shell config. */
export function registerApplyConfig(handler: ApplyConfigHandler): void {
  ensureBridge().applyConfig = handler
}

/**
 * Register the handler the worker calls to push the current media item (#757).
 *
 * The controller forwards `CurrentMediaChangedEvent` payloads over the IPC
 * bridge (the reliable path that replaces the cross-origin `/ws/state`
 * WebSocket from the `file://` overlay surface). The shell forwards the media
 * into visible plugin iframes and arms the `media_change` wake-after-blend
 * driver — the same body as the WS `onMedia` path, now shared via
 * `OverlayShell.applyMedia`.
 */
export function registerApplyMedia(handler: ApplyMediaHandler): void {
  ensureBridge().applyMedia = handler
}

/**
 * Register the handler the worker calls to push a per-plugin data update (#761).
 *
 * The clock plugin's ``extra_source: file`` mode shows the live contents of
 * ``/dev/shm/clock.txt``; the worker owns the host-fs read (plugins run in a
 * sandboxed WebKit iframe) and pushes the text here, and the shell forwards it
 * to the matching plugin iframe as a ``picframe:data`` postMessage. Generic so
 * other plugins can reuse the same channel.
 */
export function registerApplyPluginData(handler: ApplyPluginDataHandler): void {
  ensureBridge().applyPluginData = handler
}
