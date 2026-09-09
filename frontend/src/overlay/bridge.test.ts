import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { sendAction, setVisiblePlugins, setOnScreenPlugins } from './bridge'

beforeEach(() => {
  // Clean up any bridge left by a previous test
  window.picframe = undefined
})

afterEach(() => {
  window.picframe = undefined
})

describe('sendAction', () => {
  it('sends { action } when window.picframe.send exists', () => {
    const send = vi.fn()
    window.picframe = { send }
    sendAction('prev')
    expect(send).toHaveBeenCalledWith({ action: 'prev' })
  })

  it('catches a throw from send (does not propagate)', () => {
    const send = vi.fn(() => {
      throw new Error('bridge down')
    })
    window.picframe = { send }
    expect(() => sendAction('next')).not.toThrow()
    expect(send).toHaveBeenCalledWith({ action: 'next' })
  })

  it('creates a no-op bridge when window.picframe is absent', () => {
    // ensureBridge() creates a no-op send if window.picframe is undefined
    expect(() => sendAction('toggle')).not.toThrow()
    // After the call, window.picframe should exist with a no-op send
    expect(window.picframe).toBeDefined()
    expect(typeof window.picframe?.send).toBe('function')
  })
})

describe('setVisiblePlugins', () => {
  it('sends { action: "__set_visible_plugins", plugins: [...] }', () => {
    const send = vi.fn()
    window.picframe = { send }
    setVisiblePlugins(['clock', 'weather'])
    expect(send).toHaveBeenCalledWith({
      action: '__set_visible_plugins',
      plugins: ['clock', 'weather']
    })
  })

  it('catches a throw from send', () => {
    const send = vi.fn(() => {
      throw new Error('bridge down')
    })
    window.picframe = { send }
    expect(() => setVisiblePlugins(['clock'])).not.toThrow()
  })
})

describe('setOnScreenPlugins', () => {
  it('sends { action: "__set_on_screen_plugins", plugins: [...] }', () => {
    const send = vi.fn()
    window.picframe = { send }
    setOnScreenPlugins(['clock'])
    expect(send).toHaveBeenCalledWith({
      action: '__set_on_screen_plugins',
      plugins: ['clock']
    })
  })

  it('catches a throw from send', () => {
    const send = vi.fn(() => {
      throw new Error('bridge down')
    })
    window.picframe = { send }
    expect(() => setOnScreenPlugins([])).not.toThrow()
  })
})
