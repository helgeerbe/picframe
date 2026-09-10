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
  CurrentMedia,
  DockLayout,
  InputAction,
  OverlayAnchor,
  OverlayShellConfig,
  PluginEntry,
  PluginLayout
} from './types'

export interface DockCallbacks {
  /** Fired when the user changes which plugins are expanded (or collapses all). */
  onVisiblePluginsChange: (pluginIds: string[]) => void
  /** Fired when the on-screen (runtime) visibility of expanded plugins changes
   * (#766) — an auto-hide fade, wake, media_change re-arm, or toggle that
   * mutated which expanded panels are actually shown (not `--idle`). Distinct
   * from `onVisiblePluginsChange` (the persisted config set): this carries the
   * transient on-screen set the dock already tracks via the `--active` icon
   * state, now mirrored to the Remote tab so its tile highlights stay in sync. */
  onOnScreenPluginsChange: (pluginIds: string[]) => void
  /** Emit a transport or danger-menu action to the worker bridge (#763).
   * The dock calls this for transport buttons (no confirmation) and after the
   * user confirms a danger-menu item (display off / restart / reboot / shutdown /
   * exit picframe). */
  onAction: (action: InputAction) => void
}

const DOCK_ID = 'pf-dock'
/** Prefix for per-plugin panel element ids: `pf-plugin-panel-<id>`. */
const PANEL_ID_PREFIX = 'pf-plugin-panel-'
const DANGER_DROPDOWN_ID = 'pf-danger-dropdown'
const CONFIRM_BACKDROP_ID = 'pf-confirm-backdrop'
const CONFIRM_MODAL_ID = 'pf-confirm-modal'
const TOOLTIP_ID = 'pf-dock-tooltip'
/** Hover delay (ms) before a dock-icon tooltip appears — long enough that a
 * quick pass does not flicker, short enough to feel responsive. */
const TOOLTIP_DELAY_MS = 600

/** Danger-menu entries (#763). Each item shows a confirm modal before firing
 * `onAction` — even display-off (reversible) goes through the dialog for a
 * consistent mental model, so a stray tap never powers anything down. */
interface DangerEntry {
  action: InputAction
  label: string
  icon: string
  /** `severe` items get the warm hover tint (reboot/shutdown/restart). */
  severe: boolean
  confirmTitle: string
  confirmMessage: string
}

const DANGER_ENTRIES: DangerEntry[] = [
  {
    action: 'display_off',
    label: 'Display Off',
    icon: '🌙',
    severe: false,
    confirmTitle: 'Turn the display off?',
    confirmMessage: 'The screen will power off until the next wake tap.'
  },
  {
    action: 'restart_service',
    label: 'Restart Picframe',
    icon: '🔄',
    severe: true,
    confirmTitle: 'Restart the Picframe service?',
    confirmMessage: 'Picframe will restart. This takes a few seconds.'
  },
  {
    action: 'reboot_host',
    label: 'Reboot',
    icon: '🔁',
    severe: true,
    confirmTitle: 'Reboot the host?',
    confirmMessage: 'The system will reboot. This takes about a minute.'
  },
  {
    action: 'shutdown_host',
    label: 'Shut Down',
    icon: '⏻',
    severe: true,
    confirmTitle: 'Shut down the host?',
    confirmMessage: 'The system will power off completely.'
  },
  {
    action: 'stop',
    label: 'Exit Picframe',
    icon: '⏏',
    severe: true,
    confirmTitle: 'Exit Picframe?',
    confirmMessage: 'Picframe will quit. Restart the service to resume.'
  }
]

/** Default panel size when a layout omits width/height (matches the legacy
 * `#pf-plugin-panel` rule: min(38vw,480px) × min(46vh,360px)). */
const DEFAULT_PANEL_WIDTH = 'min(38vw, 480px)'
const DEFAULT_PANEL_HEIGHT = 'min(46vh, 360px)'

/** Order-independent id-set equality for `emitOnScreen`'s diff guard (#766).
 * The on-screen set is a set (membership is all that matters), so a wake that
 * re-adds a plugin in a different dock position must not re-emit. */
function sameIdSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  for (const id of b) {
    if (!set.has(id)) return false
  }
  return true
}

