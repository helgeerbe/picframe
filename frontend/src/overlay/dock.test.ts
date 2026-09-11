import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { Dock } from './dock'
import type { DockCallbacks } from './dock'
import type { OverlayShellConfig, PluginEntry } from './types'

/**
 * Dock keyboard-navigation tests (#777): the delegated Tab-wrap focus trap on
 * `#pf-dock` and focus restoration across `render()`'s `replaceChildren`.
 *
 * The dock is driven directly (not via the shell JS bridge) so the assertions
 * isolate the dock's own DOM/listener behavior. `happy-dom` synthetic
 * `KeyboardEvent`s do not run the browser's default Tab focus-move, so the
 * wrap tests rely on the handler's explicit `.focus()` call; the middle-button
 * test asserts the handler does *not* wrap (focus stays put).
 */

let dockRoot: HTMLElement
let content: HTMLElement
let dock: Dock
const callbacks: DockCallbacks = {
  onVisiblePluginsChange: () => {},
  onOnScreenPluginsChange: () => {},
  onAction: () => {}
}

beforeEach(() => {
  content = document.createElement('div')
  content.id = 'pf-content'
  dockRoot = document.createElement('div')
  dockRoot.id = 'overlay-root'
  document.body.append(content, dockRoot)
  dock = new Dock(content, dockRoot, callbacks)
})

afterEach(() => {
  dock.destroy()
  dockRoot.remove()
  content.remove()
})

function makePlugin(id: string): PluginEntry {
  return {
    id,
    name: id,
    icon: '🖼',
    position: 'bottom-center',
    // about:blank avoids happy-dom's "file:" scheme fetch errors while still
    // mounting a real iframe (the src is irrelevant to the dock DOM/trap).
    entry_uri: 'about:blank'
  }
}

/** Apply a config; unspecified fields fall back to a two-plugin baseline. */
function apply(overrides: Partial<OverlayShellConfig> = {}): void {
  dock.applyConfig({
    enabled: true,
    enabled_plugins: ['a', 'b'],
    visible_plugins: ['a'],
    idle_hide_seconds: 5,
    _plugins: [makePlugin('a'), makePlugin('b')],
    ...overrides
  } as OverlayShellConfig)
}

function dockEl(): HTMLElement {
  return document.getElementById('pf-dock')!
}

function icons(): HTMLButtonElement[] {
  return Array.from(dockEl().querySelectorAll<HTMLButtonElement>('.pf-dock-icon'))
}

/** Dispatch a Tab (or Shift+Tab) keydown on the currently-focused element so it
 * bubbles to the dock's delegated listener. */
function tab(shift = false): void {
  document.activeElement?.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, shiftKey: shift })
  )
}

describe('Dock Tab-wrap focus trap (#777)', () => {
  it('wraps Tab from the last dock icon to the first', () => {
    apply()
    const btns = icons()
    // Dock row: prev | toggle | next | icon-a | icon-b | danger — last is the
    // danger trigger.
    btns[btns.length - 1].focus()
    expect(document.activeElement).toBe(btns[btns.length - 1])
    tab(false)
    expect(document.activeElement).toBe(btns[0])
  })

  it('wraps Shift+Tab from the first dock icon to the last', () => {
    apply()
    const btns = icons()
    btns[0].focus()
    tab(true)
    expect(document.activeElement).toBe(btns[btns.length - 1])
  })

  it('does not wrap Tab from a middle button (native move, no forced wrap)', () => {
    apply()
    const btns = icons()
    // A middle button (toggle, index 1) — neither first nor last, so the trap
    // must not intercept. Synthetic Tab has no default action in happy-dom, so
    // focus stays put; the assertion is that the handler did not wrap.
    btns[1].focus()
    tab(false)
    expect(document.activeElement).toBe(btns[1])
  })

  it('keeps focus inside #pf-dock after Tab on the last icon', () => {
    apply()
    const btns = icons()
    btns[btns.length - 1].focus()
    tab(false)
    expect(dockEl().contains(document.activeElement)).toBe(true)
  })

  it('survives a re-render: the trap still wraps after replaceChildren', () => {
    apply()
    // Re-apply to force a rebuild (new #pf-dock children, same dock element).
    apply()
    const btns = icons()
    btns[btns.length - 1].focus()
    tab(false)
    expect(document.activeElement).toBe(btns[0])
  })
})

