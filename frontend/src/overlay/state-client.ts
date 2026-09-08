/**
 * Best-effort client for the picframe `/ws/state` WebSocket (#739).
 *
 * The overlay shell connects itself so plugins (clock, meta) can react to live
 * media/state. Because the shell is loaded via `file://`, this is a
 * cross-origin WebSocket to `ws://localhost:<port>/ws/state` — the Phase-1
 * spike validates this works under labwc/Wayland. Until then the client is
 * strictly best-effort: connection failures and drops are swallowed and a
 * reconnect is scheduled, so the overlay never breaks the frame if the WS is
 * blocked.
 */

import type { CurrentMedia, StateMessage } from './types'

export interface StateClientCallbacks {
  onMedia?: (media: CurrentMedia) => void
  onState?: (state: string, payload?: unknown) => void
  onError?: (message: string, component: string) => void
}

const RECONNECT_DELAY_MS = 5000

export class StateClient {
  private ws: WebSocket | null = null
  private reconnectTimer: number | null = null
  private stopped = false
  private readonly wsPort: number
  private readonly callbacks: StateClientCallbacks

  constructor(wsPort: number, callbacks: StateClientCallbacks) {
    this.wsPort = wsPort
    this.callbacks = callbacks
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) {
      return
    }
    if (this.reconnectTimer !== null || this.stopped) return

    const url = `ws://localhost:${this.wsPort}/ws/state`
    let socket: WebSocket
    try {
      socket = new WebSocket(url)
    } catch (e) {
      console.warn('Overlay state WS constructor failed', e)
      this.scheduleReconnect()
      return
    }
    this.ws = socket

    socket.onopen = () => {
      try {
        socket.send(JSON.stringify({ command: 'REQUEST_STATE' }))
      } catch {
        /* ignore send race */
      }
    }

    socket.onmessage = event => {
      let data: unknown
      try {
        data = JSON.parse(event.data as string)
      } catch {
        return
      }
      this.dispatch(data as StateMessage)
    }

    socket.onerror = () => {
      // Cross-origin WS from file:// may be blocked until the spike lands.
      console.warn('Overlay state WS error; will reconnect.')
    }

    socket.onclose = () => {
      if (this.ws === socket) this.ws = null
      this.scheduleReconnect()
    }
  }

  private dispatch(msg: StateMessage): void {
    if (msg.type === 'MediaChangedEvent' && msg.media) {
      this.callbacks.onMedia?.(msg.media)
    } else if (msg.type === 'StateEvent') {
      this.callbacks.onState?.(msg.state, msg.payload)
    } else if (msg.type === 'SystemErrorEvent') {
      this.callbacks.onError?.(msg.message, msg.component)
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null || this.stopped) return
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, RECONNECT_DELAY_MS)
  }

  stop(): void {
    this.stopped = true
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onerror = null
      this.ws.onclose = null
      try {
        this.ws.close()
      } catch {
        /* ignore */
      }
      this.ws = null
    }
  }
}