export class Dock {
  private plugins: PluginEntry[] = []
  private enabledPlugins: string[] = []
  private visiblePlugins: string[] = []
  private pluginConfig: Record<string, Record<string, unknown>> = {}
  /** Per-edge content offset (px), shared by all plugins; forwarded to each
   * plugin iframe so it can pad its content from the matching panel edge. */
  private contentOffset: ContentOffset = { top: 0, bottom: 0, left: 0, right: 0 }
  /** Dock placement (#758): position/margin/idle_hide_seconds. Applied inline
   * to `#pf-dock` in `render()` (the `pf-anchor-*` classes hardcode 12px, so
   * the dock uses inline styles to keep `margin` configurable). */
  private dockLayout: DockLayout = {
    position: 'bottom-center',
    margin: 16,
    idle_hide_seconds: null
  }
  /** Latest media snapshot (#757). When a plugin iframe finishes loading we
   * forward this so a freshly auto-shown `media_change` plugin (whose iframe
   * was not yet present when the `picframe:media` message arrived) renders the
   * current photo instead of its placeholder. */
  private mediaProvider: (() => CurrentMedia | null) | null = null
  /** Cached per-plugin data (#761) so a freshly-loaded iframe (e.g. the clock
   * panel opened after the worker already pushed the live extra-text file)
   * receives the latest value on load, mirroring the media provider. */
  private pluginDataProvider: (() => Record<string, Record<string, unknown>> | null) | null = null
  private readonly root: HTMLElement
  /** Where `#pf-dock` (and the danger dropdown / confirm modal) are appended.
   * Hoisted out of {@link root} (`#pf-content`) into `#overlay-root` so the
   * dock sits above the veil and is never shadowed by a plugin panel's inline
   * z_order (#763). Plugin panels still live in {@link root}. */
  private readonly dockRoot: HTMLElement
  private readonly callbacks: DockCallbacks
  /** Whether the danger dropdown is currently open (#763). */
  private dangerOpen = false
  /** Last on-screen plugin set emitted via `onOnScreenPluginsChange` (#766).
   * `null` until the first emission so the dock reports its initial on-screen
   * state after the first render (already-connected browsers learn it then);
   * subsequent emissions are diff-guarded so auto-hide/wake fades that return
   * to the same set do not spam the runtime channel. */
  private lastEmittedOnScreen: string[] | null = null
  /** Bound outside-click handler for the danger dropdown (kept so it can be
   * detached after close). */
  private boundDangerOutside: ((e: PointerEvent) => void) | null = null
  /** Bound keydown handler for the open confirm modal (#763). */
  private boundConfirmKey: ((e: KeyboardEvent) => void) | null = null
  /** Hover-tooltip controller: a single shared label element, shown after a
   * short delay when the mouse rests on a dock icon (transport buttons,
   * plugin icons, danger trigger). Mouse-only — touch/keyboard users already
   * get the icon `aria-label`, so the tooltip is a mouse convenience. */
  private tooltipEl: HTMLElement | null = null
  private tooltipTimer: number | null = null
  private tooltipTarget: HTMLElement | null = null
  /** Whether delegated pointer listeners have been attached to `#pf-dock`
   * (done once; the dock element persists across re-renders, so delegation
   * handles `render()`'s `replaceChildren` without re-wiring per element). */
  private tooltipDelegated = false

  constructor(root: HTMLElement, dockRoot: HTMLElement, callbacks: DockCallbacks) {
    this.root = root
    this.dockRoot = dockRoot
    this.callbacks = callbacks
  }

  /** Provide a function returning the latest media so newly-loaded plugin
   * iframes receive it on load (#757). */
  setMediaProvider(provider: () => CurrentMedia | null): void {
    this.mediaProvider = provider
  }

  /** Provide a function returning cached per-plugin data so newly-loaded
   * plugin iframes receive the latest pushed values on load (#761). */
  setPluginDataProvider(provider: () => Record<string, Record<string, unknown>> | null): void {
    this.pluginDataProvider = provider
  }

