<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ComputerDesktopIcon } from '@heroicons/vue/24/outline'
import { useConfigStore } from '../stores/config'
import FieldRow from './settings/FieldRow.vue'
import NumberField from './settings/NumberField.vue'
import SegmentedControl from './settings/SegmentedControl.vue'
import ToggleSwitch from './settings/ToggleSwitch.vue'
import Panel from './ui/Panel.vue'
import StatusBanner from './ui/StatusBanner.vue'

const { t } = useI18n()
const configStore = useConfigStore()
const { config } = storeToRefs(configStore)

const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')
let statusTimer: number | undefined

const overlay = reactive({
  display_mode: 'auto_hide' as 'persistent' | 'auto_hide',
  auto_hide_seconds: 5,
  idle_hide_seconds: 5,
  enabled_input_types: ['touch', 'mouse', 'keyboard'] as string[],
  transparent: true
})

const INPUT_TYPES = ['touch', 'mouse', 'keyboard']

const showStatus = (tone: 'success' | 'danger', message: string) => {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer)
  statusTone.value = tone
  statusMessage.value = message
  statusTimer = window.setTimeout(() => {
    statusMessage.value = ''
  }, 3000)
}

const asNumber = (value: unknown, fallback: number) => {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

const syncFromConfig = () => {
  const ov = config.value?.overlay || {}
  overlay.display_mode = ov.display_mode === 'persistent' ? 'persistent' : 'auto_hide'
  overlay.auto_hide_seconds = asNumber(ov.auto_hide_seconds, 5)
  overlay.idle_hide_seconds = asNumber(ov.idle_hide_seconds, 5)
  overlay.enabled_input_types = Array.isArray(ov.enabled_input_types)
    ? [...(ov.enabled_input_types as string[])]
    : [...INPUT_TYPES]
  overlay.transparent = ov.transparent !== false
}

const save = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({
      overlay: {
        display_mode: overlay.display_mode,
        auto_hide_seconds: Number(overlay.auto_hide_seconds),
        idle_hide_seconds: Number(overlay.idle_hide_seconds),
        enabled_input_types: [...overlay.enabled_input_types],
        transparent: Boolean(overlay.transparent)
      }
    })
    showStatus('success', t('appearance.overlay.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('appearance.overlay.failed'))
    syncFromConfig()
  } finally {
    isSaving.value = false
  }
}

const toggleInputType = async (type: string, enabled: boolean) => {
  overlay.enabled_input_types = enabled
    ? [...new Set([...overlay.enabled_input_types, type])]
    : overlay.enabled_input_types.filter(it => it !== type)
  await save()
}

const inputTypeLabel = (type: string): string => {
  const map: Record<string, string> = {
    touch: t('appearance.overlay.inputTouch'),
    mouse: t('appearance.overlay.inputMouse'),
    keyboard: t('appearance.overlay.inputKeyboard')
  }
  return map[type] || type
}

onMounted(async () => {
  if (!config.value || Object.keys(config.value).length === 0) {
    await configStore.fetchWorkflowConfig()
  }
  syncFromConfig()
})

watch(
  () => [config.value?.overlay?.display_mode, config.value?.overlay?.auto_hide_seconds],
  () => {
    if (!isSaving.value) syncFromConfig()
  }
)
</script>

<template>
  <Panel padded>
    <div class="space-y-6">
      <div class="border-b border-gray-100 pb-5 dark:border-gray-700/60">
        <div class="flex items-center gap-3">
          <div
            class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
          >
            <ComputerDesktopIcon class="h-5 w-5" />
          </div>
          <div>
            <h2 class="text-lg font-semibold text-gray-950 dark:text-white">
              {{ t('appearance.overlay.title') }}
            </h2>
            <p class="mt-0.5 text-sm leading-6 text-gray-600 dark:text-gray-300">
              {{ t('appearance.overlay.description') }}
            </p>
          </div>
        </div>
      </div>

      <FieldRow
        :label="t('appearance.overlay.displayMode.label')"
        :help="t('appearance.overlay.displayMode.help')"
      >
        <SegmentedControl
          :model-value="overlay.display_mode"
          :options="[
            { value: 'persistent', label: t('appearance.overlay.displayMode.persistent') },
            { value: 'auto_hide', label: t('appearance.overlay.displayMode.autoHide') }
          ]"
          @update:model-value="
            value => {
              overlay.display_mode = value as 'persistent' | 'auto_hide'
              save()
            }
          "
        />
      </FieldRow>

      <FieldRow
        v-if="overlay.display_mode === 'auto_hide'"
        :label="t('appearance.overlay.autoHideSeconds.label')"
        :help="t('appearance.overlay.autoHideSeconds.help')"
      >
        <NumberField
          v-model="overlay.auto_hide_seconds"
          :min="1"
          :step="1"
          unit="s"
          @update:model-value="save()"
        />
      </FieldRow>

      <FieldRow
        :label="t('appearance.overlay.idleHideSeconds.label')"
        :help="t('appearance.overlay.idleHideSeconds.help')"
      >
        <NumberField
          v-model="overlay.idle_hide_seconds"
          :min="0"
          :step="0.5"
          unit="s"
          @update:model-value="save()"
        />
      </FieldRow>

      <FieldRow
        :label="t('appearance.overlay.inputTypes.label')"
        :help="t('appearance.overlay.inputTypes.help')"
      >
        <div class="flex flex-wrap gap-4">
          <label
            v-for="type in INPUT_TYPES"
            :key="type"
            class="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            <input
              type="checkbox"
              :checked="overlay.enabled_input_types.includes(type)"
              class="h-4 w-4 rounded border-gray-300 text-violet-600 focus:ring-violet-500 dark:border-gray-600 dark:bg-gray-700"
              @change="toggleInputType(type, ($event.target as HTMLInputElement).checked)"
            />
            {{ inputTypeLabel(type) }}
          </label>
        </div>
      </FieldRow>

      <FieldRow
        :label="t('appearance.overlay.transparent.label')"
        :help="t('appearance.overlay.transparent.help')"
      >
        <ToggleSwitch v-model="overlay.transparent" @update:model-value="save()" />
      </FieldRow>

      <div v-if="statusMessage">
        <StatusBanner :tone="statusTone" :message="statusMessage" />
      </div>
    </div>
  </Panel>
</template>