describe('Dock focus restoration across re-render (#777)', () => {
  it('restores focus to the rebuilt plugin icon after a config push', () => {
    apply()
    const pluginIcon = dockEl().querySelector<HTMLButtonElement>(
      '.pf-dock-icon[data-plugin-id="a"]'
    )!
    pluginIcon.focus()
    expect(document.activeElement).toBe(pluginIcon)
    // Re-apply (triggers render() with replaceChildren).
    apply()
    const rebuilt = dockEl().querySelector<HTMLButtonElement>('.pf-dock-icon[data-plugin-id="a"]')!
    expect(rebuilt).not.toBe(pluginIcon) // a brand-new node
    expect(document.activeElement).toBe(rebuilt)
  })

  it('restores focus to the rebuilt transport button by data-dock-role', () => {
    apply()
    const toggle = dockEl().querySelector<HTMLButtonElement>(
      '.pf-dock-icon[data-dock-role="toggle"]'
    )!
    toggle.focus()
    apply()
    const rebuilt = dockEl().querySelector<HTMLButtonElement>(
      '.pf-dock-icon[data-dock-role="toggle"]'
    )!
    expect(rebuilt).not.toBe(toggle)
    expect(document.activeElement).toBe(rebuilt)
  })

  it('does not throw when the focused plugin is removed by the new config', () => {
    apply()
    const pluginIcon = dockEl().querySelector<HTMLButtonElement>(
      '.pf-dock-icon[data-plugin-id="a"]'
    )!
    pluginIcon.focus()
    // Disable 'a' and drop it from the plugin list in the next push.
    apply({ enabled_plugins: ['b'], visible_plugins: ['b'], _plugins: [makePlugin('b')] })
    expect(dockEl().querySelector('.pf-dock-icon[data-plugin-id="a"]')).toBeNull()
    // No throw; focus simply falls back to <body> (no matching rebuilt button).
    expect(document.activeElement).toBe(document.body)
  })
})
describe('Dock backward-Shift+Tab sentinel (#781)', () => {
  /** Dispatch a `focusin` on the dock sentinel with `related` as the element
   *  that lost focus: the first dock icon for a backward Shift+Tab wrap, or
   *  `null` for a forward entry from outside the webview. `bubbles: true` so it
   *  reaches the sentinel's listener. */
  function sentinelFocusin(related: EventTarget | null): void {
    const sentinel = dockEl().querySelector<HTMLElement>('.pf-dock-sentinel')!
    sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: related }))
  }

  it('wraps to the last icon when backward Shift+Tab lands on the sentinel', () => {
    apply()
    const btns = icons()
    btns[0].focus()
    // Backward Shift+Tab from the first icon lands on the sentinel (the
    // previous DOM focusable) instead of escaping the webview; the sentinel
    // redirects to the last icon.
    sentinelFocusin(btns[0])
    expect(document.activeElement).toBe(btns[btns.length - 1])
  })

  it('focuses the first icon on forward entry from outside the webview', () => {
    apply()
    const btns = icons()
    // Focus arriving at the sentinel from <body>/null (forward entry) goes to
    // the first dock icon, not the last.
    sentinelFocusin(null)
    expect(document.activeElement).toBe(btns[0])
  })

  it('is a no-op when the dock has no focusable icons (no throw)', () => {
    apply()
    const sentinel = dockEl().querySelector<HTMLElement>('.pf-dock-sentinel')!
    // Strip every dock icon so the handler's empty-guard is exercised; the
    // sentinel must not throw or strand focus on itself.
    dockEl()
      .querySelectorAll('.pf-dock-icon')
      .forEach(el => el.remove())
    expect(() => sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true }))).not.toThrow()
    expect(document.activeElement).not.toBe(sentinel)
  })

  it('survives a re-render: the sentinel still wraps after replaceChildren', () => {
    apply()
    apply() // force a rebuild (new #pf-dock children, same sentinel node)
    const btns = icons()
    btns[0].focus()
    sentinelFocusin(btns[0])
    expect(document.activeElement).toBe(btns[btns.length - 1])
  })
})

