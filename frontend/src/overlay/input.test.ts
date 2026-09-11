import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { InputRouter } from './input'

let root: HTMLElement
let onAction: ReturnType<typeof vi.fn>
let onActivity: ReturnType<typeof vi.fn>
let onHide: ReturnType<typeof vi.fn>

beforeEach(() => {
  root = document.createElement('div')
  document.body.appendChild(root)
  onAction = vi.fn()
  onActivity = vi.fn()
  onHide = vi.fn()
})

afterEach(() => {
  root.remove()
})

function makeRouter(
  enabledTypes: Array<'touch' | 'mouse' | 'keyboard'>,
  keyBindings?: Parameters<InputRouter['setKeyBindings']>[0],
  dockIdle?: () => boolean
): InputRouter {
  const router = new InputRouter({
    root,
    enabledTypes,
    onAction,
    onHide,
    onActivity,
    dockIdle
  })
  if (keyBindings) router.setKeyBindings(keyBindings)
  return router
}

function dispatchPointer(pointerType: string): void {
  root.dispatchEvent(new PointerEvent('pointerdown', { pointerType }))
}

function dispatchKey(key: string): void {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
}

describe('InputRouter — pointer events', () => {
  it('calls onActivity with "mouse" for a mouse pointer', () => {
    const router = makeRouter(['mouse', 'touch', 'keyboard'])
    router.attach()
    dispatchPointer('mouse')
    expect(onActivity).toHaveBeenCalledWith('mouse')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })

  it('calls onActivity with "touch" for a touch pointer', () => {
    const router = makeRouter(['mouse', 'touch', 'keyboard'])
    router.attach()
    dispatchPointer('touch')
    expect(onActivity).toHaveBeenCalledWith('touch')
    router.detach()
  })

  it('maps pen to touch', () => {
    const router = makeRouter(['mouse', 'touch', 'keyboard'])
    router.attach()
    dispatchPointer('pen')
    expect(onActivity).toHaveBeenCalledWith('touch')
    router.detach()
  })

  it('ignores a pointer type that is not enabled', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchPointer('mouse')
    expect(onActivity).not.toHaveBeenCalled()
    router.detach()
  })

  it('does not fire onAction on pointer tap (navigation is via dock, #763)', () => {
    const router = makeRouter(['mouse', 'touch', 'keyboard'])
    router.attach()
    dispatchPointer('touch')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })
})

describe('InputRouter — keyboard events (default key bindings, #777)', () => {
  it('maps ArrowLeft to prev', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('ArrowLeft')
    expect(onAction).toHaveBeenCalledWith('prev')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    router.detach()
  })

  it('maps ArrowRight to next', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('ArrowRight')
    expect(onAction).toHaveBeenCalledWith('next')
    router.detach()
  })

  it('maps p (default) to toggle', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('p')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.detach()
  })

  it('matches single letters case-insensitively', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('P')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.detach()
  })

  it('wakes the dock on an unmapped key but fires no action (#780)', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('a')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })

  it('wakes the dock on an unmapped named key, e.g. F5 (#780)', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('F5')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })

  it('does nothing when keyboard is not enabled', () => {
    const router = makeRouter(['mouse', 'touch'])
    router.attach()
    dispatchKey('ArrowLeft')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })
})

describe('InputRouter — two-step wake-then-navigate (#780)', () => {
  it('only wakes (no action) on a bound key while the dock is idle', () => {
    const router = makeRouter(['keyboard'], undefined, () => true)
    router.attach()
    dispatchKey('ArrowRight')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })

  it('fires the action once the dock is visible (dockIdle false)', () => {
    const router = makeRouter(['keyboard'], undefined, () => false)
    router.attach()
    dispatchKey('ArrowRight')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).toHaveBeenCalledWith('next')
    router.detach()
  })

  it('wakes-then-navigates across two presses as the dock becomes visible', () => {
    let idle = true
    const router = makeRouter(['keyboard'], undefined, () => idle)
    router.attach()
    // First press on a hidden dock: wake only.
    dispatchKey('ArrowLeft')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    // The wake reveals the dock; the shell flips the idle flag off.
    idle = false
    // Second press (dock now visible): the action fires.
    dispatchKey('ArrowLeft')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).toHaveBeenCalledWith('prev')
    router.detach()
  })

  it('still only wakes for an unmapped key regardless of dock state', () => {
    const router = makeRouter(['keyboard'], undefined, () => true)
    router.attach()
    dispatchKey('a')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })
})

