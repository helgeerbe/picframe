/**
 * Overlay shell orchestrator (#739, items 10–11; #752 multi-widget).
 *
 * Builds the transparent overlay DOM (visible-plugin panels below a
 * pointer/keyboard "veil" with the dock above it), wires the input router,
 * dock, idle-hide content fading, the `/ws/state` client, and the worker JS
 * bridge. The worker pushes the live config via `window.picframe.applyConfig`;
 * the shell boots by asking for it via `__request_config`.
 *
 * Visibility model (#752): the dock and each plugin panel fade on
 * independent timers. The dock is navigation chrome — it always auto-hides
 * after the idle interval (defaulting to {@link DOCK_IDLE_FALLBACK_SECONDS}
 * when `idle_hide_seconds` is 0), so a `persistent`-mode panel still shows
 * but the icon bar does not linger. Each visible plugin panel follows its
 * own effective `layout.display_mode` (`persistent` = always visible;
 * `auto_hide` = fades after its `layout.idle_hide_seconds`, or the global
 * `idle_hide_seconds` when the per-plugin value is `null`). All timers reset
 * on any enabled input event.
 */

import { registerApplyConfig, sendAction } from './bridge'
import { Dock } from './dock'
import { readEnv } from './env'
import { InputRouter } from './input'
import { StateClient } from './state-client'
import type { DisplayMode, InputAction, InputType, OverlayShellConfig, PluginEntry } from './types'

const DEFAULT_IDLE_HIDE_SECONDS = 5
/** Dock fallback when `idle_hide_seconds` is 0 (content stays, dock still hides). */
const DOCK_IDLE_FALLBACK_SECONDS = 5
const PANEL_ID_PREFIX = 'pf-plugin-panel-'

export class OverlayShell {
  private readonly root: HTMLElement
  private content: HTMLElement
  private veil: HTMLElement
  private dock: Dock
  private router: InputRouter
  private state: StateClient | null = null
  private dockIdleTimer: number | null = null
  /** Per-plugin idle timers keyed by plugin id (#752). */
  private panelIdleTimers = new Map<string, number>()
  private globalIdleHideSeconds = DEFAULT_IDLE_HIDE_SECONDS
  /** Snapshot of the latest plugin list (for per-panel idle lookups). */
  private plugins: PluginEntry[] = []
  /** Currently enabled input classes; the mouse-move cursor reveal only fires
   * when `mouse` is among them (#739). */
  private enabledTypes: InputType[] = ['touch', 'mouse', 'keyboard']

  constructor(root: HTMLElement) {
    this.root = root
    this.root.classList.add('pf-root')

    // Visible-plugin panels container (below the veil; non-interactive).
    this.content = document.createElement('div')
    this.content.id = 'pf-content'
    this.root.appendChild(this.content)

    // Transparent full-screen veil that captures navigation input.
    this.veil = document.createElement('div')
    this.veil.id = 'pf-veil'
    this.root.appendChild(this.veil)

    this.dock = new Dock(this.content, {
      onVisiblePluginsChange: () => this.wake()
    })

    this.router = new InputRouter({
      root: this.veil,
      enabledTypes: ['touch', 'mouse', 'keyboard'],
      onAction: (action: InputAction) => {
        if (action !== '__request_config') sendAction(action)
      },
      onActivity: () => this.wake()
    })
  }

  boot(): void {
    this.router.attach()
    // Reveal the cursor on mouse movement and reset the idle timers in lockstep
    // with the dock, so the cursor shows only while the mouse is active and
    // hides again after the idle interval — mirroring dock auto-hide. Touch and
    // keyboard activity never reveal the cursor (#739).
    this.veil.addEventListener('pointermove', this.onMouseMove)
    registerApplyConfig(config => this.applyConfig(config))

    const env = readEnv()
    if (env.wsPort) {
      this.state = new StateClient(env.wsPort, {
        // Forward live media changes into all visible plugin iframes so plugins
        // (e.g. `meta`) can react to photo changes without their own WS client.
        onMedia: media => this.dock.postToVisiblePlugins({ type: 'picframe:media', media })
      })
      this.state.connect()
    }

    // Ask the worker for the initial config (no-op outside WebKitGTK).
    sendAction('__request_config')
  }

  destroy(): void {
    this.veil.removeEventListener('pointermove', this.onMouseMove)
    this.router.detach()
    this.state?.stop()
    this.clearPanelIdle()
    this.clearDockIdle()
  }

