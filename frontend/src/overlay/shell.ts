/**
 * Overlay shell orchestrator (#739, items 10–11).
 *
 * Builds the transparent overlay DOM (visible-plugin panel below a
 * pointer/keyboard "veil" with the dock above it), wires the input router,
 * dock, idle-hide content fading, the `/ws/state` client, and the worker JS
 * bridge. The worker pushes the live config via `window.picframe.applyConfig`;
 * the shell boots by asking for it via `__request_config`.
 *
 * Visibility model: the dock and the plugin content fade on **separate**
 * timers. The dock is navigation chrome — it *always* auto-hides after the
 * idle interval (defaulting to {@link DOCK_IDLE_FALLBACK_SECONDS} when
 * `idle_hide_seconds` is 0), so a `persistent`-mode clock still shows but the
 * icon bar does not linger. The plugin content follows `display_mode`
 * (`persistent` = always visible; `auto_hide` = fades after
 * `idle_hide_seconds`). Both timers reset on any enabled input event.
 */

import { registerApplyConfig, sendAction } from './bridge'
import { Dock } from './dock'
import { readEnv } from './env'
import { InputRouter } from './input'
import { StateClient } from './state-client'
import type { DisplayMode, InputAction, InputType, OverlayShellConfig } from './types'

const DEFAULT_IDLE_HIDE_SECONDS = 5
/** Dock fallback when `idle_hide_seconds` is 0 (content stays, dock still hides). */
const DOCK_IDLE_FALLBACK_SECONDS = 5

export class OverlayShell {
  private readonly root: HTMLElement
  private content: HTMLElement
  private veil: HTMLElement
  private dock: Dock
  private router: InputRouter
  private state: StateClient | null = null
  private idleTimer: number | null = null
  private dockIdleTimer: number | null = null
  private displayMode: DisplayMode = 'auto_hide'
  private idleHideSeconds = DEFAULT_IDLE_HIDE_SECONDS
  /** Currently enabled input classes; the mouse-move cursor reveal only fires
   * when `mouse` is among them (#739). */
  private enabledTypes: InputType[] = ['touch', 'mouse', 'keyboard']

  constructor(root: HTMLElement) {
    this.root = root
    this.root.classList.add('pf-root')

    // Visible-plugin panel (below the veil; non-interactive until Phase 3).
    this.content = document.createElement('div')
    this.content.id = 'pf-content'
    this.root.appendChild(this.content)

    // Transparent full-screen veil that captures navigation input.
    this.veil = document.createElement('div')
    this.veil.id = 'pf-veil'
    this.root.appendChild(this.veil)

    this.dock = new Dock(this.content, {
      onVisiblePluginChange: () => this.wake()
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
        // Forward live media changes into the active plugin iframe so plugins
        // (e.g. `meta`) can react to photo changes without their own WS client.
        onMedia: media => this.dock.postToActivePlugin({ type: 'picframe:media', media })
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
    this.clearIdle()
    this.clearDockIdle()
  }

  private applyConfig(config: OverlayShellConfig): void {
    this.displayMode = config.display_mode ?? 'auto_hide'
    this.idleHideSeconds = config.idle_hide_seconds ?? DEFAULT_IDLE_HIDE_SECONDS
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
   * Reset both idle timers and reveal the dock + plugin content. The content
   * timer only runs in `auto_hide` mode; the dock timer always runs (the dock
   * is chrome and always auto-hides), using `idle_hide_seconds` or the dock
   * fallback when `idle_hide_seconds` is 0.
   */
  private wake(): void {
    this.root.classList.remove('pf-root--idle', 'pf-root--dock-idle')
    this.clearIdle()
    this.clearDockIdle()
    // Plugin content: fades only in auto_hide mode (persistent = always visible).
    if (this.displayMode === 'auto_hide' && this.idleHideSeconds > 0) {
      this.idleTimer = window.setTimeout(
        () => this.root.classList.add('pf-root--idle'),
        Math.max(0, this.idleHideSeconds) * 1000
      )
    }
    // Dock: always auto-hides. Reuse idle_hide_seconds, or the fallback when 0.
    // The cursor hides together with the dock so the two stay in sync: removing
    // `pf-root--cursor` reverts the root to the inherited `cursor: none` (#739).
    const dockSeconds = this.idleHideSeconds > 0 ? this.idleHideSeconds : DOCK_IDLE_FALLBACK_SECONDS
    this.dockIdleTimer = window.setTimeout(
      () => {
        this.root.classList.add('pf-root--dock-idle')
        this.root.classList.remove('pf-root--cursor')
      },
      Math.max(0, dockSeconds) * 1000
    )
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

  private clearIdle(): void {
    if (this.idleTimer !== null) {
      window.clearTimeout(this.idleTimer)
      this.idleTimer = null
    }
  }

  private clearDockIdle(): void {
    if (this.dockIdleTimer !== null) {
      window.clearTimeout(this.dockIdleTimer)
      this.dockIdleTimer = null
    }
  }
}
