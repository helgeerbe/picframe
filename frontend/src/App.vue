<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { usePlayerStore } from './stores/player'
import StatusBanner from './components/ui/StatusBanner.vue'

const { t, locale } = useI18n()
const playerStore = usePlayerStore()

const toggleLocale = () => {
  locale.value = locale.value === 'en' ? 'de' : 'en'
}

const navItems = computed(() => [
  { to: '/', label: t('nav.remote'), shortLabel: t('nav.remote') },
  { to: '/appearance', label: t('nav.appearance'), shortLabel: t('nav.appearanceShort') },
  { to: '/settings', label: t('nav.settings'), shortLabel: t('nav.settings') },
  { to: '/logs', label: t('nav.logs'), shortLabel: t('nav.logs') }
])

onMounted(() => {
  playerStore.connect()
})

const connectionIndicator = computed(() => {
  switch (playerStore.connectionStatus) {
    case 'connected':
      return {
        label: t('connection.live'),
        title: t('connection.liveTitle'),
        containerClass:
          'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
        dotClass: 'bg-emerald-500',
        pulse: false
      }
    case 'connecting':
      return {
        label: t('connection.connecting'),
        title: t('connection.connectingTitle'),
        containerClass:
          'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
        dotClass: 'bg-amber-500',
        pulse: true
      }
    case 'reconnecting':
      return {
        label: t('connection.reconnecting'),
        title: t('connection.reconnectingTitle'),
        containerClass:
          'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
        dotClass: 'bg-amber-500',
        pulse: true
      }
    default:
      return {
        label: t('connection.offline'),
        title: t('connection.offlineTitle'),
        containerClass:
          'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300',
        dotClass: 'bg-red-500',
        pulse: false
      }
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-100 text-gray-950 dark:bg-gray-900 dark:text-gray-100">
    <header
      class="sticky top-0 z-40 border-b border-gray-200 bg-white/95 shadow-sm backdrop-blur dark:border-gray-800 dark:bg-gray-900/95"
    >
      <nav class="mx-auto flex max-w-7xl items-center gap-1.5 px-2 py-2 sm:gap-2 sm:px-6 lg:px-8">
        <div
          class="hide-scrollbar flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto sm:gap-1"
          :aria-label="t('nav.primary')"
        >
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="inline-flex h-9 flex-shrink-0 items-center whitespace-nowrap rounded-lg px-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-950 focus:outline-none focus:ring-2 focus:ring-sky-500/60 dark:text-gray-200 dark:hover:bg-gray-800 dark:hover:text-white sm:h-10 sm:px-3 sm:text-sm"
            active-class="bg-gray-200 text-gray-950 dark:bg-gray-800 dark:text-white"
          >
            <span class="sm:hidden">{{ item.shortLabel }}</span>
            <span class="hidden sm:inline">{{ item.label }}</span>
          </RouterLink>
        </div>
        <div class="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <div
            class="inline-flex h-8 min-w-8 items-center justify-center gap-2 rounded-full border px-2 text-xs font-semibold transition-colors sm:h-9 sm:min-w-9 sm:px-3"
            :class="connectionIndicator.containerClass"
            :title="connectionIndicator.title"
            :aria-label="connectionIndicator.title"
            aria-live="polite"
          >
            <span
              class="h-2.5 w-2.5 rounded-full"
              :class="[
                connectionIndicator.dotClass,
                connectionIndicator.pulse ? 'animate-pulse' : ''
              ]"
            ></span>
            <span class="hidden sm:inline">{{ connectionIndicator.label }}</span>
          </div>
          <button
            type="button"
            :aria-label="t('nav.toggleLanguage')"
            class="inline-flex h-9 items-center rounded-lg px-1 text-xs font-medium uppercase text-gray-700 hover:bg-gray-100 hover:text-gray-950 focus:outline-none focus:ring-2 focus:ring-sky-500/60 dark:text-gray-200 dark:hover:bg-gray-800 dark:hover:text-white sm:h-10 sm:px-3 sm:text-sm"
            @click="toggleLocale"
          >
            {{ locale }}
          </button>
        </div>
      </nav>
    </header>

    <div v-if="playerStore.systemError" class="mx-auto max-w-7xl px-3 pt-4 sm:px-6 lg:px-8">
      <StatusBanner
        tone="danger"
        :title="t('common.systemError')"
        :message="playerStore.systemError.message"
      >
        <template #actions>
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500/60 dark:border-red-500/30 dark:bg-gray-900 dark:text-red-200 dark:hover:bg-red-500/10"
            @click="playerStore.clearError()"
          >
            <XMarkIcon class="h-4 w-4" />
            {{ t('common.dismiss') }}
          </button>
        </template>
      </StatusBanner>
    </div>

    <main class="mx-auto max-w-7xl px-3 py-4 sm:px-6 sm:py-6 lg:px-8">
      <RouterView />
    </main>
  </div>
</template>