describe('Danger dropdown keyboard navigation (#777)', () => {
  /** Click the danger (power) trigger to open the dropdown. */
  function openDanger(): HTMLButtonElement {
    const trigger = dockEl().querySelector<HTMLButtonElement>('.pf-dock-danger')!
    trigger.click()
    return trigger
  }

  /** All menu items in the currently-open danger dropdown. */
  function dangerItems(): HTMLButtonElement[] {
    return Array.from(dockRoot.querySelectorAll<HTMLButtonElement>('.pf-danger-item'))
  }

  /** Dispatch a keydown on the currently-focused element. `bubbles: true`
   *  ensures the event flows through the capture-phase window listener. */
  function keydown(key: string, shift = false): void {
    document.activeElement?.dispatchEvent(
      new KeyboardEvent('keydown', { key, bubbles: true, shiftKey: shift })
    )
  }

  it('focuses the first menu item on open', () => {
    apply()
    openDanger()
    const items = dangerItems()
    expect(items.length).toBeGreaterThan(0)
    expect(document.activeElement).toBe(items[0])
  })

  it('wraps Tab from the last menu item to the first', () => {
    apply()
    openDanger()
    const items = dangerItems()
    items[items.length - 1].focus()
    keydown('Tab')
    expect(document.activeElement).toBe(items[0])
  })

  it('wraps Shift+Tab from the first menu item to the last', () => {
    apply()
    openDanger()
    const items = dangerItems()
    items[0].focus()
    keydown('Tab', true)
    expect(document.activeElement).toBe(items[items.length - 1])
  })

  it('cycles items forward with ArrowDown (wraps last→first)', () => {
    apply()
    openDanger()
    const items = dangerItems()
    items[0].focus()
    keydown('ArrowDown')
    expect(document.activeElement).toBe(items[1])
    // Wrap from the last item back to the first.
    items[items.length - 1].focus()
    keydown('ArrowDown')
    expect(document.activeElement).toBe(items[0])
  })

  it('cycles items backward with ArrowUp (wraps first→last)', () => {
    apply()
    openDanger()
    const items = dangerItems()
    items[1].focus()
    keydown('ArrowUp')
    expect(document.activeElement).toBe(items[0])
    // Wrap from the first item back to the last.
    items[0].focus()
    keydown('ArrowUp')
    expect(document.activeElement).toBe(items[items.length - 1])
  })

  it('closes on Escape and refocuses the danger trigger', () => {
    apply()
    const trigger = openDanger()
    expect(dangerItems().length).toBeGreaterThan(0)
    keydown('Escape')
    expect(dangerItems()).toHaveLength(0)
    expect(document.activeElement).toBe(trigger)
  })

  it('does not wrap Tab to the first dock button when the menu is open', () => {
    apply()
    const btns = icons()
    const trigger = openDanger()
    // The trigger is the last dock icon — Tab on it would normally wrap to the
    // first dock button, but the dangerOpen guard lets Tab flow natively into
    // the menu instead. happy-dom does not perform the native focus-move, so
    // the assertion is that focus does NOT wrap to btns[0].
    expect(trigger).toBe(btns[btns.length - 1])
    trigger.focus()
    keydown('Tab')
    expect(document.activeElement).not.toBe(btns[0])
  })

  it('inserts a leading sentinel as the first dropdown child (#781)', () => {
    apply()
    openDanger()
    const dropdown = dockRoot.querySelector('#pf-danger-dropdown')!
    expect(dropdown.firstElementChild).toBeTruthy()
    expect(dropdown.firstElementChild!.classList.contains('pf-dropdown-sentinel')).toBe(true)
    expect(dropdown.firstElementChild!.getAttribute('tabindex')).toBe('0')
  })

  it('wraps to the last item when backward Shift+Tab lands on the sentinel', () => {
    apply()
    openDanger()
    const items = dangerItems()
    items[0].focus()
    // Backward Shift+Tab from the first item lands on the sentinel (the
    // previous DOM focusable) instead of escaping to the danger trigger; the
    // sentinel redirects to the last item.
    const sentinel = dockRoot.querySelector<HTMLElement>('.pf-dropdown-sentinel')!
    sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: items[0] }))
    expect(document.activeElement).toBe(items[items.length - 1])
  })

  it('focuses the first item on forward entry to the sentinel', () => {
    apply()
    openDanger()
    const items = dangerItems()
    // Focus arriving at the sentinel from the trigger/null (forward entry) goes
    // to the first menu item, not the last.
    const sentinel = dockRoot.querySelector<HTMLElement>('.pf-dropdown-sentinel')!
    sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: null }))
    expect(document.activeElement).toBe(items[0])
  })

  it('sentinel is removed when the dropdown closes', () => {
    apply()
    openDanger()
    expect(dockRoot.querySelector('.pf-dropdown-sentinel')).not.toBeNull()
    keydown('Escape')
    expect(dockRoot.querySelector('.pf-dropdown-sentinel')).toBeNull()
  })
})

