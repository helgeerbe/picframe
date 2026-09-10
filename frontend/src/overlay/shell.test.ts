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
