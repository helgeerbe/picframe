<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePlayerStore } from './stores/player'

const { t, locale } = useI18n()
const playerStore = usePlayerStore()

const toggleLocale = () => {
  locale.value = locale.value === 'en' ? 'de' : 'en'
}

onMounted(() => {
  playerStore.connect()
})

const connectionIndicator = computed(() => {
  switch (playerStore.connectionStatus) {
    case 'connected':
      return {
        label: t('connection.live'),
        title: t('connection.liveTitle'),
        containerClass: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
        dotClass: 'bg-emerald-500',
        pulse: false
      }
    case 'connecting':
      return {
        label: t('connection.connecting'),
        title: t('connection.connectingTitle'),
        containerClass: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
        dotClass: 'bg-amber-500',
        pulse: true
      }
    case 'reconnecting':
      return {
        label: t('connection.reconnecting'),
        title: t('connection.reconnectingTitle'),
        containerClass: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
        dotClass: 'bg-amber-500',
        pulse: true
      }
    default:
      return {
        label: t('connection.offline'),
        title: t('connection.offlineTitle'),
        containerClass: 'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300',
        dotClass: 'bg-red-500',
        pulse: false
      }
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
    <header class="bg-white dark:bg-gray-800 shadow">
      <nav class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div class="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto sm:gap-2">
          <RouterLink to="/" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.remote') }}</RouterLink>
          <RouterLink to="/filters" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.filters') }}</RouterLink>
          <RouterLink to="/settings" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.settings') }}</RouterLink>
          <RouterLink to="/logs" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.logs') }}</RouterLink>
        </div>
        <div class="ml-2 flex shrink-0 items-center gap-2">
          <div
            class="inline-flex h-9 min-w-9 items-center justify-center gap-2 rounded-full border px-2 text-xs font-semibold transition-colors sm:min-w-0 sm:px-3"
            :class="connectionIndicator.containerClass"
            :title="connectionIndicator.title"
            :aria-label="connectionIndicator.title"
            aria-live="polite"
          >
            <span
              class="h-2.5 w-2.5 rounded-full"
              :class="[connectionIndicator.dotClass, connectionIndicator.pulse ? 'animate-pulse' : '']"
            ></span>
            <span class="hidden sm:inline">{{ connectionIndicator.label }}</span>
          </div>
          <button @click="toggleLocale" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700 uppercase">
            {{ locale }}
          </button>
        </div>
      </nav>
    </header>

    <!-- Global Error Banner -->
    <div v-if="playerStore.systemError" class="bg-red-600 text-white px-4 py-3 shadow-md flex justify-between items-center">
      <div>
        <strong class="font-bold">System Error: </strong>
        <span class="block sm:inline">{{ playerStore.systemError.message }}</span>
      </div>
      <button @click="playerStore.systemError = null" class="text-white hover:text-gray-200 focus:outline-none">
        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <main class="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
      <RouterView />
    </main>
  </div>
</template>
