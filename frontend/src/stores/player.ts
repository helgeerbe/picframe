import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface MediaItem {
  id?: number | null
  file_path: string
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
  const brightness = ref(1.0)
  const isDisplayOn = ref(true)
  const isConnected = ref(false)
  const systemError = ref<{message: string, component: string} | null>(null)

  let ws: WebSocket | null = null

  function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    // In development, connect to the FastAPI backend port (e.g., 9000)
    const wsUrl = import.meta.env.DEV 
      ? `ws://${window.location.hostname}:9000/ws/state`
      : `${protocol}//${host}/ws/state`

    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      isConnected.value = true
      console.log('WebSocket connected')
      // Request initial state upon connection
      sendCommand('REQUEST_STATE')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'MediaChangedEvent') {
          currentMedia.value = normalizeMediaUrls(data.media)
        } else if (data.type === 'StateEvent') {
          if (data.state === 'PLAYING') isPlaying.value = true
          if (data.state === 'PAUSED') isPlaying.value = false
        } else if (data.type === 'SystemErrorEvent') {
          systemError.value = {
            message: data.message,
            component: data.component
          }
          // Auto-clear error after 10 seconds
          setTimeout(() => {
            if (systemError.value?.message === data.message) {
              systemError.value = null
            }
          }, 10000)
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message', e)
      }
    }

    ws.onclose = () => {
      isConnected.value = false
      console.log('WebSocket disconnected, retrying in 5s...')
      setTimeout(connect, 5000)
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      ws?.close()
    }
  }

  function sendCommand(command: string, payload?: any) {
    if (ws && isConnected.value) {
      ws.send(JSON.stringify({ command, ...payload }))
    } else {
      console.warn('Cannot send command, WebSocket not connected')
    }
  }

  function normalizeMediaUrls(media: MediaItem): MediaItem {
    const normalized = { ...media }
    normalized.file_path = normalizeMediaUrl(normalized.file_path)
    if (Array.isArray(normalized.items)) {
      normalized.items = normalized.items.map((item) => normalizeMediaUrls(item))
    }
    return normalized
  }

  function normalizeMediaUrl(path: string) {
    if (!path || path.startsWith('http') || path.startsWith('/media?path=')) {
      return path
    }

    const port = import.meta.env.DEV ? '9000' : window.location.port || (window.location.protocol === 'https:' ? '443' : '80')
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

  function setBrightness(value: number) {
    brightness.value = value
    sendCommand('SET_BRIGHTNESS', { value })
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
    brightness,
    isConnected,
    systemError,
    connect,
    sendCommand,
    play,
    pause,
    next,
    previous,
    setBrightness,
    isDisplayOn,
    toggleDisplayPower,
    clearError
  }
})
