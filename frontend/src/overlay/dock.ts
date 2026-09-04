/**
 * Dock + visible-plugin rendering for the overlay shell (#739, item 10; #752
 * multi-widget).
 *
 * The dock is a row of plugin icons; tapping an icon toggles that plugin's
 * panel (an iframe loading the plugin's `entry_uri`) on screen — several
 * panels can be visible at once (#752). The visible plugins and per-plugin
 * config are sourced from the shell config the worker pushes via
 * `window.picframe.applyConfig`; each plugin carries an effective `layout`
 * (position/size/z-order) the shell applies per panel.
 */

import type {
  ContentOffset,
  OverlayAnchor,
  OverlayShellConfig,
  PluginEntry,
  PluginLayout
} from './types'

export interface DockCallbacks {
  /** Fired when the user changes which plugins are expanded (or collapses all). */
  onVisiblePluginsChange: (pluginIds: string[]) => void
}

const DOCK_ID = 'pf-dock'
/** Prefix for per-plugin panel element ids: `pf-plugin-panel-<id>`. */
const PANEL_ID_PREFIX = 'pf-plugin-panel-'

/** Default panel size when a layout omits width/height (matches the legacy
 * `#pf-plugin-panel` rule: min(38vw,480px) × min(46vh,360px)). */
const DEFAULT_PANEL_WIDTH = 'min(38vw, 480px)'
const DEFAULT_PANEL_HEIGHT = 'min(46vh, 360px)'

export class Dock {
  private plugins: PluginEntry[] = []
  private enabledPlugins: string[] = []
  private visiblePlugins: string[] = []
  private pluginConfig: Record<string, Record<string, unknown>> = {}
  /** Per-edge content offset (px), shared by all plugins; forwarded to each
   * plugin iframe so it can pad its content from the matching panel edge. */
  private contentOffset: ContentOffset = { top: 0, bottom: 0, left: 0, right: 0 }
  private readonly root: HTMLElement
  private readonly callbacks: DockCallbacks

  constructor(root: HTMLElement, callbacks: DockCallbacks) {
    this.root = root
    this.callbacks = callbacks
  }

  /** Apply a full shell config (plugins + enabled/visible set + per-plugin config). */
  applyConfig(config: OverlayShellConfig): void {
    this.plugins = config._plugins ?? []
    this.enabledPlugins = config.enabled_plugins ?? []
    this.pluginConfig = config.plugin_config ?? {}
    this.contentOffset = config.content_offset ?? { top: 0, bottom: 0, left: 0, right: 0 }
    this.visiblePlugins = this.resolveVisiblePlugins(config)
    this.render()
  }

  /** Toggle a plugin in/out of the visible set (dock tap). */
  togglePlugin(pluginId: string): void {
    const next = this.visiblePlugins.includes(pluginId)
      ? this.visiblePlugins.filter(id => id !== pluginId)
      : [...this.visiblePlugins, pluginId]
    this.visiblePlugins = next
    this.render()
    this.callbacks.onVisiblePluginsChange(next)
  }

  /**
   * Forward a `postMessage` to every currently expanded plugin's iframe. Used
   * to push live media/state (e.g. `{ type: 'picframe:media', media }`) from
   * the shell's `/ws/state` client into all visible plugins without each
   * plugin having to connect to the WebSocket itself.
   */
  postToVisiblePlugins(message: unknown): void {
    for (const id of this.visiblePlugins) {
      const panel = this.root.querySelector<HTMLElement>(`#${CSS.escape(PANEL_ID_PREFIX + id)}`)
      const frame = panel?.querySelector<HTMLIFrameElement>('iframe')
      if (!frame?.contentWindow) continue
      try {
        frame.contentWindow.postMessage(message, '*')
      } catch {
        /* cross-origin frames may reject postMessage; ignore */
      }
    }
  }

  private resolveVisiblePlugins(config: OverlayShellConfig): string[] {
    const requested = config.visible_plugins
    if (Array.isArray(requested)) {
      return requested.filter(id => this.isPluginEnabled(id))
    }
    // Legacy single-visible-plugin model (pre-#752 config): the worker
    // normalizer re-derived `visible_plugin` from `visible_plugins[0]`.
    const legacy = config.visible_plugin ?? null
    return legacy && this.isPluginEnabled(legacy) ? [legacy] : []
  }

  private isPluginEnabled(id: string | null | undefined): id is string {
    return !!id && this.enabledPlugins.includes(id)
  }

  private render(): void {
    const enabled = this.plugins.filter(p => this.enabledPlugins.includes(p.id))
    let dock = this.root.querySelector<HTMLElement>(`#${DOCK_ID}`)
    if (!dock) {
      dock = document.createElement('div')
      dock.id = DOCK_ID
      dock.className = 'pf-dock'
      this.root.appendChild(dock)
    }
    dock.replaceChildren(...enabled.map(p => this.buildIcon(p)))

    // Render one panel per visible plugin, ordered by layout z_order (stable
    // for equal z so manifest/dock order wins), each positioned by its anchor.
    const visible = enabled
      .filter(p => this.visiblePlugins.includes(p.id))
      .sort((a, b) => this.layoutOf(a).z_order - this.layoutOf(b).z_order)
    const seen = new Set<string>()
    for (const plugin of visible) {
      seen.add(plugin.id)
      this.renderPanel(plugin)
    }
    // Remove panels for plugins no longer visible.
    this.root
      .querySelectorAll<HTMLElement>(`[id^="${CSS.escape(PANEL_ID_PREFIX)}"]`)
      .forEach(panel => {
        const id = panel.id.slice(PANEL_ID_PREFIX.length)
        if (!seen.has(id)) panel.remove()
      })
  }

