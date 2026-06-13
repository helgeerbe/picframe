<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { usePlayerStore } from './stores/player'

const { t, locale } = useI18n()
const playerStore = usePlayerStore()

const toggleLocale = () => {
  locale.value = locale.value === 'en' ? 'de' : 'en'
}
</script>

<template>
  <div class="min-h-screen bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-100">
    <header class="bg-white dark:bg-gray-800 shadow">
      <nav class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div class="flex space-x-4">
          <RouterLink to="/" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.remote') }}</RouterLink>
          <RouterLink to="/filters" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.filters') }}</RouterLink>
          <RouterLink to="/settings" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.settings') }}</RouterLink>
          <RouterLink to="/logs" class="px-3 py-2 rounded-md text-sm font-medium hover:bg-gray-200 dark:hover:bg-gray-700" active-class="bg-gray-200 dark:bg-gray-700">{{ t('nav.logs') }}</RouterLink>
        </div>
        <div>
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
