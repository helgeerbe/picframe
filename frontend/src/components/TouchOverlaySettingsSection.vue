<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { Cog6ToothIcon, CheckIcon } from '@heroicons/vue/24/outline'
import { useOverlayStore, type OverlayPlugin } from '../stores/overlay'
import { useConfigStore } from '../stores/config'
import FieldRow from './settings/FieldRow.vue'
import SettingsSection from './settings/SettingsSection.vue'
import StatusBanner from './ui/StatusBanner.vue'
import ToggleSwitch from './settings/ToggleSwitch.vue'

// The two Settings-tab-owned overlay fields are bound to the schema-driven
// `localConfig.overlay` working copy (passed via v-model) and persisted by the
// global Settings Save. Appearance-managed overlay fields (display_mode, the
// hide timers, transparent, enabled_plugins, visible_plugin) stay auto-save in
// Appearance and are intentionally NOT modeled here — modeling them would let a
// once-initialized localConfig.overlay clobber Appearance's live edits on Save.
interface OverlaySettingsModel {
  enabled: boolean
  enabled_input_types: string[]
}

const props = defineProps<{
  modelValue: OverlaySettingsModel
}>()

const emit = defineEmits<{
  'update:modelValue': [value: OverlaySettingsModel]
}>()

const { t } = useI18n()
const configStore = useConfigStore()
const overlayStore = useOverlayStore()
const { config } = storeToRefs(configStore)
const { plugins, isLoading, error: overlayError } = storeToRefs(overlayStore)

const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')
const configPluginId = ref<string | null>(null)
// Per-plugin config form state: { pluginId: { field: value } }. The dynamic
// config values come from arbitrary plugin schemas; `any` keeps the index
// accesses ergonomic (matching the config-store config blob convention).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const configDrafts = ref<Record<string, Record<string, any>>>({})
let statusTimer: number | undefined

const INPUT_TYPES = ['touch', 'mouse', 'keyboard']

// Master enable + enabled input types are pure local mutations on the working
// copy; they are persisted by the global Settings Save button (no auto-save
// here, consistent with the other schema-driven Settings sections).
const enabled = computed<boolean>({
  get: () => Boolean(props.modelValue?.enabled),
  set: v => emit('update:modelValue', { ...props.modelValue, enabled: v })
})

const enabledInputTypes = computed<string[]>({
  get: () =>
    Array.isArray(props.modelValue?.enabled_input_types)
      ? [...props.modelValue.enabled_input_types]
      : [...INPUT_TYPES],
  set: v => emit('update:modelValue', { ...props.modelValue, enabled_input_types: v })
})

const enabledPlugins = computed<string[]>(() => {
  const ov = config.value?.overlay
  return Array.isArray(ov?.enabled_plugins) ? [...(ov!.enabled_plugins as string[])] : []
})

// Only plugins the user has activated (via Appearance) are configurable here.
const activatedPlugins = computed<OverlayPlugin[]>(() =>
  plugins.value.filter(p => enabledPlugins.value.includes(p.id))
)

const showStatus = (tone: 'success' | 'danger', message: string) => {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer)
  statusTone.value = tone
  statusMessage.value = message
  statusTimer = window.setTimeout(() => {
    statusMessage.value = ''
  }, 3000)
}

const toggleInputType = (type: string, isEnabled: boolean) => {
  enabledInputTypes.value = isEnabled
    ? [...new Set([...enabledInputTypes.value, type])]
    : enabledInputTypes.value.filter(it => it !== type)
}

const inputTypeLabel = (type: string): string => {
  const map: Record<string, string> = {
    touch: t('settings.touchOverlay.inputTouch'),
    mouse: t('settings.touchOverlay.inputMouse'),
    keyboard: t('settings.touchOverlay.inputKeyboard')
  }
  return map[type] || type
}

const openConfig = (plugin: OverlayPlugin) => {
  if (!plugin.has_config) return
  if (configPluginId.value === plugin.id) {
    configPluginId.value = null
    return
  }
  // Seed the draft from the plugin's effective config.
  configDrafts.value[plugin.id] = { ...(plugin.config || {}) }
  configPluginId.value = plugin.id
}

