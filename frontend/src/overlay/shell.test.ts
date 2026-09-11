import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { OverlayShell } from './shell'
import type { OverlayShellConfig, PluginEntry } from './types'

/**
 * Overlay shell integration tests (#773).
 *
 * These mount a real `OverlayShell` against a happy-dom document and drive it
 * through the same `window.picframe.applyConfig` JS bridge the out-of-process
 * worker uses, then assert on the rendered panel DOM (`pf-plugin-panel--idle`
 * is the auto-hide class). `readEnv()` sees an empty `location.search` in
 * happy-dom, so no `/ws/state` `StateClient` is constructed and the test stays
 * hermetic. Fake timers control the `idle_hide_seconds` countdowns.
 */

const PANEL_ID_PREFIX = 'pf-plugin-panel-'

let root: HTMLElement
let shell: OverlayShell

beforeEach(() => {
  vi.useFakeTimers()
  root = document.createElement('div')
  root.id = 'overlay-root'
  document.body.appendChild(root)
  shell = new OverlayShell(root)
  shell.boot()
})

afterEach(() => {
  shell.destroy()
  root.remove()
  vi.useRealTimers()
  // Reset the JS bridge so each test re-registers handlers on a clean object.
  window.picframe = undefined
})

/** Minimal auto-hide plugin (no manifest `size` → fill mode; no per-plugin
 * layout → `auto_hide` + global `idle_hide_seconds` fallback). */
function makePlugin(id: string): PluginEntry {
  return {
    id,
    name: id,
    icon: '🖼',
    position: 'bottom-center',
    entry_uri: `file:///plugins/${id}/index.html`
  }
}

/** Push a shell config through the worker JS bridge (the Remote/Appearance
 * path). Mirrors how `overlay_worker.py` calls `evaluate_javascript` with the
 * live config. */
function applyConfig(config: OverlayShellConfig): void {
  expect(window.picframe?.applyConfig).toBeDefined()
  window.picframe!.applyConfig!(config)
}

function panel(id: string): HTMLElement | null {
  return document.getElementById(PANEL_ID_PREFIX + id)
}

function isIdle(id: string): boolean {
  return panel(id)?.classList.contains('pf-plugin-panel--idle') ?? false
}

describe('OverlayShell.applyConfig — auto-hide sibling reveal (#773)', () => {
  it('arms idle timers for all visible auto-hide panels on the first (boot) push', () => {
    const a = makePlugin('a')
    const b = makePlugin('b')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a', 'b'],
      visible_plugins: ['a', 'b'],
      idle_hide_seconds: 5,
      _plugins: [a, b]
    })

    // Both panels mount shown (no --idle) and are armed to fade after 5 s.
    expect(isIdle('a')).toBe(false)
    expect(isIdle('b')).toBe(false)

    vi.advanceTimersByTime(4999)
    expect(isIdle('a')).toBe(false)
    expect(isIdle('b')).toBe(false)

    vi.advanceTimersByTime(1)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })

  it('does not un-hide auto-hidden siblings when a config push toggles a new plugin on', () => {
    const a = makePlugin('a')
    const b = makePlugin('b')
    const c = makePlugin('c')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a', 'b', 'c'],
      visible_plugins: ['a', 'b'],
      idle_hide_seconds: 5,
      _plugins: [a, b, c]
    })

    // Let a + b auto-hide.
    vi.advanceTimersByTime(5000)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)

    // Remote toggles 'c' on → config push with visible_plugins: [a, b, c].
    applyConfig({
      enabled: true,
      enabled_plugins: ['a', 'b', 'c'],
      visible_plugins: ['a', 'b', 'c'],
      idle_hide_seconds: 5,
      _plugins: [a, b, c]
    })

    // 'c' is freshly mounted (no --idle) → shown + armed.
    expect(isIdle('c')).toBe(false)
    // 'a' and 'b' were auto-hidden; the config-push wake must leave them faded
    // (the regression was that a full wake() stripped --idle here).
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)

    // 'c' still auto-hides on its own timer after the idle interval.
    vi.advanceTimersByTime(4999)
    expect(isIdle('c')).toBe(false)
    vi.advanceTimersByTime(1)
    expect(isIdle('c')).toBe(true)
    // Siblings stayed hidden the whole time.
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })

  it('does not un-hide auto-hidden siblings when a config push toggles a plugin off', () => {
    const a = makePlugin('a')
    const b = makePlugin('b')
    const c = makePlugin('c')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a', 'b', 'c'],
      visible_plugins: ['a', 'b', 'c'],
      idle_hide_seconds: 5,
      _plugins: [a, b, c]
    })

    vi.advanceTimersByTime(5000)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
    expect(isIdle('c')).toBe(true)

    // Remote toggles 'c' off → visible_plugins: [a, b]. 'c' panel is removed.
    applyConfig({
      enabled: true,
      enabled_plugins: ['a', 'b', 'c'],
      visible_plugins: ['a', 'b'],
      idle_hide_seconds: 5,
      _plugins: [a, b, c]
    })

    expect(panel('c')).toBeNull()
    // 'a' and 'b' stay auto-hidden — collapsing a sibling must not reveal them.
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })
})