  private applyConfig(config: OverlayShellConfig): void {
    this.globalIdleHideSeconds = config.idle_hide_seconds ?? DEFAULT_IDLE_HIDE_SECONDS
    this.plugins = config._plugins ?? []
    const enabledTypes = (config.enabled_input_types ?? [
      'touch',
      'mouse',
      'keyboard'
    ]) as InputType[]
    this.enabledTypes = enabledTypes
    this.router.setEnabledTypes(enabledTypes)
    this.dock.applyConfig(config)
    this.wake()
  }

  /**
   * Reset the dock + per-panel idle timers and reveal everything. Each visible
   * plugin panel fades only in its own `auto_hide` mode; `persistent` panels
   * never get an idle timer. The dock timer always runs (the dock is chrome
   * and always auto-hides), using the global `idle_hide_seconds` or the dock
   * fallback when it is 0.
   */
  private wake(): void {
    this.root.classList.remove('pf-root--dock-idle')
    this.clearPanelIdle()
    this.clearDockIdle()

    // Per-panel idle: clear each panel's --idle class and arm its own timer.
    for (const id of this.dockVisiblePluginIds()) {
      const panel = this.content.querySelector<HTMLElement>(`#${CSS.escape(PANEL_ID_PREFIX + id)}`)
      panel?.classList.remove('pf-plugin-panel--idle')
      const seconds = this.panelIdleSeconds(id)
      if (seconds !== null && seconds > 0) {
        const timer = window.setTimeout(
          () => {
            panel?.classList.add('pf-plugin-panel--idle')
          },
          Math.max(0, seconds) * 1000
        )
        this.panelIdleTimers.set(id, timer)
      }
      // persistent panels (seconds === null) never fade.
    }

    // Dock: always auto-hides. Reuse idle_hide_seconds, or the fallback when 0.
    // The cursor hides together with the dock so the two stay in sync: removing
    // `pf-root--cursor` reverts the root to the inherited `cursor: none` (#739).
    const dockSeconds =
      this.globalIdleHideSeconds > 0 ? this.globalIdleHideSeconds : DOCK_IDLE_FALLBACK_SECONDS
    this.dockIdleTimer = window.setTimeout(
      () => {
        this.root.classList.add('pf-root--dock-idle')
        this.root.classList.remove('pf-root--cursor')
      },
      Math.max(0, dockSeconds) * 1000
    )
  }

  /** Return the effective idle-hide seconds for a panel, or `null` for
   * `persistent` (never fade). Falls back to the global value when the
   * per-plugin layout omits it (#752). */
  private panelIdleSeconds(pluginId: string): number | null {
    const plugin = this.plugins.find(p => p.id === pluginId)
    const displayMode: DisplayMode =
      plugin?.layout?.display_mode ?? plugin?.default_display_mode ?? 'auto_hide'
    if (displayMode === 'persistent') return null
    const perPlugin = plugin?.layout?.idle_hide_seconds
    if (perPlugin != null && perPlugin > 0) return perPlugin
    return this.globalIdleHideSeconds
  }

  /** The currently visible plugin ids (read from the rendered panels so the
   * shell's idle timers track exactly what is on screen). */
  private dockVisiblePluginIds(): string[] {
    const ids: string[] = []
    this.content
      .querySelectorAll<HTMLElement>(`[id^="${CSS.escape(PANEL_ID_PREFIX)}"]`)
      .forEach(panel => {
        ids.push(panel.id.slice(PANEL_ID_PREFIX.length))
      })
    return ids
  }

  /**
   * Bound pointer-move handler: reveal the cursor and reset the idle timers.
   * Only fires for real mouse input (not touch/pen) and only when `mouse` is an
   * enabled input class, so touch-only users never see a cursor (#739). Bound as
   * an arrow-function property so `removeEventListener` in {@link destroy} can
   * detach the exact same reference.
   */
  private readonly onMouseMove = (e: PointerEvent): void => {
    if (e.pointerType !== 'mouse' || !this.enabledTypes.includes('mouse')) return
    this.root.classList.add('pf-root--cursor')
    this.wake()
  }

  private clearPanelIdle(): void {
    for (const timer of this.panelIdleTimers.values()) {
      window.clearTimeout(timer)
    }
    this.panelIdleTimers.clear()
  }

  private clearDockIdle(): void {
    if (this.dockIdleTimer !== null) {
      window.clearTimeout(this.dockIdleTimer)
      this.dockIdleTimer = null
    }
  }
}
