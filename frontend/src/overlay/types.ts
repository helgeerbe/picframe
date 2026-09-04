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
  /** Emoji fallback used when no `icon_svg` is provided. */
  icon: string
  /** Inline SVG markup (single-color, `stroke="currentColor"`) from the plugin's
   * `icon.svg`. When present the dock inlines it so the icon inherits the dock
   * text color and renders without an emoji font. */
  icon_svg?: string
  position: string
  /** Manifest design size `{ w, h }` in CSS px. The shell uses this as the
   * scale basis: it lays the iframe out at this fixed size and applies
   * `transform: scale(min(panelW/w, panelH/h))` so the whole widget scales
   * uniformly to fit the panel (contain fit), like an embedded web widget.
   * `null` (plugin without a manifest `size`) → scale 1 (iframe fills panel). */
  size?: { w: number; h: number } | null
  /** Manifest default duration policy; superseded by `layout.display_mode`. */
  default_display_mode?: DisplayMode
  /** Effective per-plugin layout (#752): manifest defaults merged with the
   * persisted `overlay.plugin_layout.<id>.*` overrides, computed server-side
   * so the shell applies a ready-to-use layout. */
  layout?: PluginLayout
  /** `file://` URI of the plugin's HTML entry (loaded in an iframe). */
  entry_uri: string
}

/** Nine-anchor screen position used for panel placement and content alignment. */
export type OverlayAnchor =
  | 'top-left'
  | 'top-center'
  | 'top-right'
  | 'middle-left'
  | 'middle-center'
  | 'middle-right'
  | 'bottom-left'
  | 'bottom-center'
  | 'bottom-right'

/**
 * Effective per-plugin panel layout (#752). `null`-able fields mean
 * "inherit" (`content_align`/`idle_hide_seconds`) or "use plugin default"
 * (`width`/`height`); the worker merges defaults before sending, so the shell
 * receives concrete values, but the type keeps `null` for robustness.
 */
export interface PluginLayout {
  position: OverlayAnchor
  width: number | null
  height: number | null
  content_align: OverlayAnchor | null
  display_mode: DisplayMode
  idle_hide_seconds: number | null
  z_order: number
}

/**
 * The full config pushed to the shell by the worker. The overlay config keys
 * mirror `default_config.yaml`; the `_`-prefixed keys are worker-injected
 * metadata (plugin list + connection info).
 *
 * Issue #752 replaces the single `visible_plugin` with a `visible_plugins`
 * list (simultaneous widgets) plus a per-plugin `layout` on each
 * `PluginEntry`. The legacy `visible_plugin`/`display_mode` keys are kept as
 * fallbacks for pre-#752 config (the worker normalizer bridges the two).
 */
export interface OverlayShellConfig {
  enabled?: boolean
  enabled_plugins?: string[]
  /** Which plugins are expanded on screen (#752, multi-widget). */
  visible_plugins?: string[]
  /** Legacy single visible plugin (pre-#752); used only when `visible_plugins`
   * is absent. */
  visible_plugin?: string | null
  /** Legacy global duration policy (pre-#752); per-plugin `display_mode` in
   * `PluginEntry.layout` supersedes it. Kept as a fallback. */
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