describe('OverlayShell.applyConfig — dock flash on Remote toggle (#775)', () => {
  /** The dock auto-hide class on the overlay root (drives dock visibility). */
  function dockIdle(): boolean {
    return root.classList.contains('pf-root--dock-idle')
  }

  it('reveals the dock on the boot push, then auto-hides it', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })

    // Boot push reveals the dock (no --dock-idle) and arms its 5 s timer.
    expect(dockIdle()).toBe(false)

    vi.advanceTimersByTime(4999)
    expect(dockIdle()).toBe(false)
    vi.advanceTimersByTime(1)
    expect(dockIdle()).toBe(true)
  })

  it('does not reveal the dock or re-arm its timer on a second (Remote) push', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })

    // Boot: dock shown, 5 s timer armed.
    expect(dockIdle()).toBe(false)

    // Let 3 s pass — 2 s remain on the dock-idle timer.
    vi.advanceTimersByTime(3000)
    expect(dockIdle()).toBe(false)

    // Remote toggles something → a second config push. The dock must NOT be
    // re-revealed and its timer must NOT be cleared/re-armed: if the original
    // 2 s countdown is left alone, the dock hides 2 s later (not 5 s).
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })

    expect(dockIdle()).toBe(false)

    // With the regression, the second push reset the timer to 5 s, so 2 s
    // later the dock would still be shown. With the fix the original timer is
    // untouched, so exactly 2 s later the dock hides.
    vi.advanceTimersByTime(2000)
    expect(dockIdle()).toBe(true)

    // And a further 3 s (which would be t=5 s on a reset timer) does not bring
    // it back — confirming the timer was not re-armed.
    vi.advanceTimersByTime(3000)
    expect(dockIdle()).toBe(true)
  })

  it('does not touch the dock when it is already hidden on a second push', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })

    // Let the dock fully auto-hide.
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)

    // A second (Remote) push must not pop the dock back up.
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })

    expect(dockIdle()).toBe(true)
  })
})

describe('OverlayShell — Escape toggles the dock (#780)', () => {
  /** Dock auto-hide class on the overlay root (drives dock visibility). */
  function dockIdle(): boolean {
    return root.classList.contains('pf-root--dock-idle')
  }

  function escape(): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  }

  function key(key: string): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  }

  it('hides the dock when shown, then reveals it when hidden (symmetric toggle)', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })
    // The boot push wakes the dock (no --dock-idle right away).
    expect(dockIdle()).toBe(false)

    // 1st Escape (dock shown) -> hide.
    escape()
    expect(dockIdle()).toBe(true)
    // 2nd Escape (dock hidden) -> wake.
    escape()
    expect(dockIdle()).toBe(false)
    // 3rd Escape (dock shown again) -> hide — toggle is symmetric.
    escape()
    expect(dockIdle()).toBe(true)
  })

  it('reveals the dock on an unmapped key instead of doing nothing', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })
    // Let the dock auto-hide.
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)

    // An unmapped key now wakes the dock (reveals it) — was a no-op before #780.
    key('x')
    expect(dockIdle()).toBe(false)
  })

  it('wakes the dock on a reserved key while preserving native behavior', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)

    // Tab is reserved (no preventDefault) but still wakes the dock.
    key('Tab')
    expect(dockIdle()).toBe(false)
  })
})

