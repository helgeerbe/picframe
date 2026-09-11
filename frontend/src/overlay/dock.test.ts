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
describe('Dock focusout safety net (#781)', () => {
  /** A focusable element appended to <body> (outside `#pf-dock`) standing in
   *  for GTK4 moving focus out of the webview despite the keydown trap's
   *  preventDefault. happy-dom does not fire `focusout` on programmatic
   *  `focus()`, so the escape is simulated by dispatching a `FocusEvent` with
   *  this element as `relatedTarget`. */
  function outsideButton(): HTMLButtonElement {
    const el = document.createElement('button')
    el.id = 'pf-test-outside'
    document.body.appendChild(el)
    return el
  }

  /** Dispatch a `focusout` on `el` with `related` as the focus destination.
   *  `bubbles: true` so it reaches the dock's delegated listener. */
  function focusout(el: HTMLElement, related: EventTarget | null): void {
    el.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: related }))
  }

  /** A middle dock button (toggle) used to arm the Tab-direction flag without
   *  the keydown trap pre-wrapping in happy-dom: `tab()` on a middle button
   *  runs `setTabDirection` but, being neither first nor last, calls no
   *  `focus()`, so the safety net's wrap is observable — focus actually moves
   *  from the middle button to the wrap target. */
  function middleButton(): HTMLButtonElement {
    return icons()[1]
  }

  it('wraps focus back to the last icon when Shift+Tab escapes the dock', () => {
    apply()
    const btns = icons()
    const middle = middleButton()
    middle.focus()
    tab(true) // arms 'backward' (middle button → trap does not pre-wrap)
    const outside = outsideButton()
    focusout(middle, outside) // GTK4 moved focus out despite preventDefault
    expect(document.activeElement).toBe(btns[btns.length - 1])
    outside.remove()
  })

  it('wraps focus back to the first icon when Tab escapes the dock', () => {
    apply()
    const btns = icons()
    const middle = middleButton()
    middle.focus()
    tab(false) // arms 'forward'
    const outside = outsideButton()
    focusout(middle, outside)
    expect(document.activeElement).toBe(btns[0])
    outside.remove()
  })

  it('does not wrap for an intra-dock focus move (relatedTarget inside dock)', () => {
    apply()
    const btns = icons()
    const middle = middleButton()
    middle.focus()
    tab(true) // arms 'backward'
    // The new target is still inside the dock (the trap's own wrap, or native
    // Tab between dock buttons) → the safety net must not interfere.
    focusout(middle, btns[0])
    expect(document.activeElement).toBe(middle)
  })

  it('does not wrap when no Tab preceded the focus escape', () => {
    apply()
    const middle = middleButton()
    middle.focus()
    // No tab() → direction flag is null → safety net stays idle.
    const outside = outsideButton()
    focusout(middle, outside)
    expect(document.activeElement).toBe(middle)
    outside.remove()
  })

  it('resets the Tab direction after the macrotask so a later escape does not wrap', async () => {
    apply()
    const middle = middleButton()
    middle.focus()
    tab(true) // arms 'backward'
    // Flush the setTimeout(0) reset so the direction flag is cleared.
    await new Promise<void>(r => setTimeout(r, 0))
    const outside = outsideButton()
    focusout(middle, outside) // flag is null now → no wrap
    expect(document.activeElement).toBe(middle)
    outside.remove()
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
})