  private renderPanel(plugin: PluginEntry): void {
    const layout = this.layoutOf(plugin)
    const panelId = PANEL_ID_PREFIX + plugin.id
    let panel = this.root.querySelector<HTMLElement>(`#${CSS.escape(panelId)}`)
    if (!panel) {
      panel = document.createElement('div')
      panel.id = panelId
      panel.className = 'pf-plugin-panel'
      this.root.appendChild(panel)
    }
    this.applyPanelLayout(panel, plugin, layout)
    panel.replaceChildren(this.buildFrame(plugin, layout))
  }

  /** Apply the effective layout to a panel element (anchor class + size/z).
   *
   * Scale mode (plugin has a manifest `size`): the panel is sized to
   * `design × scale` so its aspect matches the widget exactly — no contain-fit
   * background gaps. The iframe is then laid out at the design size and zoomed
   * with `transform: scale(scale)` (see `buildFrame`).
   *
   * Fill mode (no `size`): `width`/`height` size the panel (or the CSS default);
   * the iframe fills it 100% × 100%. */
  private applyPanelLayout(panel: HTMLElement, plugin: PluginEntry, layout: PluginLayout): void {
    panel.className = `pf-plugin-panel pf-anchor-${layout.position}`
    panel.style.zIndex = String(layout.z_order)
    const design = plugin.size
    if (design) {
      // Scale mode (#752): the shell panel is transparent so the photo shows
      // through everywhere except behind the plugin content. Each plugin
      // paints its own readability background on its content container, which
      // scales with `transform: scale()` exactly like the rest of the widget.
      panel.classList.add('pf-plugin-panel--scale')
      const scale = layout.scale ?? 1
      panel.style.width = `${Math.round(design.w * scale)}px`
      panel.style.height = `${Math.round(design.h * scale)}px`
    } else {
      panel.style.width = layout.width != null ? `${layout.width}px` : DEFAULT_PANEL_WIDTH
      panel.style.height = layout.height != null ? `${layout.height}px` : DEFAULT_PANEL_HEIGHT
    }
  }

  private layoutOf(plugin: PluginEntry): PluginLayout {
    return (
      plugin.layout ?? {
        position: (plugin.position as OverlayAnchor) ?? 'top-right',
        width: null,
        height: null,
        scale: null,
        display_mode: plugin.default_display_mode ?? 'auto_hide',
        idle_hide_seconds: null,
        z_order: 0
      }
    )
  }

  private buildIcon(plugin: PluginEntry): HTMLElement {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'pf-dock-icon'
    if (this.visiblePlugins.includes(plugin.id)) btn.classList.add('pf-dock-icon--active')
    btn.setAttribute('aria-label', plugin.name || plugin.id)
    // Prefer the plugin's inline SVG (crisp, theme-aware via currentColor,
    // font-independent). Fall back to the emoji `icon` field when no SVG is
    // shipped. Only inline markup that looks like an <svg> root so a stray
    // string can never inject arbitrary HTML into the dock button.
    const svg = plugin.icon_svg?.trimStart()
    if (svg && svg.startsWith('<svg')) {
      btn.innerHTML = svg
    } else {
      btn.textContent = plugin.icon || '◆'
    }
    btn.addEventListener('click', e => {
      e.stopPropagation()
      this.togglePlugin(plugin.id)
    })
    return btn
  }

  private buildFrame(plugin: PluginEntry, layout: PluginLayout): HTMLIFrameElement {
    const frame = document.createElement('iframe')
    frame.title = plugin.name || plugin.id
    frame.src = plugin.entry_uri
    frame.className = 'pf-plugin-frame'
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin')
    // Forward the effective per-plugin config into the iframe via postMessage
    // once it loads; plugins opt in by listening for { type: 'picframe:config' }.
    const cfg = { ...(this.pluginConfig[plugin.id] ?? {}) }
    frame.addEventListener('load', () => {
      try {
        frame.contentWindow?.postMessage(
          // #752: pass the panel anchor so the plugin can align its content to
          // the same corner (the iframe is a separate document; shell CSS can't
          // reach inside it). Plugins without a handler keep centering. The
          // per-edge content_offset lets the plugin pad its content from the
          // matching panel edge; defaults to 0 (flush) when absent.
          {
            type: 'picframe:config',
            pluginId: plugin.id,
            config: cfg,
            anchor: layout.position,
            content_offset: this.contentOffset
          },
          '*'
        )
      } catch {
        /* cross-origin frames may reject postMessage; ignore */
      }
    })
    // Scale mode (#752): a plugin with a manifest `size` is laid out once at
    // that fixed design size (px), then the whole iframe is zoomed with
    // `transform: scale(layout.scale)` (a user-controlled factor). The panel is
    // sized to `design × scale` (see `applyPanelLayout`), so the iframe — at the
    // design size, scaled by `scale`, anchored top-left — fills the panel
    // exactly with no contain-fit aspect mismatch or background gaps. This
    // replaces container queries, which WebKitGTK does not resolve reliably
    // inside the overlay iframe (cqw → 0). A plugin without a manifest `size`
    // (fill mode) keeps the legacy fill (100% × 100%, no transform).
    const design = plugin.size
    if (design) {
      const scale = layout.scale ?? 1
      frame.style.position = 'absolute'
      frame.style.left = '0px'
      frame.style.top = '0px'
      frame.style.width = `${design.w}px`
      frame.style.height = `${design.h}px`
      frame.style.transform = `scale(${scale})`
      frame.style.transformOrigin = 'top left'
    }
    return frame
  }
}
