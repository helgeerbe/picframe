<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import axios from 'axios'
import {
  ArrowDownTrayIcon,
  ArrowsPointingInIcon,
  ArrowsPointingOutIcon,
  ClipboardDocumentIcon,
  FunnelIcon,
  MagnifyingGlassIcon,
  PauseIcon,
  PlayIcon,
  TrashIcon
} from '@heroicons/vue/24/outline'

interface LogLine {
  timestamp: number
  level: string
  logger: string
  message: string
  formatted: string
}

const { t } = useI18n()
const levels = ['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']
const activeLevels = ref<string[]>(['CRITICAL', 'ERROR', 'WARNING', 'INFO'])
const searchText = ref('')
const isConnected = ref(false)
const autoScroll = ref(true)
const isPaused = ref(false)
const isExpanded = ref(false)
const authRequired = ref(false)
const lines = ref<LogLine[]>([])
const pendingLines = ref<LogLine[]>([])
const logRef = ref<HTMLElement | null>(null)
let ws: WebSocket | null = null
let reconnectTimer: number | undefined
let isUnmounted = false

const filteredLines = computed(() => {
  const query = searchText.value.trim()
  let matcher: ((line: LogLine) => boolean) | null = null
  if (query) {
    try {
      const regexp = new RegExp(query, 'i')
      matcher = (line) => regexp.test(line.formatted) || regexp.test(line.logger)
    } catch {
      const lowered = query.toLowerCase()
      matcher = (line) =>
        line.formatted.toLowerCase().includes(lowered) ||
        line.logger.toLowerCase().includes(lowered)
    }
  }
  return lines.value.filter((line) => {
    if (!activeLevels.value.includes(line.level)) return false
    return matcher ? matcher(line) : true
  })
})

const panelClass = computed(() => [
  'space-y-4 border bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90',
  isExpanded.value
    ? 'fixed inset-0 z-50 flex flex-col overflow-hidden rounded-none border-gray-200 shadow-2xl dark:bg-gray-900 sm:p-6'
    : 'rounded-lg border-gray-200'
])

const logOutputClass = computed(() => [
  'log-output overflow-scroll rounded-lg border border-slate-700 bg-slate-950 p-3 text-left font-mono text-xs leading-relaxed shadow-inner',
  isExpanded.value ? 'h-auto min-h-0 flex-1' : 'h-[60vh] min-h-[24rem]'
])

async function ensureLogAccess() {
  const apiBase = import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
  try {
    await axios.get(`${apiBase}/auth/config`)
    authRequired.value = false
    return true
  } catch (error) {
    console.error('Log access check failed', error)
    if (axios.isAxiosError(error) && error.response?.status === 401) {
      authRequired.value = true
      return false
    }
    return true
  }
}

async function startLogStream() {
  if (isUnmounted) return
  const hasAccess = await ensureLogAccess()
  if (hasAccess && !isUnmounted) {
    connect()
  }
}

function scheduleReconnect() {
  if (isUnmounted) return
  reconnectTimer = window.setTimeout(() => {
    void startLogStream()
  }, 3000)
}

function connect() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const wsUrl = import.meta.env.DEV
    ? `ws://${window.location.hostname}:9000/ws/logs`
    : `${protocol}//${host}/ws/logs`

  ws = new WebSocket(wsUrl)
  ws.onopen = () => {
    isConnected.value = true
    authRequired.value = false
  }
  ws.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'LogSnapshot') {
        const snapshot = Array.isArray(payload.events) ? payload.events : []
        lines.value = snapshot.map(normalizeLine)
        void scrollToBottom()
        return
      }
      if (payload.type === 'LogEvent') {
        appendLine(normalizeLine(payload))
      }
    } catch (error) {
      console.error('Failed to parse log event', error)
    }
  }
  ws.onclose = (event) => {
    isConnected.value = false
    if (event.code === 1008) {
      authRequired.value = true
      return
    }
    scheduleReconnect()
  }
  ws.onerror = () => {
    ws?.close()
  }
}

