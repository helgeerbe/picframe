<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import {
  ChevronDownIcon,
  Squares2X2Icon,
  ArrowPathIcon,
  Cog6ToothIcon,
  CheckIcon
} from '@heroicons/vue/24/outline'
import { useOverlayStore, type OverlayPlugin } from '../../stores/overlay'
import { useConfigStore } from '../../stores/config'
import ToggleSwitch from '../settings/ToggleSwitch.vue'
import NumberField from '../settings/NumberField.vue'
import StatusBanner from '../ui/StatusBanner.vue'

const { t } = useI18n()
const overlayStore = useOverlayStore()
const configStore = useConfigStore()
const { config } = storeToRefs(configStore)
const { plugins, isLoading, error: overlayError } = storeToRefs(overlayStore)

const isExpanded = ref(true)
const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')
const configPluginId = ref<string | null>(null)
// Per-plugin config form state: { pluginId: { field: value } }
// The dynamic config values come from arbitrary plugin schemas; `any` keeps the
// index accesses ergonomic (matching the config-store config blob convention).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const configDrafts = ref<Record<string, Record<string, any>>>({})
let statusTimer: number | undefined

const enabledPlugins = computed<string[]>(() => {
  const overlay = config.value?.overlay
  return Array.isArray(overlay?.enabled_plugins) ? [...(overlay!.enabled_plugins as string[])] : []
})

const visiblePlugin = computed<string | null>(() => {
  const v = config.value?.overlay?.visible_plugin
  return typeof v === 'string' ? v : null
})

const showStatus = (tone: 'success' | 'danger', message: string) => {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer)
  statusTone.value = tone
  statusMessage.value = message
  statusTimer = window.setTimeout(() => {
    statusMessage.value = ''
  }, 3000)
}

const saveOverlay = async (patch: Record<string, unknown>) => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({ overlay: patch })
    showStatus('success', t('remote.touchOverlay.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('remote.touchOverlay.failed'))
  } finally {
    isSaving.value = false
  }
}

const togglePlugin = async (plugin: OverlayPlugin, enabled: boolean) => {
  let next = enabled
    ? [...enabledPlugins.value, plugin.id]
    : enabledPlugins.value.filter(id => id !== plugin.id)
  // Drop ids that no longer correspond to a discovered plugin.
  next = next.filter(id => plugins.value.some(p => p.id === id))
  const patch: Record<string, unknown> = { enabled_plugins: next }
  // If disabling the currently visible plugin, clear it.
  if (!enabled && visiblePlugin.value === plugin.id) patch.visible_plugin = null
  await saveOverlay(patch)
}

const setVisible = async (pluginId: string | null) => {
  await saveOverlay({ visible_plugin: pluginId })
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
  statusMessage.value = ''
  try {
    const result = await overlayStore.updatePluginConfig(
      plugin.id,
      configDrafts.value[plugin.id] || {}
    )
    // Reflect the validated config back into the loaded plugin list.
    plugin.config = result.config
    showStatus('success', t('remote.touchOverlay.configSaved'))
    configPluginId.value = null
  } catch (e) {
    console.error(e)
    showStatus('danger', t('remote.touchOverlay.configFailed'))
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
  await overlayStore.fetchPlugins()
  // Ensure config (for overlay.enabled_plugins / visible_plugin) is loaded.
  if (!config.value || Object.keys(config.value).length === 0) {
    await configStore.fetchWorkflowConfig()
  }
})
</script>

