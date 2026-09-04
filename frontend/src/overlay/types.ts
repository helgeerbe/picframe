/**
 * Shared types for the WebKitGTK overlay shell (#739, items 10–11).
 *
 * The shell runs in its own out-of-process WebKitGTK surface loaded via
 * `file://`. It receives a "shell config" from the worker through the
 * `window.picframe.applyConfig` JS bridge, reads connection info from
 * `location.search`, and connects to the picframe `/ws/state` WebSocket
 * itself for live media/state.
 */

/** Input actions the shell emits to the worker via the JS bridge. */
export type InputAction = 'prev' | 'next' | 'toggle' | 'hide' | '__request_config'

/** Overlay display duration policy. */
export type DisplayMode = 'persistent' | 'auto_hide'

/** Active input device classes (any subset). */
export type InputType = 'touch' | 'mouse' | 'keyboard'

/**
 * A discovered overlay plugin, slimmed to what the shell needs to render the
 * dock and load the plugin entry. The worker builds this from
 * `PluginDescriptor` (it knows the plugin_dir on disk).
 */
export interface PluginEntry {
  id: string
  name: string
  icon: string
  position: string
  /** `file://` URI of the plugin's HTML entry (loaded in an iframe). */
  entry_uri: string
}

/**
 * The full config pushed to the shell by the worker. The overlay config keys
 * mirror `default_config.yaml`; the `_`-prefixed keys are worker-injected
 * metadata (plugin list + connection info).
 */
export interface OverlayShellConfig {
  enabled?: boolean
  enabled_plugins?: string[]
  visible_plugin?: string | null
  display_mode?: DisplayMode
  enabled_input_types?: InputType[]
  idle_hide_seconds?: number
  transparent?: boolean
  plugin_config?: Record<string, Record<string, unknown>>
  _plugins?: PluginEntry[]
  _ws_port?: number
  _plugin_uri?: string
}

/** Minimal slice of the current media item the shell forwards to plugins. */
export interface CurrentMedia {
  file_path: string
  media_type?: string
  /** GPS coordinates when the media has them (forwarded to the meta plugin). */
  location?: { lat: number; lon: number } | null
  // EXIF is an open-ended metadata blob; plugins access arbitrary keys.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  exif?: Record<string, any>
}

/** A decoded `/ws/state` message. */
export type StateMessage =
  | { type: 'MediaChangedEvent'; media: CurrentMedia }
  | { type: 'StateEvent'; state: string; payload?: unknown }
  | { type: 'SystemErrorEvent'; message: string; component: string }
