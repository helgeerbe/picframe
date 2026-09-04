/**
 * Parse the worker-injected connection info from `location.search`.
 *
 * The overlay is loaded by the worker via a `file://` URI with query params
 * `?ws=<port>&plugins=<encoded file:// URI of plugin_dir>` appended by
 * `OverlayWorker._shell_uri`. Because the page origin is `file://`, the shell
 * cannot derive the picframe HTTP/WS port from `window.location`, so the
 * worker hands it in explicitly.
 */
export interface OverlayEnv {
  /** picframe state WebSocket port (FastAPI port), or null if absent. */
  wsPort: number | null
  /** `file://` URI of the plugin directory, or null if absent. */
  pluginUri: string | null
}

export function readEnv(): OverlayEnv {
  const params = new URLSearchParams(window.location.search)
  const ws = params.get('ws')
  const plugins = params.get('plugins')
  let wsPort: number | null = null
  if (ws !== null) {
    const parsed = Number(ws)
    wsPort = Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }
  return { wsPort, pluginUri: plugins }
}