function normalizeLine(payload: Record<string, any>): LogLine {
  return {
    timestamp: Number(payload.timestamp || Date.now() / 1000),
    level: String(payload.level || 'INFO').toUpperCase(),
    logger: String(payload.logger || ''),
    message: String(payload.message || ''),
    formatted: String(payload.formatted || payload.message || '')
  }
}

function appendLine(line: LogLine) {
  if (isPaused.value) {
    pendingLines.value.push(line)
    if (pendingLines.value.length > 1000) {
      pendingLines.value.splice(0, pendingLines.value.length - 1000)
    }
    return
  }
  lines.value.push(line)
  if (lines.value.length > 1000) {
    lines.value.splice(0, lines.value.length - 1000)
  }
  void scrollToBottom()
}

async function scrollToBottom() {
  if (!autoScroll.value) return
  await nextTick()
  if (logRef.value) {
    logRef.value.scrollTop = logRef.value.scrollHeight
  }
}

function handleScroll() {
  if (!logRef.value) return
  const threshold = 24
  autoScroll.value =
    logRef.value.scrollTop + logRef.value.clientHeight >= logRef.value.scrollHeight - threshold
}

function togglePause() {
  isPaused.value = !isPaused.value
  if (!isPaused.value && pendingLines.value.length) {
    const nextLines = [...lines.value, ...pendingLines.value]
    lines.value = nextLines.slice(Math.max(0, nextLines.length - 1000))
    pendingLines.value = []
    void scrollToBottom()
  }
}

function toggleLevel(level: string) {
  if (activeLevels.value.includes(level)) {
    activeLevels.value = activeLevels.value.filter((item) => item !== level)
  } else {
    activeLevels.value = [...activeLevels.value, level]
  }
}

function clearLogs() {
  lines.value = []
  pendingLines.value = []
}

function toggleExpanded() {
  isExpanded.value = !isExpanded.value
  void scrollToBottom()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && isExpanded.value) {
    isExpanded.value = false
  }
}

function openLogAuth() {
  const path = import.meta.env.DEV ? `http://${window.location.hostname}:9000/logs` : '/logs'
  window.location.assign(path)
}

function serializeLines() {
  return filteredLines.value.map((line) => line.formatted).join('\n')
}

async function copyLogs() {
  await navigator.clipboard.writeText(serializeLines())
}