  /** Forward a `postMessage` to a single plugin's iframe (#761). Used to push
   * per-plugin data (e.g. the clock extra-text file contents) to the matching
   * plugin only, rather than broadcasting to every visible plugin. No-op when
   * the plugin panel/iframe is not currently mounted. */
  postToPlugin(pluginId: string, message: unknown): void {
    const panel = this.root.querySelector<HTMLElement>(`#${CSS.escape(PANEL_ID_PREFIX + pluginId)}`)
    const frame = panel?.querySelector<HTMLIFrameElement>('iframe')
    if (!frame?.contentWindow) return
    try {
      frame.contentWindow.postMessage(message, '*')
    } catch {
      /* cross-origin frames may reject postMessage; ignore */
    }
  }

  /** Apply a full shell config (plugins + enabled/visible set + per-plugin config). */
  applyConfig(config: OverlayShellConfig): void {
    this.plugins = config._plugins ?? []
    this.enabledPlugins = config.enabled_plugins ?? []
    this.pluginConfig = config.plugin_config ?? {}
    this.contentOffset = config.content_offset ?? { top: 0, bottom: 0, left: 0, right: 0 }
    this.dockLayout = config.dock_layout ?? this.dockLayout
    this.visiblePlugins = this.resolveVisiblePlugins(config)
    this.render()
  }