describe('Confirm modal backward-Shift+Tab sentinel (#781)', () => {
  /** Open the danger dropdown then click the first item to bring up the confirm
   *  modal. Returns the Cancel/Confirm buttons inside the open modal. */
  function openConfirmModal(): { cancel: HTMLButtonElement; ok: HTMLButtonElement } {
    const trigger = dockEl().querySelector<HTMLButtonElement>('.pf-dock-danger')!
    trigger.click()
    const items = Array.from(dockRoot.querySelectorAll<HTMLButtonElement>('.pf-danger-item'))
    items[0].click()
    const cancel = dockRoot.querySelector<HTMLButtonElement>('.pf-confirm-cancel')!
    const ok = dockRoot.querySelector<HTMLButtonElement>('.pf-confirm-ok')!
    return { cancel, ok }
  }

  it('inserts a leading sentinel as the first modal child (#781)', () => {
    apply()
    openConfirmModal()
    const modal = dockRoot.querySelector('#pf-confirm-modal')!
    expect(modal.firstElementChild).toBeTruthy()
    expect(modal.firstElementChild!.classList.contains('pf-modal-sentinel')).toBe(true)
    expect(modal.firstElementChild!.getAttribute('tabindex')).toBe('0')
  })

  it('wraps to Confirm when backward Shift+Tab lands on the sentinel', () => {
    apply()
    const { cancel, ok } = openConfirmModal()
    cancel.focus()
    // Backward Shift+Tab from Cancel (the first focusable) lands on the sentinel
    // (the previous DOM focusable) instead of escaping the modal to whatever
    // precedes the backdrop; the sentinel redirects to Confirm (the last).
    const sentinel = dockRoot.querySelector<HTMLElement>('.pf-modal-sentinel')!
    sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: cancel }))
    expect(document.activeElement).toBe(ok)
  })

  it('focuses Cancel on forward entry to the sentinel', () => {
    apply()
    const { cancel, ok } = openConfirmModal()
    // Focus arriving at the sentinel from outside the modal (forward entry) goes
    // to Cancel (the first button), not Confirm (the last).
    const sentinel = dockRoot.querySelector<HTMLElement>('.pf-modal-sentinel')!
    sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: null }))
    expect(document.activeElement).toBe(cancel)
    expect(document.activeElement).not.toBe(ok)
  })

  it('is a no-op when the modal has no buttons (no throw)', () => {
    apply()
    openConfirmModal()
    const sentinel = dockRoot.querySelector<HTMLElement>('.pf-modal-sentinel')!
    // Strip the action buttons so the handler's empty-guard is exercised; the
    // sentinel must not throw or strand focus on itself.
    dockRoot.querySelectorAll('.pf-confirm-btn').forEach(el => el.remove())
    expect(() =>
      sentinel.dispatchEvent(new FocusEvent('focusin', { bubbles: true, relatedTarget: null }))
    ).not.toThrow()
  })

  it('sentinel is removed when the modal closes', () => {
    apply()
    openConfirmModal()
    expect(dockRoot.querySelector('.pf-modal-sentinel')).not.toBeNull()
    // Escape on the focused Cancel button closes the modal.
    const cancel = dockRoot.querySelector<HTMLButtonElement>('.pf-confirm-cancel')!
    cancel.focus()
    cancel.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(dockRoot.querySelector('.pf-modal-sentinel')).toBeNull()
    expect(dockRoot.querySelector('#pf-confirm-backdrop')).toBeNull()
  })
})

describe('Dock two-state Play/Pause toggle (#783)', () => {
  function toggle(): HTMLButtonElement {
    return dockEl().querySelector<HTMLButtonElement>('.pf-dock-icon[data-dock-role="toggle"]')!
  }

  /** The toggle icon is now an inline SVG (font-independent, `currentColor`),
   * so the assertions check the SVG shape (`<rect>` = pause, `<polygon>` =
   * play) rather than a bare Unicode glyph, plus the `aria-label` for the
   * semantic state. This proves both the visual icon and the label flip. */
  function expectPause(btn: HTMLButtonElement): void {
    expect(btn.querySelector('svg')).not.toBeNull()
    expect(btn.innerHTML).toContain('<rect')
    expect(btn.getAttribute('aria-label')).toBe('Pause')
  }

  function expectPlay(btn: HTMLButtonElement): void {
    expect(btn.querySelector('svg')).not.toBeNull()
    expect(btn.innerHTML).toContain('<polygon')
    expect(btn.getAttribute('aria-label')).toBe('Play')
  }

  it('shows the Pause icon while playing (default)', () => {
    apply()
    expectPause(toggle())
  })

  it('flips to the Play icon when paused', () => {
    apply()
    dock.setPlaybackState('PAUSED')
    expectPlay(toggle())
  })

  it('reverts to the Pause icon on resume', () => {
    apply()
    dock.setPlaybackState('PAUSED')
    dock.setPlaybackState('PLAYING')
    expectPause(toggle())
  })

  it('treats transitioning/preparing-video as playing', () => {
    apply()
    dock.setPlaybackState('TRANSITIONING')
    expectPause(toggle())
    dock.setPlaybackState('PREPARING_VIDEO')
    expectPause(toggle())
  })

  it('is a no-op when the state does not change', () => {
    apply()
    const before = toggle()
    // Same playing family -> no DOM change.
    dock.setPlaybackState('PLAYING')
    const after = toggle()
    expect(after).toBe(before)
    expectPause(after)
  })

  it('reflects the paused icon in the initial render after a state push', () => {
    apply()
    dock.setPlaybackState('PAUSED')
    // A subsequent config push rebuilds the dock; the rebuilt toggle must
    // reflect the paused state, not the default.
    apply()
    expectPlay(toggle())
  })
})
