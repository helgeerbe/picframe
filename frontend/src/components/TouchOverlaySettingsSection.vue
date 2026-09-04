<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { Cog6ToothIcon, CheckIcon, Square2StackIcon } from '@heroicons/vue/24/outline'
import { useOverlayStore, type OverlayPlugin } from '../stores/overlay'
import { useConfigStore } from '../stores/config'
import FieldRow from './settings/FieldRow.vue'
import NumberField from './settings/NumberField.vue'
import SegmentedControl from './settings/SegmentedControl.vue'
import SettingsSection from './settings/SettingsSection.vue'
import StatusBanner from './ui/StatusBanner.vue'
import ToggleSwitch from './settings/ToggleSwitch.vue'

// The Settings-tab-owned overlay working copy (passed via v-model) covers only
// the schema-driven fields persisted by the global Settings Save: `enabled` and
// `enabled_input_types`. The overlay layout fields moved here from Appearance
// — the global idle fade and the per-plugin panel layout (position/size/content
// align/display mode/z-order/per-plugin idle fade) — are NOT part of that
// working copy: they auto-save through `savePartialConfig` (idle fade) and the
// dedicated `PUT /overlay/plugins/{id}/layout` endpoint (per-plugin layout), so
// they never flow through `SettingsView.initializeConfig()` and cannot clobber
// a stale working copy on Save.
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
const layoutPluginId = ref<string | null>(null)
// Per-plugin config form state: { pluginId: { field: value } }. The dynamic
// config values come from arbitrary plugin schemas; `any` keeps the index
// accesses ergonomic (matching the config-store config blob convention).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const configDrafts = ref<Record<string, Record<string, any>>>({})
let statusTimer: number | undefined

/** Global idle fade (the per-plugin default when a layout omits it). Auto-saves
 *  via `savePartialConfig`; not part of the schema-driven working copy. */
const overlay = reactive({
  idle_hide_seconds: 5
})

/** Nine anchors for the position select. */
const ANCHORS = [
  'top-left',
  'top-center',
  'top-right',
  'middle-left',
  'middle-center',
  'middle-right',
  'bottom-left',
  'bottom-center',
  'bottom-right'
] as const

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

// Settings configures EVERY discovered plugin regardless of its Appearance
// activation state: a plugin deactivated in Appearance must stay configurable
// here (it simply won't appear as a tile in the Remote dock until re-activated).
// `enabledPlugins` is read live only to render the activation status badge.

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

