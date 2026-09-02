<script setup lang="ts">
import { ref, onMounted, type Ref } from 'vue'
import { useConfigStore } from '../stores/config'
import { usePlayerStore } from '../stores/player'
import { useI18n } from 'vue-i18n'
import HelperText from './HelperText.vue'
import ToggleSwitch from './settings/ToggleSwitch.vue'
import StatusBanner from './ui/StatusBanner.vue'
import { AdjustmentsHorizontalIcon } from '@heroicons/vue/24/outline'

const configStore = useConfigStore()
const playerStore = usePlayerStore()
const { t } = useI18n()

const isLoading = ref(true)
const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')

const showClock = ref(false)
const showTextOnVideo = ref(false)
const showTitle = ref(false)
const showCaption = ref(false)
const showName = ref(false)
const showDate = ref(false)
const showFolder = ref(false)
const showLocation = ref(false)

const syncControlsFromConfig = () => {
  const viewerConfig = configStore.config?.viewer || {}
  showClock.value = !!viewerConfig.show_clock
  showTextOnVideo.value = !!viewerConfig.show_text_on_video

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
      console.error('Failed to fetch config for overlays', e)
    }
  }
  syncControlsFromConfig()

  isLoading.value = false
})

const overlayPayload = () => {
  const textElements = []
  if (showTitle.value) textElements.push('title')
  if (showCaption.value) textElements.push('caption')
  if (showName.value) textElements.push('name')
  if (showDate.value) textElements.push('date')
  if (showFolder.value) textElements.push('folder')
  if (showLocation.value) textElements.push('location')

  const showTextStr = textElements.join(' ')

  return {
    viewer: {
      show_clock: showClock.value,
      show_text_enabled: showTextStr.length > 0,
      text_overlay_format: showTextStr,
      show_text_on_video: showTextOnVideo.value
    }
  }
}

const handleChange = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''

  try {
    const payload = overlayPayload()
    await configStore.saveWorkflowConfig(payload)
    playerStore.sendCommand('REQUEST_STATE')
    statusTone.value = 'success'
    statusMessage.value = t('remote.overlays.saved')
  } catch (error) {
    console.error(error)
    statusTone.value = 'danger'
    statusMessage.value = t('remote.overlays.failed')
    syncControlsFromConfig()
    return
  } finally {
    isSaving.value = false
    window.setTimeout(() => {
      statusMessage.value = ''
    }, 3000)
  }
}

const updateControl = (control: { ref: Ref<boolean> }, value: boolean) => {
  control.ref.value = value
  void handleChange()
}

const controls: Array<{ id: string; ref: Ref<boolean>; labelKey: string; helperKey: string }> = [
  {
    id: 'clock',
    ref: showClock,
    labelKey: 'remote.overlays.clock',
    helperKey: 'remote.overlays.clockHelper'
  },
  {
    id: 'textOnVideo',
    ref: showTextOnVideo,
    labelKey: 'remote.overlays.textOnVideo',
    helperKey: 'remote.overlays.textOnVideoHelper'
  },
  {
    id: 'title',
    ref: showTitle,
    labelKey: 'remote.overlays.textTitle',
    helperKey: 'remote.overlays.textTitleHelper'
  },
  {
    id: 'caption',
    ref: showCaption,
    labelKey: 'remote.overlays.textCaption',
    helperKey: 'remote.overlays.textCaptionHelper'
  },
  {
    id: 'name',
    ref: showName,
    labelKey: 'remote.overlays.textName',
    helperKey: 'remote.overlays.textNameHelper'
  },
  {
    id: 'date',
    ref: showDate,
    labelKey: 'remote.overlays.textDate',
    helperKey: 'remote.overlays.textDateHelper'
  },
  {
    id: 'folder',
    ref: showFolder,
    labelKey: 'remote.overlays.textFolder',
    helperKey: 'remote.overlays.textFolderHelper'
  },
  {
    id: 'location',
    ref: showLocation,
    labelKey: 'remote.overlays.textLocation',
    helperKey: 'remote.overlays.textLocationHelper'
  }
]
</script>

<template>
  <div
    class="relative z-10 flex flex-col rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800"
  >
    <div
      class="z-20 flex items-center justify-between border-b border-gray-100 bg-white px-6 py-5 dark:border-gray-700/50 dark:bg-gray-800"
    >
      <div class="flex items-center space-x-3 overflow-hidden">
        <div class="p-2 bg-blue-50 dark:bg-blue-500/10 rounded-lg flex-shrink-0">
          <AdjustmentsHorizontalIcon class="w-5 h-5 text-blue-600 dark:text-blue-400" />
        </div>
        <h3 class="truncate text-lg font-bold tracking-normal text-gray-900 dark:text-white">
          {{ t('remote.overlays.title') }}
        </h3>
      </div>
    </div>

    <div class="p-6 relative z-10">
      <div
        v-if="isLoading"
        class="flex justify-center py-4"
        role="status"
        :aria-label="t('remote.overlays.loading')"
      >
        <div class="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-600"></div>
      </div>
      <div v-else class="space-y-4">
        <div v-for="ctrl in controls" :key="ctrl.id" class="flex items-center justify-between">
          <div class="flex items-center space-x-2">
            <span class="text-sm font-medium text-gray-700 dark:text-gray-300">{{
              t(ctrl.labelKey)
            }}</span>
            <HelperText :text="t(ctrl.helperKey)" />
          </div>
          <ToggleSwitch
            :model-value="ctrl.ref.value"
            :disabled="isSaving"
            :label="t(ctrl.labelKey)"
            @update:model-value="value => updateControl(ctrl, value)"
          />
        </div>
        <StatusBanner v-if="statusMessage" :tone="statusTone" :message="statusMessage" />
      </div>
    </div>
  </div>
</template>
