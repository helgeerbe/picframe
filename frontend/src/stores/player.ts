import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

export type ConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'offline'

export interface MediaItem {
  id?: number | null
  file_path: string
  media_type?: 'image' | 'video' | string
  // EXIF is an open-ended metadata blob accessed at arbitrary keys by RemoteView;
  // keep dynamic `any` rather than cascading `unknown` casts through the template.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  exif?: Record<string, any>
  location?: {
    lat: number
    lon: number
  }
  role?: string | null
  index?: number | null
  layout?: 'single' | 'portrait_pair' | string
  primary_index?: number
  items?: MediaItem[]
}

export const usePlayerStore = defineStore('player', () => {
  const currentMedia = ref<MediaItem | null>(null)
  const isPlaying = ref(false)
  const playbackState = ref('IDLE')
  const brightness = ref(1.0)
  const isDisplayOn = ref(true)
  const connectionStatus = ref<ConnectionStatus>('offline')
  const isConnected = computed(() => connectionStatus.value === 'connected')
  const systemError = ref<{
    message: string
    component: string
    sticky?: boolean
    code?: string | null
  } | null>(null)

  let ws: WebSocket | null = null
  let reconnectTimer: number | null = null
  const reconnectDelayMs = 5000
  let heartbeatTimer: number | null = null
  let lastMessageAt = 0
  const heartbeatIntervalMs = 10000
  const staleConnectionMs = 25000

  function connect() {
    if (ws?.readyState === WebSocket.OPEN || ws?.readyState === WebSocket.CONNECTING) {
      return
    }
    if (reconnectTimer !== null) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    // In development, connect to the FastAPI backend port (e.g., 9000)
    const wsUrl = import.meta.env.DEV
      ? `ws://${window.location.hostname}:9000/ws/state`
      : `${protocol}//${host}/ws/state`

    connectionStatus.value =
      connectionStatus.value === 'reconnecting' ? 'reconnecting' : 'connecting'
    const socket = new WebSocket(wsUrl)
    ws = socket

    socket.onopen = () => {
      if (ws !== socket) return
      connectionStatus.value = 'connected'
      lastMessageAt = Date.now()
      startHeartbeat()

      // Request initial state upon connection
      sendCommand('REQUEST_STATE')
    }

    socket.onmessage = event => {
      if (ws !== socket) return
      lastMessageAt = Date.now()
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'MediaChangedEvent') {
          currentMedia.value = normalizeMediaUrls(data.media)
        } else if (data.type === 'StateEvent') {
          playbackState.value = data.state
          isPlaying.value = ['PLAYING', 'TRANSITIONING', 'PREPARING_VIDEO'].includes(data.state)
          if (data.state === 'ERROR') {
            isPlaying.value = false
            if (data.payload?.reason === 'invalid_renderer_config') {
              systemError.value = {
                message: data.payload.message,
                component: data.payload.component || 'Pi3dRenderer',
                sticky: true,
                code: data.payload.reason
              }
            }
          }
          if (data.state === 'PLAYING' && systemError.value?.code === 'invalid_renderer_config') {
            systemError.value = null
          }
        } else if (data.type === 'SystemErrorEvent') {
          systemError.value = {
            message: data.message,
            component: data.component,
            sticky: data.sticky,
            code: data.code
          }
          if (!data.sticky) {
            setTimeout(() => {
              if (systemError.value?.message === data.message) {
                systemError.value = null
              }
            }, 10000)
          }
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message', e)
      }
    }

    socket.onclose = () => {
      if (ws !== socket) return
      ws = null
      stopHeartbeat()

      scheduleReconnect()
    }

    socket.onerror = error => {
      if (ws !== socket) return
      connectionStatus.value = 'offline'
      console.error('WebSocket error:', error)
      socket.close()
    }
  }

  function startHeartbeat() {
    stopHeartbeat()
    heartbeatTimer = window.setInterval(() => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        connectionStatus.value = 'reconnecting'
        stopHeartbeat()
        scheduleReconnect()
        return
      }
      if (Date.now() - lastMessageAt > staleConnectionMs) {
        connectionStatus.value = 'reconnecting'
        ws.close()
        return
      }
      sendCommand('REQUEST_STATE')
    }, heartbeatIntervalMs)
  }

  function stopHeartbeat() {
    if (heartbeatTimer === null) return
    window.clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }

  function scheduleReconnect() {
    if (reconnectTimer !== null) {
      return
    }
    connectionStatus.value = 'reconnecting'
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null
      connect()
    }, reconnectDelayMs)
  }

  function sendCommand(command: string, payload?: Record<string, unknown>): boolean {
    if (ws && isConnected.value && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ command, ...payload }))
        return true
      } catch (error) {
        console.warn('WebSocket send failed, reconnecting', error)
        connectionStatus.value = 'reconnecting'
        ws.close()
        scheduleReconnect()
        return false
      }
    }
    console.warn('Cannot send command, WebSocket not connected')
    return false
  }

  function normalizeMediaUrls(media: MediaItem): MediaItem {
    const normalized = { ...media }
    normalized.file_path = normalizeMediaUrl(normalized.file_path)
    if (Array.isArray(normalized.items)) {
      normalized.items = normalized.items.map(item => normalizeMediaUrls(item))
    }
    return normalized
  }

  function normalizeMediaUrl(path: string) {
    if (!path || path.startsWith('http') || path.startsWith('/media?path=')) {
      return path
    }

    const port = import.meta.env.DEV
      ? '9000'
      : window.location.port || (window.location.protocol === 'https:' ? '443' : '80')
    const host = window.location.hostname
    const protocol = window.location.protocol
    const mediaUrl = `/media?path=${encodeURIComponent(path)}`

    if (import.meta.env.DEV) {
      return `http://${host}:9000${mediaUrl}`
    }
    return `${protocol}//${host}${port ? ':' + port : ''}${mediaUrl}`
  }

  function play() {
    sendCommand('PLAY')
  }

  function pause() {
    sendCommand('PAUSE')
  }

  function next() {
    sendCommand('NEXT')
  }

  function previous() {
    sendCommand('PREV')
  }

  function normalizeBrightness(value: number) {
    if (!Number.isFinite(value)) return brightness.value
    return Math.max(0, Math.min(1, value))
  }

  function previewBrightness(value: number) {
    brightness.value = normalizeBrightness(value)
  }

  function setBrightness(value: number) {
    const nextValue = normalizeBrightness(value)
    brightness.value = nextValue
    sendCommand('SET_BRIGHTNESS', { value: nextValue })
  }

  function toggleDisplayPower() {
    isDisplayOn.value = !isDisplayOn.value
    sendCommand(isDisplayOn.value ? 'DISPLAY_ON' : 'DISPLAY_OFF')
  }

  function clearError() {
    systemError.value = null
  }

  return {
    currentMedia,
    isPlaying,
    playbackState,
    brightness,
    isConnected,
    connectionStatus,
    systemError,
    connect,
    sendCommand,
    play,
    pause,
    next,
    previous,
    previewBrightness,
    setBrightness,
    isDisplayOn,
    toggleDisplayPower,
    clearError
  }
})