describe('OverlayShell — two-step wake-then-navigate (#780)', () => {
  /** Dock auto-hide class on the overlay root (drives dock visibility). */
  function dockIdle(): boolean {
    return root.classList.contains('pf-root--dock-idle')
  }

  function key(key: string): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  }

  it('a bound key on a hidden dock only wakes; it navigates on the next press', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })
    // Spy on the worker bridge to observe dispatched actions. The shell
    // already created window.picframe.send (no-op) during boot.
    const send = vi.fn()
    expect(window.picframe).toBeDefined()
    window.picframe!.send = send

    // Let the dock auto-hide.
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)

    // First ArrowRight on a hidden dock: wakes only — no action dispatched.
    key('ArrowRight')
    expect(dockIdle()).toBe(false)
    expect(send).not.toHaveBeenCalledWith({ action: 'next' })

    // Second ArrowRight (dock now visible): the action fires over the bridge.
    key('ArrowRight')
    expect(send).toHaveBeenCalledWith({ action: 'next' })
  })

  it('a bound key navigates in one press when the dock is already visible', () => {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })
    const send = vi.fn()
    window.picframe!.send = send
    // Dock is awake right after the boot push.
    expect(dockIdle()).toBe(false)

    key('ArrowLeft')
    expect(send).toHaveBeenCalledWith({ action: 'prev' })
  })
})

describe('OverlayShell — all inputs wake the dock only (#766/#780)', () => {
  /** Dock auto-hide class on the overlay root (drives dock visibility). */
  function dockIdle(): boolean {
    return root.classList.contains('pf-root--dock-idle')
  }

  /** The veil captures pointerdown (the InputRouter root). */
  function veil(): HTMLElement {
    return document.getElementById('pf-veil')!
  }

  function key(key: string): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  }

  function escape(): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  }

  /** A pointer tap on the veil (the path a touch/mouse click takes). */
  function tap(pointerType: string): void {
    veil().dispatchEvent(new PointerEvent('pointerdown', { pointerType, bubbles: true }))
  }

  function setupTwoAutoHidePlugins() {
    const a = makePlugin('a')
    const b = makePlugin('b')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a', 'b'],
      visible_plugins: ['a', 'b'],
      idle_hide_seconds: 5,
      _plugins: [a, b]
    })
    // Let both panels + the dock auto-hide.
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  }

  it('a keyboard key on a hidden dock wakes the dock but leaves auto-hidden panels hidden', () => {
    setupTwoAutoHidePlugins()

    // A keyboard key wakes the dock only — panels stay auto-hidden.
    key('x')
    expect(dockIdle()).toBe(false)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })

  it('a touch tap on a hidden dock wakes the dock but leaves auto-hidden panels hidden', () => {
    setupTwoAutoHidePlugins()

    // A touch tap wakes the dock only — panels stay auto-hidden. Touch no
    // longer does a full wake (#780): it now matches mouse/keyboard.
    tap('touch')
    expect(dockIdle()).toBe(false)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })

  it('a mouse click on a hidden dock wakes the dock but leaves auto-hidden panels hidden', () => {
    setupTwoAutoHidePlugins()

    // A mouse click (pointerdown) wakes the dock only — panels stay hidden.
    tap('mouse')
    expect(dockIdle()).toBe(false)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })

  it('Escape on a hidden dock wakes the dock only, leaving auto-hidden panels hidden', () => {
    setupTwoAutoHidePlugins()

    // Escape on a hidden dock wakes the dock only (was a full wake()).
    escape()
    expect(dockIdle()).toBe(false)
    expect(isIdle('a')).toBe(true)
    expect(isIdle('b')).toBe(true)
  })
})