<template>
  <div
    class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800"
  >
    <button
      type="button"
      class="flex w-full items-center justify-between border-b border-gray-100 bg-white px-6 py-5 text-left transition-colors hover:bg-gray-50 dark:border-gray-700/50 dark:bg-gray-800 dark:hover:bg-gray-700/40"
      :aria-expanded="isExpanded"
      @click="isExpanded = !isExpanded"
    >
      <div class="flex items-center space-x-3 overflow-hidden">
        <div class="flex-shrink-0 rounded-lg bg-violet-50 p-2 dark:bg-violet-500/10">
          <Squares2X2Icon class="h-5 w-5 text-violet-600 dark:text-violet-400" />
        </div>
        <div class="min-w-0">
          <h3 class="truncate text-lg font-bold tracking-tight text-gray-900 dark:text-white">
            {{ t('remote.touchOverlay.title') }}
          </h3>
          <p class="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
            {{ t('remote.touchOverlay.description') }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="!isLoading"
          type="button"
          class="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-700/50 dark:hover:text-gray-200"
          :title="t('common.retry')"
          @click.stop="overlayStore.fetchPlugins()"
        >
          <ArrowPathIcon class="h-4 w-4" />
        </button>
        <ChevronDownIcon
          class="h-5 w-5 flex-shrink-0 text-gray-400 transition-transform"
          :class="{ 'rotate-180': isExpanded }"
        />
      </div>
    </button>

    <div v-show="isExpanded" class="p-6">
      <div
        v-if="isLoading"
        class="flex justify-center py-6"
        role="status"
        :aria-label="t('remote.touchOverlay.loading')"
      >
        <div class="h-8 w-8 animate-spin rounded-full border-b-2 border-violet-600"></div>
      </div>

      <div v-else-if="overlayError" class="py-2">
        <StatusBanner tone="danger" :message="overlayError" />
      </div>

      <div v-else-if="plugins.length === 0" class="py-6 text-center">
        <p class="text-sm text-gray-500 dark:text-gray-400">
          {{ t('remote.touchOverlay.empty') }}
        </p>
      </div>

      <div v-else class="space-y-5">
        <!-- Visible-plugin selector -->
        <div class="space-y-2">
          <label
            class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
          >
            {{ t('remote.touchOverlay.visiblePlugin') }}
          </label>
          <select
            :value="visiblePlugin ?? ''"
            class="w-full rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5 text-sm font-medium text-gray-900 focus:outline-none focus:ring-2 focus:ring-violet-500/50 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-100"
            :disabled="isSaving"
            @change="setVisible(($event.target as HTMLSelectElement).value || null)"
          >
            <option value="">{{ t('remote.touchOverlay.dockOnly') }}</option>
            <option
              v-for="plugin in plugins"
              :key="plugin.id"
              :value="plugin.id"
              :disabled="!enabledPlugins.includes(plugin.id)"
            >
              {{ plugin.icon ? `${plugin.icon} ` : '' }}{{ plugin.name || plugin.id }}
            </option>
          </select>
          <p class="text-xs text-gray-500 dark:text-gray-400">
            {{ t('remote.touchOverlay.visiblePluginHelp') }}
          </p>
        </div>

        <!-- Plugin list -->
        <ul class="divide-y divide-gray-100 dark:divide-gray-700/60">
          <li v-for="plugin in plugins" :key="plugin.id" class="py-4 first:pt-0 last:pb-0">
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
              <ToggleSwitch
                :model-value="enabledPlugins.includes(plugin.id)"
                :disabled="isSaving"
                :label="plugin.name || plugin.id"
                @update:model-value="value => togglePlugin(plugin, value)"
              />
            </div>

            <!-- Per-plugin config editor -->
            <div v-if="plugin.has_config" class="mt-3">
              <button
                type="button"
                class="inline-flex items-center gap-1.5 text-xs font-semibold text-violet-600 transition-colors hover:text-violet-500 dark:text-violet-400"
                @click="openConfig(plugin)"
              >
                <Cog6ToothIcon class="h-4 w-4" />
                {{
                  configPluginId === plugin.id
                    ? t('remote.touchOverlay.hideConfig')
                    : t('remote.touchOverlay.editConfig')
                }}
              </button>

              <div
                v-if="configPluginId === plugin.id"
                class="mt-4 space-y-4 rounded-lg border border-gray-100 bg-gray-50 p-4 dark:border-gray-700/60 dark:bg-gray-900/30"
              >
                <div
                  v-for="(_schema, fieldName) in plugin.config_schema"
                  :key="fieldName"
                  class="space-y-1.5"
                >
                  <label class="block text-xs font-semibold text-gray-700 dark:text-gray-300">
                    {{ fieldLabel(plugin.id, fieldName) }}
                  </label>
                  <p
                    v-if="fieldHelp(plugin.id, fieldName)"
                    class="text-xs text-gray-500 dark:text-gray-400"
                  >
                    {{ fieldHelp(plugin.id, fieldName) }}
                  </p>

                  <!-- boolean -->
                  <ToggleSwitch
                    v-if="plugin.config_schema[fieldName]?.type === 'boolean'"
                    :model-value="!!configDrafts[plugin.id]?.[fieldName]"
                    @update:model-value="value => (configDrafts[plugin.id][fieldName] = value)"
                  />

                  <!-- number / integer -->
                  <NumberField
                    v-else-if="
                      ['number', 'integer'].includes(plugin.config_schema[fieldName]?.type)
                    "
                    :model-value="configDrafts[plugin.id]?.[fieldName] ?? 0"
                    :step="plugin.config_schema[fieldName]?.type === 'integer' ? 1 : 0.1"
                    @update:model-value="value => (configDrafts[plugin.id][fieldName] = value)"
                  />

                  <!-- enum -->
                  <select
                    v-else-if="Array.isArray(plugin.config_schema[fieldName]?.enum)"
                    :value="configDrafts[plugin.id]?.[fieldName] ?? ''"
                    class="w-full max-w-xs rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-violet-500 focus:ring-violet-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    @change="
                      configDrafts[plugin.id][fieldName] = (
                        $event.target as HTMLSelectElement
                      ).value
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
                    class="block w-full max-w-md rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-violet-500 focus:ring-violet-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
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
                    class="inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-60"
                    @click="savePluginConfig(plugin)"
                  >
                    <CheckIcon class="h-4 w-4" />
                    {{ isSaving ? t('common.saving') : t('common.save') }}
                  </button>
                </div>
              </div>
            </div>
          </li>
        </ul>

        <StatusBanner v-if="statusMessage" :tone="statusTone" :message="statusMessage" />
      </div>
    </div>
  </div>
</template>