describe('InputRouter — reserved keys (#777, #780)', () => {
  it('wakes on Enter but lets native <button> activation win (#780)', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('Enter')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    expect(onHide).not.toHaveBeenCalled()
    router.detach()
  })

  it('wakes on Space but lets native <button> activation win (#780)', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey(' ')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    expect(onHide).not.toHaveBeenCalled()
    router.detach()
  })

  it('wakes on Tab but lets native focus movement win (#780)', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('Tab')
    expect(onActivity).toHaveBeenCalledWith('keyboard')
    expect(onAction).not.toHaveBeenCalled()
    expect(onHide).not.toHaveBeenCalled()
    router.detach()
  })

  it('ignores reserved keys even when a hand-edited config lists them', () => {
    // Defense in depth: a config.db3 that puts Enter/Tab/Escape in key_bindings
    // is ignored by setKeyBindings, so native activation/navigation still works.
    const router = makeRouter(['keyboard'], {
      prev: ['Enter'],
      next: ['Tab'],
      toggle: [' ', 'Escape']
    })
    router.attach()
    dispatchKey('Enter')
    dispatchKey('Tab')
    dispatchKey(' ')
    // Reserved keys still wake the dock (3 key actions) but never fire actions.
    expect(onActivity).toHaveBeenCalledTimes(3)
    expect(onAction).not.toHaveBeenCalled()
    expect(onHide).not.toHaveBeenCalled()
    router.detach()
  })
})

describe('InputRouter — Escape -> onHide (#777, #780)', () => {
  it('fires onHide for Escape and does not count it as wake activity', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('Escape')
    expect(onHide).toHaveBeenCalledTimes(1)
    expect(onActivity).not.toHaveBeenCalled()
    expect(onAction).not.toHaveBeenCalled()
    router.detach()
  })

  it('fires onHide for Escape regardless of key_bindings', () => {
    const router = makeRouter(['keyboard'], { toggle: ['x'] })
    router.attach()
    dispatchKey('Escape')
    expect(onHide).toHaveBeenCalledTimes(1)
    router.detach()
  })

  it('does nothing on Escape when keyboard is not enabled', () => {
    const router = makeRouter(['mouse', 'touch'])
    router.attach()
    dispatchKey('Escape')
    expect(onHide).not.toHaveBeenCalled()
    router.detach()
  })
})

describe('InputRouter — configurable key bindings (#777)', () => {
  it('uses a custom key for an action', () => {
    const router = makeRouter(['keyboard'], { prev: ['q'], next: ['w'], toggle: ['e'] })
    router.attach()
    dispatchKey('q')
    expect(onAction).toHaveBeenCalledWith('prev')
    dispatchKey('w')
    expect(onAction).toHaveBeenCalledWith('next')
    dispatchKey('e')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.detach()
  })

  it('binds several keys to one action', () => {
    const router = makeRouter(['keyboard'], { toggle: ['p', 't'] })
    router.attach()
    dispatchKey('p')
    dispatchKey('t')
    expect(onAction).toHaveBeenCalledWith('toggle')
    expect(onAction).toHaveBeenCalledTimes(2)
    router.detach()
  })

  it('live-updates via setKeyBindings', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('p')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.setKeyBindings({ toggle: ['x'] })
    dispatchKey('p')
    expect(onAction).toHaveBeenCalledTimes(1) // no new toggle from old key
    dispatchKey('x')
    expect(onAction).toHaveBeenLastCalledWith('toggle')
    router.detach()
  })

  it('falls back to defaults when key_bindings is empty', () => {
    const router = makeRouter(['keyboard'], {})
    router.attach()
    dispatchKey('ArrowLeft')
    expect(onAction).toHaveBeenCalledWith('prev')
    dispatchKey('p')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.detach()
  })
})

describe('InputRouter — dynamic config and detach', () => {
  it('setEnabledTypes live-updates which inputs are honoured', () => {
    const router = makeRouter(['mouse'])
    router.attach()
    // keyboard disabled initially
    dispatchKey('ArrowLeft')
    expect(onAction).not.toHaveBeenCalled()

    // enable keyboard
    router.setEnabledTypes(['mouse', 'keyboard'])
    dispatchKey('ArrowLeft')
    expect(onAction).toHaveBeenCalledWith('prev')
    router.detach()
  })

  it('detach removes listeners so events are no longer captured', () => {
    const router = makeRouter(['mouse', 'touch', 'keyboard'])
    router.attach()
    router.detach()
    dispatchPointer('mouse')
    dispatchKey('ArrowLeft')
    dispatchKey('Escape')
    expect(onActivity).not.toHaveBeenCalled()
    expect(onAction).not.toHaveBeenCalled()
    expect(onHide).not.toHaveBeenCalled()
  })
})