  /** Return the effective dock placement (#758). */
  getDockLayout(): DockLayout {
    return this.dockLayout
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

  /** Ensure a plugin is expanded but held hidden (``--idle``) until a later
   * wake reveals it (#757). Used by the shell's ``media_change`` driver: the
   * panel is mounted immediately (so its iframe can load + receive the media
   * postMessage) but kept faded out, then the shell wakes it after the image
   * blend finishes. No-op for disabled/unknown plugins. Unlike
   * {@link togglePlugin} this does **not** fire ``onVisiblePluginsChange`` —
   * the shell owns the scheduled wake.
   *
   * #765: a plugin the user collapsed (removed from ``visiblePlugins`` via the
   * dock toggle, which now persists to ``overlay.visible_plugins``) stays
   * collapsed across photo changes — ``visiblePlugins`` is the single source
   * of truth, matching the remote-tab semantics. So a ``media_change`` plugin
   * auto-shows only while it remains opted-in there; collapsing it stops the
   * auto-show until the user expands it again. */
  showPluginIdle(pluginId: string): void {
    if (!this.isPluginEnabled(pluginId)) return
    if (!this.visiblePlugins.includes(pluginId)) return
    // The plugin is already opted-in (visible); re-arm the idle class so the
    // shell's scheduled wake fades it in after the image blend (#757).
    // #766: route through `setPluginIdle` so the dock icon de-activates too.
    this.setPluginIdle(pluginId, true)
  }

  /** Set a visible plugin's idle state on its panel **and** its dock icon
   * together (#766). When `idle` is true the panel fades out
   * (`pf-plugin-panel--idle`) and the icon loses `pf-dock-icon--active`; when
   * false the panel shows and the icon is highlighted. No-op when the panel
   * is not mounted (unknown/disabled/collapsed plugin). The shell's per-panel
   * idle timers and the `media_change` driver call this so the icon always
   * reflects the on-screen state rather than just the toggled-on config set. */
  setPluginIdle(pluginId: string, idle: boolean): void {
    const panel = this.root.querySelector<HTMLElement>(`#${CSS.escape(PANEL_ID_PREFIX + pluginId)}`)
    if (!panel) return
    if (idle) panel.classList.add('pf-plugin-panel--idle')
    else panel.classList.remove('pf-plugin-panel--idle')
    // The icon is `--active` when the plugin is opted-in *and* currently shown
    // (not idle). A collapsed plugin has no panel/icon here, so this only
    // governs the auto-hide highlight, not the on/off toggle.
    this.setIconActive(pluginId, !idle)
    // #766: an auto-hide fade (idle=true) or wake (idle=false) changed the
    // on-screen set — mirror it to the Remote tab. The dock icon already
    // reflects this via `setIconActive`; the runtime event keeps the web UI's
    // tile highlights in sync. `emitOnScreen` diff-guards so a no-op fade
    // (e.g. re-arming idle on an already-hidden panel) does not spam.
    this.emitOnScreen()
  }

  /** Toggle `pf-dock-icon--active` on the dock icon matching `pluginId`
   * (#766). Located via the `data-plugin-id` attribute set in `buildIcon` so a
   * re-render's rebuilt icon is always found. No-op when the icon is absent
   * (e.g. the plugin is disabled and not in the dock row). */
  private setIconActive(pluginId: string, active: boolean): void {
    const icon = this.dockRoot.querySelector<HTMLElement>(
      `#${DOCK_ID} .pf-dock-icon[data-plugin-id="${CSS.escape(pluginId)}"]`
    )
    icon?.classList.toggle('pf-dock-icon--active', active)
  }

  /** Reconcile each visible plugin's dock-icon `--active` state with its
   * panel's current `--idle` class after a `render()` (#766). `applyPanelLayout`
   * preserves `--idle` across re-renders (#767); a brand-new panel has none, so
   * its icon stays active (shown). Called once at the end of `render()` so the
   * rebuilt icons reflect reality rather than just the toggled-on set. */
  private syncIconStates(): void {
    for (const plugin of this.plugins.filter(p => this.enabledPlugins.includes(p.id))) {
      if (!this.visiblePlugins.includes(plugin.id)) continue
      const panel = this.root.querySelector<HTMLElement>(
        `#${CSS.escape(PANEL_ID_PREFIX + plugin.id)}`
      )
      const idle = panel?.classList.contains('pf-plugin-panel--idle') ?? false
      this.setIconActive(plugin.id, !idle)
    }
  }

  /** Whether a plugin id is currently enabled (loaded/active). */
  isPluginEnabled(id: string | null | undefined): id is string {
    return !!id && this.enabledPlugins.includes(id)
  }

  /** The set of expanded plugins currently shown on screen (#766) — i.e. those
   * in `visiblePlugins` whose panel exists and is **not** auto-hidden
   * (no `pf-plugin-panel--idle`). Auto-hide is a client-side CSS fade, so this
   * is the runtime counterpart of the persisted `visiblePlugins` config set.
   * Order follows `visiblePlugins` for a stable, deterministic emission; the
   * set itself is unordered (membership is all that matters). */
  onScreenPluginIds(): string[] {
    return this.visiblePlugins.filter(id => {
      const panel = this.root.querySelector<HTMLElement>(`#${CSS.escape(PANEL_ID_PREFIX + id)}`)
      if (!panel) return false
      return !panel.classList.contains('pf-plugin-panel--idle')
    })
  }

  /** Diff-guarded emission of the on-screen set via
   * `onOnScreenPluginsChange` (#766). The first call (after boot) always fires
   * so already-connected browsers learn the initial on-screen state;
   * subsequent calls only fire when the set actually changed, so a re-render
   * or a no-op fade that leaves the on-screen set unchanged does not spam the
   * runtime channel. */
  private emitOnScreen(): void {
    const next = this.onScreenPluginIds()
    const last = this.lastEmittedOnScreen
    if (last !== null && sameIdSet(last, next)) return
    this.lastEmittedOnScreen = next
    this.callbacks.onOnScreenPluginsChange(next)
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

  private render(): void {
    const enabled = this.plugins.filter(p => this.enabledPlugins.includes(p.id))
    // Close any open dropdown / confirm modal before re-rendering so a config
    // push never leaves a stale overlay pointing at removed DOM (#763).
    this.closeDangerDropdown()
    this.closeConfirm()
    // A re-render replaces every dock icon (replaceChildren below); drop any
    // showing tooltip so it does not float over the rebuilt dock.
    this.hideTooltip()

    let dock = this.dockRoot.querySelector<HTMLElement>(`#${DOCK_ID}`)
    if (!dock) {
      dock = document.createElement('div')
      dock.id = DOCK_ID
      dock.className = 'pf-dock'
      this.dockRoot.appendChild(dock)
    }
    this.applyDockPlacement(dock, this.dockLayout)
    // Attach delegated hover-tooltip listeners once (the dock element persists
    // across re-renders; delegation picks up the rebuilt children automatically).
    this.attachTooltipDelegation(dock)

    // Dock contents (#763): transport buttons | divider | plugin icons |
    // divider | danger menu. Transport + danger live in the dock so they
    // share its auto-hide + z-order hoist; plugin icons follow when present.
    // The transport row is prev/toggle/next only — there is no "stop" button:
    // the dock auto-hides on idle, and tearing down playback / powering down
    // belongs in the danger menu (⏻ Power dropdown).
    const children: HTMLElement[] = [
      this.buildTransportButton('prev', '⏮', 'Previous'),
      this.buildTransportButton('toggle', '⏯', 'Play / Pause'),
      this.buildTransportButton('next', '⏭', 'Next')
    ]
    if (enabled.length > 0) {
      children.push(this.buildDivider())
      children.push(...enabled.map(p => this.buildIcon(p)))
    }
    children.push(this.buildDivider())
    children.push(this.buildDangerButton())
    dock.replaceChildren(...children)

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
    // #766: the dock icons were just rebuilt; reconcile their `--active` state
    // with the panels' current `--idle` classes (preserved by
    // `applyPanelLayout`, #767) so an auto-hidden plugin's icon is not
    // highlighted while its panel is faded out.
    this.syncIconStates()
    // #766: a toggle or config apply may have mounted/removed panels (changing
    // the on-screen set) — mirror it to the Remote tab. Runs after
    // `syncIconStates` so the on-screen set reflects the rebuilt panels.
    this.emitOnScreen()
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

  /** Apply the dock placement (9-anchor + margin) inline to `#pf-dock` (#758).
   *
   * The `pf-anchor-*` classes hardcode a 12px edge margin, so the dock uses
   * inline styles to keep `margin` configurable. Center/middle anchors combine
   * the 50% offset with a `translate` transform so the dock stays centered
   * while the margin offsets it from the chosen edge. */
  private applyDockPlacement(dock: HTMLElement, layout: DockLayout): void {
    const m = `${layout.margin}px`
    dock.style.top = ''
    dock.style.bottom = ''
    dock.style.left = ''
    dock.style.right = ''
    dock.style.transform = ''
    const [v, h] = layout.position.split('-') as [
      'top' | 'middle' | 'bottom',
      'left' | 'center' | 'right'
    ]
    const translate: string[] = []
    if (v === 'top') {
      dock.style.top = m
    } else if (v === 'bottom') {
      dock.style.bottom = m
    } else {
      dock.style.top = '50%'
      translate.push('translateY(-50%)')
    }
    if (h === 'left') {
      dock.style.left = m
    } else if (h === 'right') {
      dock.style.right = m
    } else {
      dock.style.left = '50%'
      translate.push('translateX(-50%)')
    }
    if (translate.length) dock.style.transform = translate.join(' ')
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
    // #767: preserve the idle class across re-renders. `render()` reuses an
    // existing panel element (looked up by id) but resetting `className` here
    // would wipe `pf-plugin-panel--idle` that shell.ts armed via
    // `showPluginIdle` / the per-panel idle timers — revealing an auto-hidden
    // sibling when an unrelated plugin is toggled. Capture + re-apply so a
    // re-render never changes a panel's idle state. `applyConfig` is unaffected
    // by this preservation: it is followed by `wake(true, true, false)` (#773)
    // which skips already-`--idle` panels (leaving them hidden) and only
    // reveals + re-arms panels that are currently shown or freshly mounted,
    // and a brand-new panel has no `--idle` class to preserve.
    const wasIdle = panel.classList.contains('pf-plugin-panel--idle')
    panel.className = `pf-plugin-panel pf-anchor-${layout.position}`
    if (wasIdle) panel.classList.add('pf-plugin-panel--idle')
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
    // #766: tag the icon with its plugin id so `setIconActive`/`syncIconStates`
    // can locate the rebuilt icon after a re-render and keep its `--active`
    // state in sync with the panel's on-screen (idle) state.
    btn.setAttribute('data-plugin-id', plugin.id)
    if (this.visiblePlugins.includes(plugin.id)) btn.classList.add('pf-dock-icon--active')
    btn.setAttribute('aria-label', plugin.name || plugin.id)
    // The hover tooltip shows the plugin's display name (same as the
    // aria-label) so a mouse user can identify an icon-only plugin.
    btn.setAttribute('data-tooltip', plugin.name || plugin.id)
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

  /** Build a transport button (prev/next/toggle/hide) that emits its action
   * immediately on click — no confirmation (#763). */
  private buildTransportButton(action: InputAction, icon: string, label: string): HTMLElement {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'pf-dock-icon'
    btn.setAttribute('aria-label', label)
    btn.setAttribute('data-tooltip', label)
    btn.textContent = icon
    btn.addEventListener('click', e => {
      e.stopPropagation()
      this.callbacks.onAction(action)
    })
    return btn
  }

  /** Build a vertical divider separating dock groups (#763). */
  private buildDivider(): HTMLElement {
    const div = document.createElement('span')
    div.className = 'pf-dock-divider'
    div.setAttribute('aria-hidden', 'true')
    return div
  }

  /** Build the danger-menu trigger button (power icon). Toggles the
   * dropdown (#763). */
  private buildDangerButton(): HTMLElement {
    const btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'pf-dock-icon pf-dock-danger'
    btn.setAttribute('aria-label', 'System')
    btn.setAttribute('data-tooltip', 'System')
    btn.setAttribute('aria-haspopup', 'menu')
    btn.setAttribute('aria-expanded', String(this.dangerOpen))
    btn.textContent = '⏻'
    btn.addEventListener('click', e => {
      e.stopPropagation()
      if (this.dangerOpen) this.closeDangerDropdown()
      else this.openDangerDropdown(btn)
    })
    return btn
  }

  /** Open the danger dropdown anchored below the trigger button (#763). */
  private openDangerDropdown(triggerBtn: HTMLElement): void {
    this.closeDangerDropdown()
    this.dangerOpen = true
    triggerBtn.setAttribute('aria-expanded', 'true')
    const dropdown = document.createElement('div')
    dropdown.id = DANGER_DROPDOWN_ID
    dropdown.setAttribute('role', 'menu')
    for (const entry of DANGER_ENTRIES) {
      const item = document.createElement('button')
      item.type = 'button'
      item.className = 'pf-danger-item' + (entry.severe ? ' pf-danger-item--severe' : '')
      item.setAttribute('role', 'menuitem')
      const iconSpan = document.createElement('span')
      iconSpan.setAttribute('aria-hidden', 'true')
      iconSpan.textContent = entry.icon
      const labelSpan = document.createElement('span')
      labelSpan.textContent = entry.label
      item.append(iconSpan, labelSpan)
      item.addEventListener('click', ev => {
        ev.stopPropagation()
        this.closeDangerDropdown()
        this.openConfirm(entry)
      })
      dropdown.appendChild(item)
    }
    this.dockRoot.appendChild(dropdown)
    const rect = triggerBtn.getBoundingClientRect()
    const dw = dropdown.offsetWidth
    const dh = dropdown.offsetHeight
    let left = rect.left + rect.width / 2 - dw / 2
    let top = rect.bottom + 8
    left = Math.max(8, Math.min(left, window.innerWidth - dw - 8))
    if (top + dh > window.innerHeight - 8) top = rect.top - dh - 8
    dropdown.style.left = `${left}px`
    dropdown.style.top = `${top}px`
    this.boundDangerOutside = (ev: PointerEvent) => {
      const target = ev.target as Node | null
      if (target && !dropdown.contains(target) && target !== triggerBtn) {
        this.closeDangerDropdown()
      }
    }
    window.setTimeout(() => {
      if (this.boundDangerOutside) {
        this.dockRoot.addEventListener('pointerdown', this.boundDangerOutside)
      }
    }, 0)
  }

  /** Close and detach the danger dropdown (#763). */
  private closeDangerDropdown(): void {
    if (this.boundDangerOutside) {
      this.dockRoot.removeEventListener('pointerdown', this.boundDangerOutside)
      this.boundDangerOutside = null
    }
    this.dockRoot.querySelector(`#${DANGER_DROPDOWN_ID}`)?.remove()
    this.dangerOpen = false
    const trigger = this.dockRoot.querySelector<HTMLElement>('.pf-dock-danger')
    trigger?.setAttribute('aria-expanded', 'false')
  }

  /** Open a confirm modal for a danger entry (#763). Cancel closes the modal;
   * Confirm fires `onAction` then closes. Escape closes the modal and stops
   * propagation so the global InputRouter Escape→hide does not also fire. */
  private openConfirm(entry: DangerEntry): void {
    this.closeConfirm()
    const backdrop = document.createElement('div')
    backdrop.id = CONFIRM_BACKDROP_ID
    const modal = document.createElement('div')
    modal.id = CONFIRM_MODAL_ID
    modal.setAttribute('role', 'alertdialog')
    modal.setAttribute('aria-modal', 'true')
    modal.setAttribute('aria-labelledby', 'pf-confirm-title')
    modal.setAttribute('aria-describedby', 'pf-confirm-msg')
    const title = document.createElement('h2')
    title.id = 'pf-confirm-title'
    title.textContent = entry.confirmTitle
    const msg = document.createElement('p')
    msg.id = 'pf-confirm-msg'
    msg.textContent = entry.confirmMessage
    const actions = document.createElement('div')
    actions.className = 'pf-confirm-actions'
    const cancel = document.createElement('button')
    cancel.type = 'button'
    cancel.className = 'pf-confirm-btn pf-confirm-cancel'
    cancel.textContent = 'Cancel'
    const ok = document.createElement('button')
    ok.type = 'button'
    ok.className = 'pf-confirm-btn pf-confirm-ok'
    ok.textContent = 'Confirm'
    actions.append(cancel, ok)
    modal.append(title, msg, actions)
    backdrop.appendChild(modal)
    this.dockRoot.appendChild(backdrop)

    const dismiss = (): void => this.closeConfirm()
    cancel.addEventListener('click', e => {
      e.stopPropagation()
      dismiss()
    })
    ok.addEventListener('click', e => {
      e.stopPropagation()
      this.closeConfirm()
      this.callbacks.onAction(entry.action)
    })
    backdrop.addEventListener('pointerdown', e => {
      if (e.target === backdrop) {
        e.stopPropagation()
        dismiss()
      }
    })

    // Escape closes the modal (stops the global hide handler); Enter activates
    // the focused button; Tab is trapped between Cancel and Confirm. Focus
    // Cancel on open so the destructive action is never the default. Capture
    // phase runs before the window-level InputRouter keydown.
    this.boundConfirmKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopImmediatePropagation()
        e.preventDefault()
        dismiss()
        return
      }
      if (e.key === 'Enter') {
        e.stopImmediatePropagation()
        e.preventDefault()
        if (document.activeElement === ok) {
          this.closeConfirm()
          this.callbacks.onAction(entry.action)
        } else {
          dismiss()
        }
        return
      }
      if (e.key === 'Tab') {
        e.preventDefault()
        if (e.shiftKey) {
          ;(document.activeElement === ok ? cancel : ok).focus()
        } else {
          ;(document.activeElement === cancel ? ok : cancel).focus()
        }
      }
    }
    window.addEventListener('keydown', this.boundConfirmKey, true)
    cancel.focus()
  }

  /** Remove the confirm modal + detach its capture-phase key handler (#763). */
  private closeConfirm(): void {
    if (this.boundConfirmKey) {
      window.removeEventListener('keydown', this.boundConfirmKey, true)
      this.boundConfirmKey = null
    }
    this.dockRoot.querySelector(`#${CONFIRM_BACKDROP_ID}`)?.remove()
  }

  /** Lazily create the shared tooltip element in the dock root so it sits above
   * the dock (z-index 24 > dock 20, but below the danger dropdown 25 and the
   * confirm backdrop/modal 30/31, so it never covers an open menu or dialog). */
  private ensureTooltip(): HTMLElement {
    if (this.tooltipEl && this.tooltipEl.isConnected) return this.tooltipEl
    const el = document.createElement('div')
    el.id = TOOLTIP_ID
    el.className = 'pf-dock-tooltip'
    el.setAttribute('role', 'tooltip')
    this.dockRoot.appendChild(el)
    this.tooltipEl = el
    return el
  }

  /** Attach delegated pointer listeners to `#pf-dock` once. Delegation handles
   * dynamically rebuilt dock children (`render()` calls `replaceChildren`)
   * without re-wiring per element. Mouse-only — touch and keyboard users
   * already get the icon `aria-label`. */
  private attachTooltipDelegation(dock: HTMLElement): void {
    if (this.tooltipDelegated) return
    this.tooltipDelegated = true
    dock.addEventListener('pointerover', (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      const icon = (e.target as HTMLElement | null)?.closest<HTMLElement>(
        '.pf-dock-icon[data-tooltip]'
      )
      if (!icon || !dock.contains(icon)) return
      this.armTooltip(icon)
    })
    dock.addEventListener('pointerout', (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      const icon = (e.target as HTMLElement | null)?.closest<HTMLElement>(
        '.pf-dock-icon[data-tooltip]'
      )
      if (!icon || !dock.contains(icon)) return
      // Only dismiss when the pointer left the icon entirely (not just moved
      // between children of the same icon, e.g. an inline SVG).
      const related = e.relatedTarget as Node | null
      if (related && icon.contains(related)) return
      this.hideTooltip()
    })
  }

  /** Arm the show timer for an icon. Re-arming to a different icon cancels the
   * pending show first, so a quick sweep across the dock does not stack or
   * mis-target tooltips. */
  private armTooltip(icon: HTMLElement): void {
    if (this.tooltipTarget === icon) return
    this.hideTooltip()
    this.tooltipTarget = icon
    const label = icon.getAttribute('data-tooltip') ?? ''
    this.tooltipTimer = window.setTimeout(() => {
      this.tooltipTimer = null
      this.showTooltip(icon, label)
    }, TOOLTIP_DELAY_MS)
  }

  /** Position the shared label above the icon (flipping below when the dock is
   * at the top edge so the label stays on screen for any dock anchor). */
  private showTooltip(icon: HTMLElement, label: string): void {
    const el = this.ensureTooltip()
    el.textContent = label
    el.classList.add('pf-dock-tooltip--visible')
    // Measure after the visible class applies (the element is always laid
    // out, so offsetWidth/Height are real even while fading in).
    const tw = el.offsetWidth
    const th = el.offsetHeight
    const rect = icon.getBoundingClientRect()
    let left = rect.left + rect.width / 2 - tw / 2
    let top = rect.top - th - 8
    left = Math.max(8, Math.min(left, window.innerWidth - tw - 8))
    if (top < 8) top = rect.bottom + 8
    el.style.left = `${left}px`
    el.style.top = `${top}px`
  }

  /** Cancel the pending show timer, clear the armed target, and hide the
   * label. Called on pointer-leave, dock idle, destroy, and before re-render. */
  private hideTooltip(): void {
    if (this.tooltipTimer !== null) {
      window.clearTimeout(this.tooltipTimer)
      this.tooltipTimer = null
    }
    this.tooltipTarget = null
    this.tooltipEl?.classList.remove('pf-dock-tooltip--visible')
  }

  /** Close any open dropdown / confirm modal (#763). Called by the shell when
   * the dock enters its idle state (so transient overlays don't outlive the
   * faded dock — the dropdown is a sibling of #pf-dock and the idle CSS only
   * hides #pf-dock) and by destroy() for teardown. */
  closeOverlays(): void {
    this.closeDangerDropdown()
    this.closeConfirm()
    this.hideTooltip()
  }

  /** Tear down transient overlays + detach window listeners (#763). Called by
   * the shell on destroy so a left-open modal never leaks its key handler. */
  destroy(): void {
    this.closeOverlays()
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
        // #757: forward the latest media so a freshly auto-shown plugin (whose
        // iframe was not present when the live `picframe:media` message fired)
        // renders the current photo instead of its placeholder. Harmless for
        // plugins that ignore `picframe:media` (e.g. clock/weather).
        const media = this.mediaProvider?.()
        if (media) {
          frame.contentWindow?.postMessage({ type: 'picframe:media', media }, '*')
        }
        // #761: forward any cached per-plugin data (e.g. the clock extra-text
        // file contents the worker already pushed) so a freshly-opened panel
        // shows the latest value instead of waiting for the next poll.
        const pdata = this.pluginDataProvider?.()?.[plugin.id]
        if (pdata) {
          for (const [key, value] of Object.entries(pdata)) {
            frame.contentWindow?.postMessage({ type: 'picframe:data', key, value }, '*')
          }
        }
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
