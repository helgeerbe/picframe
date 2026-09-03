/**
 * Overlay shell orchestrator (#739, items 10–11).
 *
 * Builds the transparent overlay DOM (visible-plugin panel below a
 * pointer/keyboard "veil" with the dock above it), wires the input router,
 * dock, idle-hide content fading, the `/ws/state` client, and the worker JS
 * bridge. The worker pushes the live config via `window.picframe.applyConfig`;
 * the shell boots by asking for it via `__request_config`.
 */

import { registerApplyConfig, sendAction } from './bridge'
import { Dock } from './dock'
import { readEnv } from './env'
import { InputRouter } from './input'
import { StateClient } from './state-client'
import type { DisplayMode, InputAction, InputType, OverlayShellConfig } from './types'

const DEFAULT_IDLE_HIDE_SECONDS = 5

export class OverlayShell {
  private readonly root: HTMLElement
  private content: HTMLElement
  private veil: HTMLElement
  private dock: Dock
  private router: InputRouter
  private state: StateClient | null = null
  private idleTimer: number | null = null
  private displayMode: DisplayMode = 'auto_hide'
  private idleHideSeconds = DEFAULT_IDLE_HIDE_SECONDS

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
    this.router.detach()
    this.state?.stop()
    this.clearIdle()
  }

  private applyConfig(config: OverlayShellConfig): void {
    this.displayMode = config.display_mode ?? 'auto_hide'
    this.idleHideSeconds = config.idle_hide_seconds ?? DEFAULT_IDLE_HIDE_SECONDS
    const enabledTypes = (config.enabled_input_types ?? [
      'touch',
      'mouse',
      'keyboard'
    ]) as InputType[]
    this.router.setEnabledTypes(enabledTypes)
    this.dock.applyConfig(config)
    this.wake()
  }

  /** Reset the idle timer and reveal the content (dock + visible plugin). */
  private wake(): void {
    this.root.classList.remove('pf-root--idle')
    this.clearIdle()
    if (this.displayMode === 'auto_hide' && this.idleHideSeconds > 0) {
      this.idleTimer = window.setTimeout(
        () => this.root.classList.add('pf-root--idle'),
        Math.max(0, this.idleHideSeconds) * 1000
      )
    }
  }

  private clearIdle(): void {
    if (this.idleTimer !== null) {
      window.clearTimeout(this.idleTimer)
      this.idleTimer = null
    }
  }
}
