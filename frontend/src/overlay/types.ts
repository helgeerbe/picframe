/**
 * Shared types for the WebKitGTK overlay shell (#739, items 10–11).
 *
 * The shell runs in its own out-of-process WebKitGTK surface loaded via
 * `file://`. It receives a "shell config" from the worker through the
 * `window.picframe.applyConfig` JS bridge, reads connection info from
 * `location.search`, and connects to the picframe `/ws/state` WebSocket
 * itself for live media/state.
 */

/** Input actions the shell emits to the worker via the JS bridge. Navigation
 * actions (prev/next/toggle) come from the dock transport buttons and the
 * keyboard router; the danger-menu actions (display_off/restart_service/
 * reboot_host/shutdown_host) are confirmed in the shell before being sent
 * (#763). `__request_config` is the boot handshake. */
export type InputAction =
  | 'prev'
  | 'next'
  | 'toggle'
  | 'display_off'
  | 'restart_service'
  | 'reboot_host'
  | 'shutdown_host'
  | '__request_config'

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
  /** Activation modes (#757): `"icon"` = dock-activatable (every plugin);
   * `"media_change"` = auto-show on each media change (composable with
   * `"icon"`). Absent means `["icon"]` (legacy/default). */
  trigger?: string[]
  position: string
  /** Manifest design size `{ w, h }` in CSS px. A plugin with a `size` is in
   * *scale mode*: the shell sizes the panel to `design × scale` (so its aspect
   * matches the widget — no contain-fit gaps) and zooms the iframe with
   * `transform: scale(layout.scale)`. `null` (no manifest `size`) → *fill mode*:
   * the iframe fills the panel 100% × 100% and `width`/`height` size it. */
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
 * Effective per-plugin panel layout (#752). A plugin with a manifest `size`
 * is in *scale mode* (`scale` zooms the widget; `width`/`height` ignored); a
 * plugin without `size` is in *fill mode* (`width`/`height` size the panel).
 * `null`-able fields mean "inherit" (`idle_hide_seconds`) or "use default"
 * (`width`/`height`/`scale`); the worker merges defaults before sending, so the
 * shell receives concrete values, but the type keeps `null` for robustness.
 */
export interface PluginLayout {
  position: OverlayAnchor
  width: number | null
  height: number | null
  scale: number | null
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
  /** Image blend time in seconds (#757): the shell waits this long after a
   * media change before waking a `media_change`-triggered panel so the new
   * photo has finished crossfading. Sourced from `model.fade_time` /
   * `RendererConfig.time_fade`; defaults to 2.0 when absent. */
  time_fade?: number
  /** Per-edge content offset (px), shared by all plugins; forwarded to each
   * plugin's iframe via the `picframe:config` postMessage so the plugin can
   * pad its content from the matching panel edge. */
  content_offset?: ContentOffset
  /** Dock (plugin-icon row) placement (#758): position/margin/idle_hide_seconds.
   * The shell applies position+margin inline to `#pf-dock`. Absent = defaults
   * (bottom-center, 16px, inherit global idle). */
  dock_layout?: DockLayout
  plugin_config?: Record<string, Record<string, unknown>>
  _plugins?: PluginEntry[]
  _ws_port?: number
  _plugin_uri?: string
}

/** Per-edge content offset (px) inside each plugin panel, shared by all
 * plugins. Each anchor picks up the relevant edges (top-left -> top+left,
 * middle-right -> right, middle-center -> none). */
export interface ContentOffset {
  top: number
  bottom: number
  left: number
  right: number
}

/**
 * Dock (plugin-icon row) placement (#758). Unlike the per-plugin
 * `PluginLayout` there is a single dock, so this is a flat object. The shell
 * applies `position` + `margin` inline to the `#pf-dock` element (the
 * `pf-anchor-*` classes hardcode 12px, so the dock uses inline styles to keep
 * `margin` configurable). `idle_hide_seconds` `null` = inherit the global
 * `overlay.idle_hide_seconds` (matching the per-plugin layout semantics).
 */
export interface DockLayout {
  position: OverlayAnchor
  margin: number
  idle_hide_seconds: number | null
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