const savePluginConfig = async (plugin: OverlayPlugin) => {
  if (isSaving.value) return
  isSaving.value = true
  try {
    const result = await overlayStore.updatePluginConfig(
      plugin.id,
      configDrafts.value[plugin.id] || {}
    )
    plugin.config = result.config
    showStatus('success', t('settings.touchOverlay.pluginConfig.configSaved'))
    configPluginId.value = null
  } catch (e) {
    console.error(e)
    showStatus('danger', t('settings.touchOverlay.pluginConfig.configFailed'))
  } finally {
    isSaving.value = false
  }
}

const fieldLabel = (pluginId: string, fieldName: string): string => {
  const schema = plugins.value.find(p => p.id === pluginId)?.config_schema?.[fieldName]
  return (schema?.label as string | undefined) || fieldName
}

const fieldHelp = (pluginId: string, fieldName: string): string => {
  const schema = plugins.value.find(p => p.id === pluginId)?.config_schema?.[fieldName]
  return (schema?.help as string | undefined) || ''
}

onMounted(async () => {
  // Settings already fetches the full config, but guard for a direct tab visit
  // or a config blob that only has the workflow-config allowlist. The Appearance
  // overlay fields (enabled_plugins etc.) are read live from the shared config
  // blob, so the full config must be present for the per-plugin list below.
  const ov = config.value?.overlay
  if (!config.value || Object.keys(config.value).length === 0 || typeof ov?.enabled !== 'boolean') {
    await configStore.fetchConfig()
  }
  await overlayStore.fetchPlugins()
})
</script>
<template>
  <div class="space-y-8">
    <h2
      class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white"
    >
      {{ t('settings.touchOverlay.title') }}
    </h2>

    <SettingsSection
      id="settings-touch-overlay"
      :title="t('settings.touchOverlay.title')"
      :description="t('settings.touchOverlay.description')"
      default-open
    >
      <FieldRow
        :label="t('settings.touchOverlay.enable.label')"
        :help="t('settings.touchOverlay.enable.help')"
      >
        <div class="space-y-2">
          <ToggleSwitch v-model="enabled" />
          <p class="text-xs leading-relaxed text-amber-700 dark:text-amber-300">
            {{ t('settings.touchOverlay.restartRequired') }}
          </p>
        </div>
      </FieldRow>

      <FieldRow
        :label="t('settings.touchOverlay.inputTypes.label')"
        :help="t('settings.touchOverlay.inputTypes.help')"
      >
        <div class="flex flex-wrap gap-4">
          <label
            v-for="type in INPUT_TYPES"
            :key="type"
            class="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300"
          >
            <input
              type="checkbox"
              :checked="enabledInputTypes.includes(type)"
              class="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700"
              @change="toggleInputType(type, ($event.target as HTMLInputElement).checked)"
            />
            {{ inputTypeLabel(type) }}
          </label>
        </div>
      </FieldRow>
    </SettingsSection>

    <SettingsSection
      id="settings-touch-overlay-plugins"
      :title="t('settings.touchOverlay.pluginConfig.title')"
      :description="t('settings.touchOverlay.pluginConfig.description')"
      default-open
    >
      <div
        v-if="isLoading"
        class="flex justify-center py-6"
        role="status"
        :aria-label="t('remote.touchOverlay.loading')"
      >
        <div class="h-8 w-8 animate-spin rounded-full border-b-2 border-indigo-600"></div>
      </div>

      <div v-else-if="overlayError" class="py-2">
        <StatusBanner tone="danger" :message="overlayError" />
      </div>

      <div
        v-else-if="activatedPlugins.length === 0"
        class="py-4 text-center text-sm text-gray-500 dark:text-gray-400"
      >
        {{ t('settings.touchOverlay.pluginConfig.noPlugins') }}
      </div>

      <div v-else :class="{ 'pointer-events-none opacity-50': !enabled }">
        <p v-if="!enabled" class="mb-4 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
          {{ t('settings.touchOverlay.pluginConfig.disabledHint') }}
        </p>
        <ul class="divide-y divide-gray-100 dark:divide-gray-700/60">
          <li v-for="plugin in activatedPlugins" :key="plugin.id" class="py-4 first:pt-0 last:pb-0">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span v-if="plugin.icon" class="text-base leading-none">{{ plugin.icon }}</span>
                  <span class="truncate text-sm font-semibold text-gray-900 dark:text-white">
                    {{ plugin.name || plugin.id }}
                  </span>
                </div>
                <p v-if="plugin.description" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {{ plugin.description }}
                </p>
              </div>
              <button
                v-if="plugin.has_config"
                type="button"
                class="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 transition-colors hover:text-indigo-500 dark:text-indigo-400"
                @click="openConfig(plugin)"
              >
                <Cog6ToothIcon class="h-4 w-4" />
                {{
                  configPluginId === plugin.id
                    ? t('settings.touchOverlay.pluginConfig.hideConfig')
                    : t('settings.touchOverlay.pluginConfig.editConfig')
                }}
              </button>
            </div>

            <!-- Per-plugin config editor -->
            <div
              v-if="plugin.has_config && configPluginId === plugin.id"
              class="mt-4 space-y-4 rounded-lg border border-gray-100 bg-gray-50 p-4 dark:border-gray-700/60 dark:bg-gray-900/30"
            >
              <div
                v-for="(_schema, fieldName) in plugin.config_schema"
                :key="fieldName"
                class="space-y-1.5"
              >
                <label class="block text-xs font-semibold text-gray-700 dark:text-gray-300">
                  {{ fieldLabel(plugin.id, fieldName) }}
                  <span
                    v-if="fieldHelp(plugin.id, fieldName)"
                    class="ml-1 font-normal text-gray-500 dark:text-gray-400"
                  >
                    — {{ fieldHelp(plugin.id, fieldName) }}
                  </span>
                </label>

                <!-- boolean -->
                <ToggleSwitch
                  v-if="plugin.config_schema[fieldName]?.type === 'boolean'"
                  :model-value="!!configDrafts[plugin.id]?.[fieldName]"
                  @update:model-value="value => (configDrafts[plugin.id][fieldName] = value)"
                />

                <!-- number / integer -->
                <input
                  v-else-if="['number', 'integer'].includes(plugin.config_schema[fieldName]?.type)"
                  type="number"
                  :value="configDrafts[plugin.id]?.[fieldName] ?? 0"
                  :step="plugin.config_schema[fieldName]?.type === 'integer' ? 1 : 0.1"
                  class="block w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                  @input="
                    configDrafts[plugin.id][fieldName] = Number(
                      ($event.target as HTMLInputElement).value
                    )
                  "
                />

                <!-- enum -->
                <select
                  v-else-if="Array.isArray(plugin.config_schema[fieldName]?.enum)"
                  :value="configDrafts[plugin.id]?.[fieldName] ?? ''"
                  class="w-full max-w-xs rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                  @change="
                    configDrafts[plugin.id][fieldName] = ($event.target as HTMLSelectElement).value
                  "
                >
                  <option
                    v-for="opt in plugin.config_schema[fieldName]?.enum"
                    :key="String(opt)"
                    :value="opt"
                  >
                    {{ opt }}
                  </option>
                </select>

                <!-- string (default) -->
                <input
                  v-else
                  :value="configDrafts[plugin.id]?.[fieldName] ?? ''"
                  type="text"
                  class="block w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                  @input="
                    configDrafts[plugin.id][fieldName] = ($event.target as HTMLInputElement).value
                  "
                />
              </div>

              <div class="flex items-center justify-end gap-3 pt-2">
                <button
                  type="button"
                  class="rounded-lg px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700/50"
                  @click="configPluginId = null"
                >
                  {{ t('common.cancel') }}
                </button>
                <button
                  type="button"
                  :disabled="isSaving"
                  class="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                  @click="savePluginConfig(plugin)"
                >
                  <CheckIcon class="h-4 w-4" />
                  {{ isSaving ? t('common.saving') : t('common.save') }}
                </button>
              </div>
            </div>
          </li>
        </ul>
      </div>

      <StatusBanner v-if="statusMessage" :tone="statusTone" :message="statusMessage" />
    </SettingsSection>
  </div>
</template>
