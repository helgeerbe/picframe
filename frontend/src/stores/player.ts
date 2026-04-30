import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface MediaItem {
  file_path: string
  exif?: Record<string, any>
  location?: {
    lat: number
    lon: number
  }
}

export const usePlayerStore = defineStore('player', () => {
  const currentMedia = ref<MediaItem | null>(null)
  const isPlaying = ref(false)
  const brightness = ref(1.0)
  const isDisplayOn = ref(true)
  const isConnected = ref(false)

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
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'MediaChangedEvent') {
          currentMedia.value = data.media
          // Always prepend the host/port if it's a relative path, not just in DEV
          // This ensures it works when served from the backend or a separate frontend server
          if (currentMedia.value?.file_path?.startsWith('/')) {
            const port = import.meta.env.DEV ? '9000' : window.location.port || (window.location.protocol === 'https:' ? '443' : '80')
            const host = window.location.hostname
            const protocol = window.location.protocol
            
            // If we're in DEV, we know the backend is on 9000.
            // If we're in PROD, the backend is serving the frontend, so we use the current origin.
            if (import.meta.env.DEV) {
              currentMedia.value.file_path = `http://${host}:9000${currentMedia.value.file_path}`
            } else {
              currentMedia.value.file_path = `${protocol}//${host}${port ? ':' + port : ''}${currentMedia.value.file_path}`
            }
          }
        } else if (data.type === 'StateEvent') {
          if (data.state === 'PLAYING') isPlaying.value = true
          if (data.state === 'PAUSED') isPlaying.value = false
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

  return {
    currentMedia,
    isPlaying,
    brightness,
    isConnected,
    connect,
    sendCommand,
    play,
    pause,
    next,
    previous,
    setBrightness,
    isDisplayOn,
    toggleDisplayPower
  }
})
