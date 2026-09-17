import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { usePlayerStore } from './player'

/**
 * Player store transport tests (#786). The store keeps a module-private
 * WebSocket handle, so `connect()` is driven through a fake `WebSocket`
 * constructor whose `onopen` we fire by hand. Window timers are stubbed so the
 * heartbeat/reconnect schedulers never leak out of the test.
 */
class FakeWebSocket {
  static readonly OPEN = 1
  static readonly CONNECTING = 0
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  readyState = 1
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  onclose: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  constructor(_url: string) {
    instances.push(this)
  }
}

let instances: FakeWebSocket[]

beforeEach(() => {
  setActivePinia(createPinia())
  instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
  vi.stubGlobal(
    'setInterval',
    vi.fn(() => 0)
  )
  vi.stubGlobal('clearInterval', vi.fn())
  vi.stubGlobal(
    'setTimeout',
    vi.fn(() => 0)
  )
  vi.stubGlobal('clearTimeout', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('player store — restartPlaylist (#786)', () => {
  it('sends a RESTART_PLAYLIST command over the websocket', () => {
    const store = usePlayerStore()
    store.connect()
    // Fire the open handshake the browser would dispatch after connect().
    instances[0].onopen?.(new Event('open'))

    store.restartPlaylist()

    expect(store.sendCommand).toBeDefined()
    expect(instances[0].send).toHaveBeenCalledWith(JSON.stringify({ command: 'RESTART_PLAYLIST' }))
  })

  it('adapts no payload — restartPlaylist issues only the command token', () => {
    const store = usePlayerStore()
    store.connect()
    instances[0].onopen?.(new Event('open'))
    instances[0].send.mockClear()

    store.restartPlaylist()

    expect(instances[0].send).toHaveBeenCalledTimes(1)
    const payload = JSON.parse(instances[0].send.mock.calls[0][0] as string)
    expect(payload).toEqual({ command: 'RESTART_PLAYLIST' })
  })
})