function downloadLogs() {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
  const blob = new Blob([serializeLines()], { type: 'text/plain' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `picframe-log-${timestamp}.txt`
  anchor.click()
  URL.revokeObjectURL(url)
}

function levelClass(level: string) {
  switch (level) {
    case 'CRITICAL':
    case 'ERROR':
      return 'text-red-300'
    case 'WARNING':
      return 'text-amber-300'
    case 'DEBUG':
      return 'text-sky-300'
    default:
      return 'text-emerald-300'
  }
}

onMounted(() => {
  isUnmounted = false
  void startLogStream()
  window.addEventListener('keydown', handleKeydown)
})

onBeforeUnmount(() => {
  isUnmounted = true
  if (reconnectTimer !== undefined) {
    window.clearTimeout(reconnectTimer)
  }
  ws?.close()
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-5 p-4 sm:p-6 lg:p-8">
    <div class="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
      <div>
        <h1 class="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">{{ t('logs.title') }}</h1>
        <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {{ isConnected ? t('logs.connected') : t('logs.disconnected') }}
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="togglePause">
          <PlayIcon v-if="isPaused" class="mr-2 h-4 w-4" />
          <PauseIcon v-else class="mr-2 h-4 w-4" />
          {{ isPaused ? t('logs.resume') : t('logs.pause') }}
        </button>
        <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="copyLogs">
          <ClipboardDocumentIcon class="mr-2 h-4 w-4" />
          {{ t('logs.copy') }}
        </button>
        <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="downloadLogs">
          <ArrowDownTrayIcon class="mr-2 h-4 w-4" />
          {{ t('logs.download') }}
        </button>
        <button type="button" class="inline-flex items-center rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700" @click="clearLogs">
          <TrashIcon class="mr-2 h-4 w-4" />
          {{ t('logs.clear') }}
        </button>
      </div>
    </div>

    <section :class="panelClass">
      <div v-if="isExpanded" class="flex flex-col justify-between gap-3 border-b border-gray-200 pb-4 dark:border-gray-700 sm:flex-row sm:items-center">
        <div>
          <h2 class="text-xl font-bold text-gray-900 dark:text-white">{{ t('logs.title') }}</h2>
          <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">
            {{ isConnected ? t('logs.connected') : t('logs.disconnected') }}
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="togglePause">
            <PlayIcon v-if="isPaused" class="mr-2 h-4 w-4" />
            <PauseIcon v-else class="mr-2 h-4 w-4" />
            {{ isPaused ? t('logs.resume') : t('logs.pause') }}
          </button>
          <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="copyLogs">
            <ClipboardDocumentIcon class="mr-2 h-4 w-4" />
            {{ t('logs.copy') }}
          </button>
          <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="downloadLogs">
            <ArrowDownTrayIcon class="mr-2 h-4 w-4" />
            {{ t('logs.download') }}
          </button>
          <button type="button" class="inline-flex items-center rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700" @click="clearLogs">
            <TrashIcon class="mr-2 h-4 w-4" />
            {{ t('logs.clear') }}
          </button>
          <button type="button" class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="toggleExpanded">
            <ArrowsPointingInIcon class="mr-2 h-4 w-4" />
            {{ t('logs.collapse') }}
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <label class="relative block">
          <MagnifyingGlassIcon class="pointer-events-none absolute left-3 top-2.5 h-5 w-5 text-gray-400" />
          <input v-model="searchText" type="search" :placeholder="t('logs.search')" class="block w-full rounded-lg border-gray-300 bg-white py-2 pl-10 pr-3 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
        </label>
        <div class="flex flex-wrap items-center gap-2">
          <FunnelIcon class="h-5 w-5 text-gray-400" />
          <button
            v-for="level in levels"
            :key="level"
            type="button"
            :class="[activeLevels.includes(level) ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200', 'rounded-md px-3 py-1.5 text-xs font-semibold transition-colors']"
            @click="toggleLevel(level)"
          >
            {{ level }}
          </button>
          <button v-if="!isExpanded" type="button" class="inline-flex items-center rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-semibold text-gray-700 shadow-sm hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="toggleExpanded">
            <ArrowsPointingOutIcon class="mr-2 h-4 w-4" />
            {{ t('logs.expand') }}
          </button>
        </div>
      </div>

      <div ref="logRef" :class="logOutputClass" @scroll="handleScroll">
        <div v-if="authRequired" class="flex min-h-full flex-col items-start justify-center gap-3 text-slate-200">
          <p class="whitespace-normal font-sans text-sm leading-6">{{ t('logs.authRequired') }}</p>
          <button type="button" class="rounded-md bg-indigo-600 px-3 py-2 font-sans text-sm font-semibold text-white hover:bg-indigo-500" @click="openLogAuth">
            {{ t('logs.authenticate') }}
          </button>
        </div>
        <div v-for="(line, index) in filteredLines" :key="`${line.timestamp}-${index}`" :class="['min-w-max whitespace-pre text-left', levelClass(line.level)]">
          {{ line.formatted }}
        </div>
      </div>

      <div class="flex flex-wrap items-center justify-between gap-3 text-sm text-gray-500 dark:text-gray-400">
        <p>{{ t('logs.lines', { count: filteredLines.length }) }}</p>
        <p v-if="pendingLines.length">{{ t('logs.pending', { count: pendingLines.length }) }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.log-output {
  scrollbar-color: #64748b #0f172a;
  scrollbar-width: auto;
}

.log-output::-webkit-scrollbar {
  height: 14px;
  width: 14px;
}

.log-output::-webkit-scrollbar-track {
  background: #0f172a;
  border-radius: 8px;
}

.log-output::-webkit-scrollbar-thumb {
  background: #64748b;
  border: 3px solid #0f172a;
  border-radius: 8px;
}

.log-output::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
