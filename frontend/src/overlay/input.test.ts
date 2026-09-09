import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { InputRouter } from './input'

let root: HTMLElement
let onAction: ReturnType<typeof vi.fn>
let onActivity: ReturnType<typeof vi.fn>

beforeEach(() => {
  root = document.createElement('div')
  document.body.appendChild(root)
  onAction = vi.fn()
  onActivity = vi.fn()
})

afterEach(() => {
  root.remove()
})

function makeRouter(enabledTypes: Array<'touch' | 'mouse' | 'keyboard'>): InputRouter {
  return new InputRouter({ root, enabledTypes, onAction, onActivity })
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

describe('InputRouter — keyboard events', () => {
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

  it('maps Enter to toggle', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('Enter')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.detach()
  })

  it('maps Space to toggle', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey(' ')
    expect(onAction).toHaveBeenCalledWith('toggle')
    router.detach()
  })

  it('ignores an unmapped key', () => {
    const router = makeRouter(['keyboard'])
    router.attach()
    dispatchKey('a')
    expect(onAction).not.toHaveBeenCalled()
    expect(onActivity).not.toHaveBeenCalled()
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
    expect(onActivity).not.toHaveBeenCalled()
    expect(onAction).not.toHaveBeenCalled()
  })
})
