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

import {
  registerApplyConfig,
  registerApplyMedia,
  registerApplyPluginData,
  sendAction
} from './bridge'
import { Dock } from './dock'
import { readEnv } from './env'
import { InputRouter } from './input'
import { StateClient } from './state-client'
import type {
  CurrentMedia,
  DisplayMode,
  InputAction,
  InputType,
  OverlayShellConfig,
  PluginEntry
} from './types'

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
  /** Dock idle-hide override (#758): `null` = inherit `globalIdleHideSeconds`.
   * Sourced from `dock_layout.idle_hide_seconds`. */
  private dockIdleHideSeconds: number | null = null
  /** Snapshot of the latest plugin list (for per-panel idle lookups). */
  private plugins: PluginEntry[] = []
  /** Image blend time (s) — the shell waits this long after a media change
   * before waking a `media_change` panel (#757). Sourced from
   * `RendererConfig.time_fade` via the worker config. */
  private timeFade = 2
  /** Latest media received from `/ws/state`; forwarded to plugin iframes on
   * load (#757) so a freshly auto-shown panel renders the current photo. */
  private latestMedia: CurrentMedia | null = null
  /** Per-plugin data cache (#761): the worker pushes e.g. the clock extra-text
   * file contents here; forwarded to plugin iframes on load so a freshly-opened
   * panel shows the latest value instead of waiting for the next poll. */
  private pluginData: Record<string, Record<string, unknown>> = {}
  /** Pending `media_change` wake-after-blend timer (#757). */
  private mediaWakeTimer: number | null = null
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

    this.dock = new Dock(this.content, this.root, {
      onVisiblePluginsChange: () => this.wake(),
      onAction: (action: InputAction) => {
        if (action !== '__request_config') sendAction(action)
      }
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
    // keyboard activity never reveal the cursor (#739). The listener is on
    // #overlay-root (not the veil) so mouse moves over the hoisted dock (#763)
    // also wake the shell — the dock sits above the veil and would otherwise
    // swallow pointermove without resetting the idle timer.
    this.root.addEventListener('pointermove', this.onMouseMove)
    registerApplyConfig(config => this.applyConfig(config))
    // The worker pushes current-media payloads over the IPC bridge (the reliable
    // path that replaces the cross-origin `/ws/state` WebSocket from `file://`).
    registerApplyMedia(media => this.applyMedia(media))
    // The worker pushes per-plugin data (e.g. the clock extra-text file
    // contents) over the same IPC bridge (#761); forwarded to the matching
    // plugin iframe and cached for freshly-loaded panels.
    registerApplyPluginData((pluginId, key, value) => this.applyPluginData(pluginId, key, value))

    const env = readEnv()
    if (env.wsPort) {
      this.state = new StateClient(env.wsPort, {
        // Best-effort fallback: when the cross-origin WS *does* connect it is a
        // harmless secondary media path. Both the bridge and the WS feed the
        // shared `applyMedia` so plugins see identical payloads (#757).
        onMedia: media => this.applyMedia(media)
      })
      this.state.connect()
    }

    // Ask the worker for the initial config (no-op outside WebKitGTK).
    sendAction('__request_config')
  }

  destroy(): void {
    this.root.removeEventListener('pointermove', this.onMouseMove)
    this.dock.destroy()
    this.router.detach()
    this.state?.stop()
    this.clearPanelIdle()
    this.clearDockIdle()
    this.clearMediaWake()
  }

  private applyConfig(config: OverlayShellConfig): void {
    this.globalIdleHideSeconds = config.idle_hide_seconds ?? DEFAULT_IDLE_HIDE_SECONDS
    this.dockIdleHideSeconds = config.dock_layout?.idle_hide_seconds ?? null
    this.timeFade = config.time_fade ?? 2
    this.plugins = config._plugins ?? []
    const enabledTypes = (config.enabled_input_types ?? [
      'touch',
      'mouse',
      'keyboard'
    ]) as InputType[]
    this.enabledTypes = enabledTypes
    this.router.setEnabledTypes(enabledTypes)
    // Let newly-loaded plugin iframes receive the current photo (#757).
    this.dock.setMediaProvider(() => this.latestMedia)
    // And the latest per-plugin data (clock extra-text file, #761).
    this.dock.setPluginDataProvider(() => this.pluginData)
    this.dock.applyConfig(config)
    this.wake()
  }

  /**
   * Apply a current-media payload from the IPC bridge or the `/ws/state` client
   * (#757). Both paths feed this shared method so plugins see identical
   * payloads regardless of which transport delivered them. The media is
   * forwarded into all visible plugin iframes (so e.g. `meta`/`text` react to
   * photo changes without their own WS client), cached for freshly-loaded
   * iframes, and used to arm the `media_change` wake-after-blend driver.
   */
  private applyMedia(media: CurrentMedia): void {
    const previousPath = this.latestMedia?.file_path
    this.latestMedia = media
    this.dock.postToVisiblePlugins({ type: 'picframe:media', media })
    // Only re-trigger the wake-after-blend cycle when the photo actually
    // changes. Periodic state updates (WS reconnects, duplicate IPC pushes)
    // with the same file_path would otherwise hide the panel repeatedly via
    // `scheduleMediaWake` → `showPluginIdle`, preventing it from ever becoming
    // visible (#757).
    if (previousPath === media?.file_path) return
    this.scheduleMediaWake()
  }

  /**
   * Apply a per-plugin data push from the worker IPC bridge (#761). The worker
   * owns host-fs reads plugins cannot do from their sandboxed WebKit iframe
   * (e.g. the clock's `/dev/shm/clock.txt` extra-text source) and pushes the
   * value here; the shell forwards it to the matching plugin iframe as a
   * `picframe:data` postMessage and caches it for freshly-loaded panels.
   */
  private applyPluginData(pluginId: string, key: string, value: unknown): void {
    if (!this.pluginData[pluginId]) this.pluginData[pluginId] = {}
    this.pluginData[pluginId][key] = value
    this.dock.postToPlugin(pluginId, { type: 'picframe:data', key, value })
  }

  /**
   * Reset the dock + per-panel idle timers and reveal everything. Each visible
   * plugin panel fades only in its own `auto_hide` mode; `persistent` panels
   * never get an idle timer. The dock timer always runs (the dock is chrome
   * and always auto-hides), using the global `idle_hide_seconds` or the dock
   * fallback when it is 0.
   *
   * @param revealDock When `false`, only the plugin panels are revealed and
   *   re-armed; the dock is left untouched. Used by `scheduleMediaWake` so a
   *   `media_change` trigger surfaces the text panel without also fading in the
   *   dock (#757).
   */
  private wake(revealDock = true): void {
    if (revealDock) {
      this.root.classList.remove('pf-root--dock-idle')
      this.clearDockIdle()
    }
    this.clearPanelIdle()

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

    if (revealDock) {
      // Dock: always auto-hides. The dock layout may override the idle delay
      // (#758); otherwise reuse `idle_hide_seconds`, or the fallback when it
      // is 0. The cursor hides together with the dock so the two stay in sync:
      // removing `pf-root--cursor` reverts the root to the inherited
      // `cursor: none` (#739).
      const dockSeconds = this.dockIdleSeconds()
      this.dockIdleTimer = window.setTimeout(
        () => {
          this.root.classList.add('pf-root--dock-idle')
          this.root.classList.remove('pf-root--cursor')
        },
        Math.max(0, dockSeconds) * 1000
      )
    }
  }

  /** Effective dock idle-hide seconds (#758): the dock layout override when set
   * and positive, else the global value (or the fallback when the global is 0,
   * matching the pre-#758 behavior). */
  private dockIdleSeconds(): number {
    const override = this.dockIdleHideSeconds
    if (override != null && override > 0) return override
    return this.globalIdleHideSeconds > 0 ? this.globalIdleHideSeconds : DOCK_IDLE_FALLBACK_SECONDS
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

  /**
   * `media_change` wake-after-blend driver (#757). For every enabled plugin
   * whose triggers include `"media_change"`, mount its panel hidden (so its
   * iframe can load + receive the live media) and arm a single timer that
   * wakes the shell after the image blend (`time_fade`) finishes — the same
   * wake path as a dock tap, so the panel then fades in and vanishes via the
   * existing #752 `auto_hide` + `idle_hide_seconds`. No-op when no plugin opts
   * into `media_change` (clock/weather are dock-only and unaffected).
   */
  private scheduleMediaWake(): void {
    this.clearMediaWake()
    const targets = this.plugins.filter(
      p => (p.trigger ?? ['icon']).includes('media_change') && this.dock.isPluginEnabled(p.id)
    )
    if (targets.length === 0) return
    for (const p of targets) this.dock.showPluginIdle(p.id)
    const delay = Math.max(0, this.timeFade) * 1000
    this.mediaWakeTimer = window.setTimeout(() => {
      this.mediaWakeTimer = null
      // Reveal only the media_change panels, not the dock. The dock is
      // navigation chrome and should not appear on a photo change — only on
      // user interaction (#757).
      this.wake(false)
    }, delay)
  }

  private clearMediaWake(): void {
    if (this.mediaWakeTimer !== null) {
      window.clearTimeout(this.mediaWakeTimer)
      this.mediaWakeTimer = null
    }
  }
}