describe('OverlayShell — pause pins the dock (#783)', () => {
  function dockIdle(): boolean {
    return root.classList.contains('pf-root--dock-idle')
  }

  function toggleButton(): HTMLButtonElement | null {
    return document.querySelector<HTMLButtonElement>('.pf-dock-icon[data-dock-role="toggle"]')
  }

  /** Push a playback state through the worker JS bridge (the path
   * `overlay_worker.py` uses via `window.picframe.applyPlaybackState`). */
  function applyPlaybackState(state: string): void {
    expect(window.picframe?.applyPlaybackState).toBeDefined()
    window.picframe!.applyPlaybackState!(state)
  }

  function bootPlugin(): void {
    const a = makePlugin('a')
    applyConfig({
      enabled: true,
      enabled_plugins: ['a'],
      visible_plugins: ['a'],
      idle_hide_seconds: 5,
      _plugins: [a]
    })
  }

  function escape(): void {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  }

  it('flips the toggle icon to Play when paused and back to Pause on resume', () => {
    bootPlugin()
    // The toggle icon is an inline SVG (font-independent): pause = <rect>,
    // play = <polygon>. Assert the SVG shape + aria-label rather than a glyph.
    const pauseIcon = toggleButton()!
    expect(pauseIcon.querySelector('svg')).not.toBeNull()
    expect(pauseIcon.innerHTML).toContain('<rect')
    expect(pauseIcon.getAttribute('aria-label')).toBe('Pause')
    applyPlaybackState('PAUSED')
    const playIcon = toggleButton()!
    expect(playIcon.innerHTML).toContain('<polygon')
    expect(playIcon.getAttribute('aria-label')).toBe('Play')
    applyPlaybackState('PLAYING')
    expect(toggleButton()!.innerHTML).toContain('<rect')
    expect(toggleButton()!.getAttribute('aria-label')).toBe('Pause')
  })

  it('pins the dock visible while paused (idle-hide is suppressed)', () => {
    bootPlugin()
    applyPlaybackState('PAUSED')
    expect(dockIdle()).toBe(false)
    // The idle-hide timer must NOT be armed while paused — advancing well past
    // the idle interval leaves the dock visible.
    vi.advanceTimersByTime(60000)
    expect(dockIdle()).toBe(false)
  })

  it('restores normal dock auto-hide on resume', () => {
    bootPlugin()
    applyPlaybackState('PAUSED')
    expect(dockIdle()).toBe(false)
    applyPlaybackState('PLAYING')
    // Resumed: the dock auto-hides again after the idle interval.
    expect(dockIdle()).toBe(false)
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)
  })

  it('reveals a hidden dock when it becomes paused', () => {
    bootPlugin()
    // Let the dock auto-hide first.
    vi.advanceTimersByTime(5000)
    expect(dockIdle()).toBe(true)
    applyPlaybackState('PAUSED')
    expect(dockIdle()).toBe(false)
  })

  it('does not dismiss the dock with Escape while paused', () => {
    bootPlugin()
    applyPlaybackState('PAUSED')
    expect(dockIdle()).toBe(false)
    // Escape normally dismisses the dock; while paused the pin wins so the
    // paused state keeps an on-screen indicator.
    escape()
    expect(dockIdle()).toBe(false)
  })

  it('lets Escape dismiss the dock again after resume', () => {
    bootPlugin()
    applyPlaybackState('PAUSED')
    applyPlaybackState('PLAYING')
    escape()
    expect(dockIdle()).toBe(true)
  })

  it('does not pin the dock for an already-paused repeat state', () => {
    bootPlugin()
    applyPlaybackState('PAUSED')
    vi.advanceTimersByTime(60000)
    expect(dockIdle()).toBe(false)
    // A duplicate PAUSED push must not re-arm a hide timer.
    applyPlaybackState('PAUSED')
    vi.advanceTimersByTime(60000)
    expect(dockIdle()).toBe(false)
  })
})
