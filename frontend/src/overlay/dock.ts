/**
 * Dock + visible-plugin rendering for the overlay shell (#739, item 10).
 *
 * The dock is a row of plugin icons; tapping an icon expands that plugin into
 * a panel (an iframe loading the plugin's `entry_uri`), tapping the active icon
 * again collapses it. The visible plugin and per-plugin config are sourced from
 * the shell config the worker pushes via `window.picframe.applyConfig`.
 */

import type { OverlayShellConfig, PluginEntry } from './types'

export interface DockCallbacks {
  /** Fired when the user changes which plugin is expanded (or collapses). */
  onVisiblePluginChange: (pluginId: string | null) => void
}

const PANEL_ID = 'pf-plugin-panel'
const DOCK_ID = 'pf-dock'

export class Dock {
  private plugins: PluginEntry[] = []
  private enabledPlugins: string[] = []
  private visiblePlugin: string | null = null
  private pluginConfig: Record<string, Record<string, unknown>> = {}
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
    const requested = config.visible_plugin ?? null
    this.visiblePlugin = this.isPluginEnabled(requested) ? requested : null
    this.render()
  }

  /** Expand/collapse a plugin by id (dock tap). */
  togglePlugin(pluginId: string): void {
    const next = this.visiblePlugin === pluginId ? null : pluginId
    this.visiblePlugin = next
    this.render()
    this.callbacks.onVisiblePluginChange(next)
  }

  /**
   * Forward a `postMessage` to the currently expanded plugin's iframe. Used to
   * push live media/state (e.g. `{ type: 'picframe:media', media }`) from the
   * shell's `/ws/state` client into the active plugin without the plugin having
   * to connect to the WebSocket itself.
   */
  postToActivePlugin(message: unknown): void {
    const panel = this.root.querySelector<HTMLElement>(`#${PANEL_ID}`)
    const frame = panel?.querySelector<HTMLIFrameElement>('iframe')
    if (!frame?.contentWindow) return
    try {
      frame.contentWindow.postMessage(message, '*')
    } catch {
      /* cross-origin frames may reject postMessage; ignore */
    }
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

    let panel = this.root.querySelector<HTMLElement>(`#${PANEL_ID}`)
    const current = this.visiblePlugin ? enabled.find(p => p.id === this.visiblePlugin) : undefined
    if (!current) {
      panel?.remove()
      return
    }
    if (!panel) {
      panel = document.createElement('div')
      panel.id = PANEL_ID
      panel.className = 'pf-plugin-panel'
      this.root.appendChild(panel)
    }
    panel.replaceChildren(this.buildFrame(current))
  }

  private buildIcon(plugin: PluginEntry): HTMLElement {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'pf-dock-icon'
    if (plugin.id === this.visiblePlugin) btn.classList.add('pf-dock-icon--active')
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

  private buildFrame(plugin: PluginEntry): HTMLIFrameElement {
    const frame = document.createElement('iframe')
    frame.title = plugin.name || plugin.id
    frame.src = plugin.entry_uri
    frame.className = 'pf-plugin-frame'
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin')
    // Forward the effective per-plugin config into the iframe via postMessage
    // once it loads; plugins opt in by listening for { type: 'picframe:config' }.
    const cfg = this.pluginConfig[plugin.id] ?? {}
    frame.addEventListener('load', () => {
      try {
        frame.contentWindow?.postMessage(
          { type: 'picframe:config', pluginId: plugin.id, config: cfg },
          '*'
        )
      } catch {
        /* cross-origin frames may reject postMessage; ignore */
      }
    })
    return frame
  }
}
