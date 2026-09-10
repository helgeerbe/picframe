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
