<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useConfigStore } from '../stores/config'
import { usePlayerStore } from '../stores/player'
import { useI18n } from 'vue-i18n'
import HelperText from './HelperText.vue'
import { AdjustmentsHorizontalIcon } from '@heroicons/vue/24/outline'

const configStore = useConfigStore()
const playerStore = usePlayerStore()
const { t } = useI18n()

const isLoading = ref(true)

const showClock = ref(false)
const showTitle = ref(false)
const showCaption = ref(false)
const showName = ref(false)
const showDate = ref(false)
const showFolder = ref(false)
const showLocation = ref(false)

const syncControlsFromConfig = () => {
  const viewerConfig = configStore.config?.viewer || {}
  showClock.value = !!viewerConfig.show_clock

  const showTextStr = (viewerConfig.text_overlay_format || '').toLowerCase()
  showTitle.value = showTextStr.includes('title')
  showCaption.value = showTextStr.includes('caption')
  showName.value = showTextStr.includes('name')
  showDate.value = showTextStr.includes('date')
  showFolder.value = showTextStr.includes('folder')
  showLocation.value = showTextStr.includes('location')
}

onMounted(async () => {
  if (!configStore.config || Object.keys(configStore.config).length === 0) {
    try {
      await configStore.fetchWorkflowConfig()
    } catch (e) {
      console.error("Failed to fetch config for overlays", e)
    }
  }
  syncControlsFromConfig()
  
  isLoading.value = false
})

const handleChange = () => {
  const textElements = []
  if (showTitle.value) textElements.push('title')
  if (showCaption.value) textElements.push('caption')
  if (showName.value) textElements.push('name')
  if (showDate.value) textElements.push('date')
  if (showFolder.value) textElements.push('folder')
  if (showLocation.value) textElements.push('location')
  
  const showTextStr = textElements.join(' ')
  
  const payload = {
    viewer: {
      show_clock: showClock.value,
      show_text_enabled: showTextStr.length > 0,
      text_overlay_format: showTextStr
    }
  }
  
  const sent = playerStore.sendCommand('SET_CONFIG', payload)
  if (!sent) {
    syncControlsFromConfig()
    return
  }
  
  // Update local config store to stay in sync
  if (configStore.config && configStore.config.viewer) {
    configStore.config.viewer.show_clock = showClock.value
    configStore.config.viewer.show_text_enabled = showTextStr.length > 0
    configStore.config.viewer.text_overlay_format = showTextStr
  }
}

const controls = [
  { id: 'clock', ref: showClock, labelKey: 'remote.overlays.clock', helperKey: 'remote.overlays.clockHelper' },
  { id: 'title', ref: showTitle, labelKey: 'remote.overlays.textTitle', helperKey: 'remote.overlays.textTitleHelper' },
  { id: 'caption', ref: showCaption, labelKey: 'remote.overlays.textCaption', helperKey: 'remote.overlays.textCaptionHelper' },
  { id: 'name', ref: showName, labelKey: 'remote.overlays.textName', helperKey: 'remote.overlays.textNameHelper' },
  { id: 'date', ref: showDate, labelKey: 'remote.overlays.textDate', helperKey: 'remote.overlays.textDateHelper' },
  { id: 'folder', ref: showFolder, labelKey: 'remote.overlays.textFolder', helperKey: 'remote.overlays.textFolderHelper' },
  { id: 'location', ref: showLocation, labelKey: 'remote.overlays.textLocation', helperKey: 'remote.overlays.textLocationHelper' },
]
</script>

<template>
  <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-xl border border-gray-200/50 dark:border-gray-700/50 flex flex-col relative z-10">
    <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between z-20 bg-white dark:bg-gray-800/90 rounded-t-3xl">
      <div class="flex items-center space-x-3 overflow-hidden">
        <div class="p-2 bg-blue-50 dark:bg-blue-500/10 rounded-lg flex-shrink-0">
          <AdjustmentsHorizontalIcon class="w-5 h-5 text-blue-600 dark:text-blue-400" />
        </div>
        <h3 class="text-lg font-bold text-gray-900 dark:text-white tracking-tight truncate">
          {{ t('remote.overlays.title') }}
        </h3>
      </div>
    </div>
    
    <div class="p-6 relative z-10">
      <div v-if="isLoading" class="flex justify-center py-4">
        <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-600"></div>
      </div>
      <div v-else class="space-y-4">
        <div v-for="ctrl in controls" :key="ctrl.id" class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-sm font-medium text-gray-700 dark:text-gray-300">{{ t(ctrl.labelKey) }}</span>
            <HelperText :text="t(ctrl.helperKey)" />
          </div>
          <label
            class="relative inline-flex items-center"
            :class="playerStore.isConnected ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'"
          >
            <input
              v-model="ctrl.ref.value"
              type="checkbox"
              class="sr-only peer"
              :disabled="!playerStore.isConnected"
              @change="handleChange"
            >
            <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-indigo-300 dark:peer-focus:ring-indigo-800 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-indigo-600"></div>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>