const asNumber = (value: unknown, fallback: number) => {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

const syncFromConfig = () => {
  const ov = config.value?.overlay || {}
  overlay.idle_hide_seconds = asNumber(ov.idle_hide_seconds, 5)
}

/** Auto-save the global idle fade through `savePartialConfig` (#754). */
const saveIdle = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({
      overlay: { idle_hide_seconds: Number(overlay.idle_hide_seconds) }
    })
    showStatus('success', t('settings.touchOverlay.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('settings.touchOverlay.failed'))
    syncFromConfig()
  } finally {
    isSaving.value = false
  }
}

/** Effective layout for a plugin (from the discovered plugin's merged layout),
 * or sensible defaults. Drives the per-plugin layout editor working copy. */
const layoutOf = (plugin: OverlayPlugin): Record<string, unknown> => {
  const l = plugin.layout ?? {}
  return {
    position: l.position ?? plugin.position ?? 'top-right',
    width: l.width ?? 0,
    height: l.height ?? 0,
    scale: l.scale ?? (plugin.size ? 1 : 0),
    display_mode: l.display_mode ?? 'auto_hide',
    idle_hide_seconds: l.idle_hide_seconds ?? 0,
    z_order: l.z_order ?? 0
  }
}

/** Per-plugin layout working copies, keyed by plugin id. */
const layoutDrafts = reactive<Record<string, Record<string, unknown>>>({})

const ensureDraft = (plugin: OverlayPlugin): Record<string, unknown> => {
  if (!layoutDrafts[plugin.id]) {
    layoutDrafts[plugin.id] = layoutOf(plugin)
  }
  return layoutDrafts[plugin.id]
}

/** Toggle the per-plugin layout editor. Reopening re-seeds from the effective
 *  layout so external changes (e.g. via MQTT) are reflected. */
const openLayout = (plugin: OverlayPlugin) => {
  if (layoutPluginId.value === plugin.id) {
    layoutPluginId.value = null
    return
  }
  delete layoutDrafts[plugin.id]
  ensureDraft(plugin)
  layoutPluginId.value = plugin.id
}

/** Save a plugin's layout via the dedicated PUT endpoint (#752/#754). 0/empty
 *  for width/height/scale/idle_hide_seconds is sent as null
 *  (inherit/default). */
const saveLayout = async (plugin: OverlayPlugin) => {
  if (isSaving.value) return
  const draft = layoutDrafts[plugin.id]
  if (!draft) return
  const payload: Record<string, unknown> = {
    position: draft.position,
    display_mode: draft.display_mode,
    z_order: Number(draft.z_order) || 0
  }
  const w = Number(draft.width)
  payload.width = Number.isFinite(w) && w > 0 ? Math.round(w) : null
  const h = Number(draft.height)
  payload.height = Number.isFinite(h) && h > 0 ? Math.round(h) : null
  const scale = Number(draft.scale)
  payload.scale = Number.isFinite(scale) && scale > 0 ? scale : null
  const idle = Number(draft.idle_hide_seconds)
  payload.idle_hide_seconds = Number.isFinite(idle) && idle > 0 ? idle : null
  isSaving.value = true
  statusMessage.value = ''
  try {
    const result = await overlayStore.updatePluginLayout(plugin.id, payload)
    // Reflect the effective layout the backend persisted back into the draft.
    layoutDrafts[plugin.id] = result.layout
    showStatus('success', t('settings.touchOverlay.layout.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('settings.touchOverlay.layout.failed'))
  } finally {
    isSaving.value = false
  }
}

onMounted(async () => {
  // Settings already fetches the full config, but guard for a direct tab visit
  // or a config blob that only has the workflow-config allowlist. The overlay
  // fields (enabled_plugins, idle_hide_seconds, etc.) are read live from the
  // shared config blob, so the full config must be present for the per-plugin
  // list and the global idle fade below.
  const ov = config.value?.overlay
  if (!config.value || Object.keys(config.value).length === 0 || typeof ov?.enabled !== 'boolean') {
    await configStore.fetchConfig()
  }
  await overlayStore.fetchPlugins()
  syncFromConfig()
})

watch(
  () => [config.value?.overlay?.idle_hide_seconds],
  () => {
    if (!isSaving.value) syncFromConfig()
  }
)
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

      <FieldRow
        :label="t('settings.touchOverlay.idleHideSeconds.label')"
        :help="t('settings.touchOverlay.idleHideSeconds.help')"
      >
        <NumberField
          v-model="overlay.idle_hide_seconds"
          :min="0"
          :step="0.5"
          unit="s"
          @update:model-value="saveIdle()"
        />
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
        v-else-if="plugins.length === 0"
        class="py-4 text-center text-sm text-gray-500 dark:text-gray-400"
      >
        {{ t('settings.touchOverlay.pluginConfig.noPlugins') }}
      </div>

      <div v-else :class="{ 'pointer-events-none opacity-50': !enabled }">
        <p v-if="!enabled" class="mb-4 text-xs leading-relaxed text-amber-700 dark:text-amber-300">
          {{ t('settings.touchOverlay.pluginConfig.disabledHint') }}
        </p>
        <ul class="divide-y divide-gray-100 dark:divide-gray-700/60">
          <li v-for="plugin in plugins" :key="plugin.id" class="py-4 first:pt-0 last:pb-0">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span v-if="plugin.icon" class="text-base leading-none">{{ plugin.icon }}</span>
                  <span class="truncate text-sm font-semibold text-gray-900 dark:text-white">
                    {{ plugin.name || plugin.id }}
                  </span>
                  <span
                    v-if="enabledPlugins.includes(plugin.id)"
                    class="inline-flex items-center rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300"
                  >
                    {{ t('settings.touchOverlay.pluginConfig.activatedBadge') }}
                  </span>
                  <span
                    v-else
                    class="inline-flex items-center rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-500 dark:bg-gray-700/60 dark:text-gray-400"
                  >
                    {{ t('settings.touchOverlay.pluginConfig.inactiveBadge') }}
                  </span>
                </div>
                <p v-if="plugin.description" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {{ plugin.description }}
                </p>
              </div>
              <div class="flex flex-shrink-0 items-center gap-4">
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
                <button
                  type="button"
                  class="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-600 transition-colors hover:text-indigo-500 dark:text-indigo-400"
                  @click="openLayout(plugin)"
                >
                  <Square2StackIcon class="h-4 w-4" />
                  {{
                    layoutPluginId === plugin.id
                      ? t('settings.touchOverlay.layout.hideLayout')
                      : t('settings.touchOverlay.layout.editLayout')
                  }}
                </button>
              </div>
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

            <!-- Per-plugin layout editor (#754): shown for every discovered
                 plugin (active or not). Position, display mode, size, z-order,
                 and a per-plugin idle fade (0 = inherit the global value above). -->
            <div
              v-if="layoutPluginId === plugin.id"
              class="mt-4 rounded-lg border border-gray-100 bg-gray-50 p-4 dark:border-gray-700/60 dark:bg-gray-900/30"
            >
              <h4
                class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
              >
                {{ t('settings.touchOverlay.layout.title') }}
              </h4>
              <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-position`"
                    >{{ t('settings.touchOverlay.layout.position') }}</label
                  >
                  <select
                    :id="`layout-${plugin.id}-position`"
                    v-model="ensureDraft(plugin)['position']"
                    class="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                  >
                    <option v-for="a in ANCHORS" :key="a" :value="a">{{ a }}</option>
                  </select>
                </div>
                <div v-if="plugin.size">
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-scale`"
                    >{{ t('settings.touchOverlay.layout.scale') }}</label
                  >
                  <NumberField
                    :model-value="(ensureDraft(plugin)['scale'] as number) ?? 0"
                    :min="0"
                    :step="0.1"
                    @update:model-value="ensureDraft(plugin)['scale'] = $event"
                  />
                </div>
                <div>
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-display-mode`"
                    >{{ t('settings.touchOverlay.layout.displayMode') }}</label
                  >
                  <SegmentedControl
                    :model-value="ensureDraft(plugin)['display_mode'] as string"
                    :options="[
                      {
                        value: 'persistent',
                        label: t('settings.touchOverlay.displayMode.persistent')
                      },
                      {
                        value: 'auto_hide',
                        label: t('settings.touchOverlay.displayMode.autoHide')
                      }
                    ]"
                    @update:model-value="ensureDraft(plugin)['display_mode'] = $event as string"
                  />
                </div>
                <div v-if="!plugin.size">
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-width`"
                    >{{ t('settings.touchOverlay.layout.width') }}</label
                  >
                  <NumberField
                    :model-value="(ensureDraft(plugin)['width'] as number) ?? 0"
                    :min="0"
                    :step="10"
                    unit="px"
                    @update:model-value="ensureDraft(plugin)['width'] = $event"
                  />
                </div>
                <div v-if="!plugin.size">
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-height`"
                    >{{ t('settings.touchOverlay.layout.height') }}</label
                  >
                  <NumberField
                    :model-value="(ensureDraft(plugin)['height'] as number) ?? 0"
                    :min="0"
                    :step="10"
                    unit="px"
                    @update:model-value="ensureDraft(plugin)['height'] = $event"
                  />
                </div>
                <div>
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-z-order`"
                    >{{ t('settings.touchOverlay.layout.zOrder') }}</label
                  >
                  <NumberField
                    :model-value="(ensureDraft(plugin)['z_order'] as number) ?? 0"
                    :min="0"
                    :step="1"
                    @update:model-value="ensureDraft(plugin)['z_order'] = $event"
                  />
                </div>
                <div>
                  <label
                    class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                    :for="`layout-${plugin.id}-idle`"
                    >{{ t('settings.touchOverlay.layout.idleHideSeconds') }}</label
                  >
                  <NumberField
                    :model-value="(ensureDraft(plugin)['idle_hide_seconds'] as number) ?? 0"
                    :min="0"
                    :step="0.5"
                    unit="s"
                    @update:model-value="ensureDraft(plugin)['idle_hide_seconds'] = $event"
                  />
                </div>
              </div>
              <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">
                {{ t('settings.touchOverlay.layout.inheritHint') }}
              </p>
              <div class="mt-3 flex justify-end">
                <button
                  type="button"
                  :disabled="isSaving"
                  class="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white transition-colors hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-60"
                  @click="saveLayout(plugin)"
                >
                  <CheckIcon class="h-4 w-4" />
                  {{ isSaving ? t('common.saving') : t('settings.touchOverlay.layout.save') }}
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
