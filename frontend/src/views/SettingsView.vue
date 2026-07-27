<script setup lang="ts">
import { computed, onErrorCaptured, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useConfigStore, useSystemStore, type AuthScope, type PicframeServiceStatus } from '../stores/config'
import { useI18n } from 'vue-i18n'
import configSchema from '../configSchema.json'
import HardwareInputsEditor from '../components/HardwareInputsEditor.vue'
import ColorField from '../components/settings/ColorField.vue'
import FieldRow from '../components/settings/FieldRow.vue'
import FixedChoiceListEditor from '../components/settings/FixedChoiceListEditor.vue'
import GeocodeKeyListEditor from '../components/settings/GeocodeKeyListEditor.vue'
import NumberField from '../components/settings/NumberField.vue'
import PathPicker from '../components/settings/PathPicker.vue'
import PasswordField from '../components/settings/PasswordField.vue'
import SegmentedControl from '../components/settings/SegmentedControl.vue'
import SettingsSection from '../components/settings/SettingsSection.vue'
import ShaderPicker from '../components/settings/ShaderPicker.vue'
import SortRulesEditor from '../components/settings/SortRulesEditor.vue'
import ToggleSwitch from '../components/settings/ToggleSwitch.vue'
import TokenListEditor from '../components/settings/TokenListEditor.vue'
import ActionBar from '../components/ui/ActionBar.vue'
import EmptyState from '../components/ui/EmptyState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import StatusBanner from '../components/ui/StatusBanner.vue'
import {
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ArrowUpTrayIcon,
  CheckCircleIcon,
  Cog6ToothIcon,
  ExclamationTriangleIcon,
  PowerIcon,
  TrashIcon
} from '@heroicons/vue/24/outline'

const { t } = useI18n()
const configStore = useConfigStore()
const systemStore = useSystemStore()

const { config, isLoading: isConfigLoading, error: configError, filterOptions, locales, authConfig } = storeToRefs(configStore)
const { error: systemError } = storeToRefs(systemStore)

const localConfig = ref<Record<string, any>>({})
const localAuthConfig = ref({
  enabled: false,
  username: 'admin',
  scope: 'none' as AuthScope,
  password_set: false,
  password: ''
})
const activeTab = ref('viewer')
const showConfirmModal = ref(false)
const showServiceRestartModal = ref(false)
const serviceRestartStatus = ref<PicframeServiceStatus | null>(null)
const picframeServiceStatus = ref<PicframeServiceStatus | null>(null)
const confirmAction = ref<(() => Promise<void>) | null>(null)
const confirmActionHandlesSuccess = ref(false)
const confirmMessage = ref('')
const successMessage = ref('')
const renderError = ref<any>(null)
const CLOCK_FORMAT_24 = '%H:%M'
const CLOCK_FORMAT_12 = '%-I:%M %p'
type ClockFormatMode = '24' | '12' | 'custom'
const clockFormatModeOverride = ref<ClockFormatMode | null>(null)

const tabs = [
  { id: 'viewer', labelKey: 'config.viewer._title' },
  { id: 'model', labelKey: 'config.model._title' },
  { id: 'mqtt', labelKey: 'config.mqtt._title' },
  { id: 'http', labelKey: 'config.http._title' },
  { id: 'hardware_inputs', labelKey: 'config.hardware_inputs._title' }
]

const matStyleOptions = [
  'float',
  'float_polaroid',
  'float_color_wrap',
  'single_bevel',
  'double_bevel',
  'double_flat'
]

const geocodeKeyChoices = [
  'tourism',
  'amenity',
  'historic',
  'leisure',
  'shop',
  'office',
  'building',
  'isolated_dwelling',
  'farm',
  'house_number',
  'road',
  'pedestrian',
  'square',
  'suburb',
  'village',
  'hamlet',
  'town',
  'city_district',
  'borough',
  'quarter',
  'neighbourhood',
  'city',
  'municipality',
  'county',
  'local_administrative_area',
  'region',
  'state',
  'province',
  'state_district',
  'country',
  'country_code'
].map(value => ({ value }))

const imageExtensionChoices = ['.jpg', '.jpeg', '.png', '.heic', '.heif'].map(value => ({ value }))
const videoExtensionChoices = ['.mp4', '.mkv', '.flv', '.mov', '.avi', '.webm', '.hevc'].map(value => ({ value }))
const imageFileExtensions = imageExtensionChoices.map(choice => choice.value)
const fontExtensions = ['.ttf', '.otf']
const certificateExtensions = ['.pem', '.crt', '.cer', '.key']
const logLevelOptions = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
const serviceRestartViewerKeys = ['use_glx', 'use_sdl2']
const authScopeOptions = computed(() => [
  { value: 'none', label: t('settings.auth.scopeNone') },
  { value: 'settings', label: t('settings.auth.scopeSettings') },
  { value: 'site', label: t('settings.auth.scopeSite') }
])

onErrorCaptured((err, _instance, info) => {
  console.error('SettingsView Error:', err, info)
  renderError.value = { message: err instanceof Error ? err.message : String(err), info }
  return false
})

onMounted(async () => {
  await configStore.fetchConfig()
  await configStore.fetchAuthConfig()
  await configStore.fetchLocales()
  await configStore.fetchFilterOptions()
  await refreshPicframeServiceStatus()
})

watch(() => config.value, (newConfig) => {
  if (!newConfig || Object.keys(newConfig).length === 0) return
  clockFormatModeOverride.value = null
  localConfig.value = initializeConfig(newConfig)
}, { immediate: true, deep: true })

watch(() => authConfig.value, (newAuthConfig) => {
  const scope = normalizeAuthScope(newAuthConfig.scope, newAuthConfig.enabled)
  localAuthConfig.value = {
    enabled: scope !== 'none',
    username: newAuthConfig.username || 'admin',
    scope,
    password_set: Boolean(newAuthConfig.password_set),
    password: newAuthConfig.password || ''
  }
}, { immediate: true, deep: true })

watch(() => activeTab.value, (tab) => {
  if (tab === 'danger') {
    void refreshPicframeServiceStatus()
  }
})

const sortColumns = computed(() => filterOptions.value.sort_columns || [])
const localeOptions = computed(() => {
  const savedLocale = localConfig.value.model?.locale
  const installedLocales = locales.value || []
  if (savedLocale && !installedLocales.includes(savedLocale)) {
    return [savedLocale, ...installedLocales]
  }
  return installedLocales
})

function detectedClockFormatMode(value: unknown): ClockFormatMode {
  if (value === CLOCK_FORMAT_24) return '24'
  if (value === CLOCK_FORMAT_12) return '12'
  return 'custom'
}

const clockFormatMode = computed<ClockFormatMode>({
  get() {
    if (clockFormatModeOverride.value === 'custom') {
      return 'custom'
    }
    return detectedClockFormatMode(localConfig.value.viewer?.clock_format)
  },
  set(mode) {
    if (!localConfig.value.viewer) return
    if (mode === '24') {
      localConfig.value.viewer.clock_format = CLOCK_FORMAT_24
      clockFormatModeOverride.value = null
      return
    }
    if (mode === '12') {
      localConfig.value.viewer.clock_format = CLOCK_FORMAT_12
      clockFormatModeOverride.value = null
      return
    }
    clockFormatModeOverride.value = 'custom'
  }
})

const displayMode = computed({
  get: () => {
    const viewer = localConfig.value.viewer || {}
    const widthUnset = viewer.display_w === null || viewer.display_w === ''
    const heightUnset = viewer.display_h === null || viewer.display_h === ''
    const x = Number(viewer.display_x || 0)
    const y = Number(viewer.display_y || 0)
    return widthUnset && heightUnset && x === 0 && y === 0 ? 'fullscreen' : 'custom'
  },
  set: (mode: string | number | boolean | null) => {
    setDisplayMode(String(mode || 'fullscreen'))
  }
})

function initializeConfig(newConfig: Record<string, any>) {
  const getFallbackValue = (type: string) => {
    switch (type) {
      case 'boolean': return false
      case 'integer': return 0
      case 'float': return 0.0
      case 'array': return []
      case 'object': return {}
      default: return ''
    }
  }

  const initialized: Record<string, any> = {}
  for (const [section, props] of Object.entries(configSchema)) {
    initialized[section] = {}
    for (const [key, propDef] of Object.entries(props as Record<string, any>)) {
      if (key === '_title') continue
      if (propDef.type === 'object' && propDef.properties) {
        initialized[section][key] = {}
        for (const [subKey, subPropDef] of Object.entries(propDef.properties as Record<string, any>)) {
          if (subKey === '_title') continue
          initialized[section][key][subKey] = newConfig?.[section]?.[key]?.[subKey] ??
            getFallbackValue((subPropDef as any).type || 'string')
        }
      } else {
        initialized[section][key] = newConfig?.[section]?.[key] ?? getFallbackValue((propDef as any).type)
      }
    }
  }
  initialized.hardware_inputs = {
    enabled: Boolean(newConfig?.hardware_inputs?.enabled),
    inputs: newConfig?.hardware_inputs?.inputs || {}
  }
  return initialized
}

function sectionHelp(section: string, key: string) {
  return t(`config.${section}.${key}`, '')
}

function formatLabel(key: string | undefined | null) {
  if (!key) return ''
  return String(key).split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

function normalizeAuthScope(value: unknown, enabled?: boolean): AuthScope {
  if (value === 'none' || value === 'settings' || value === 'site') {
    return value
  }
  return enabled ? 'settings' : 'none'
}

function serviceRestartSettingsChanged() {
  const savedViewer = config.value?.viewer || {}
  const draftViewer = localConfig.value?.viewer || {}
  return serviceRestartViewerKeys.some(key => Boolean(savedViewer[key]) !== Boolean(draftViewer[key]))
}

function restoreServiceRestartSettings() {
  const savedViewer = config.value?.viewer || {}
  const draftViewer = localConfig.value?.viewer
  if (!draftViewer) return
  for (const key of serviceRestartViewerKeys) {
    draftViewer[key] = Boolean(savedViewer[key])
  }
}

async function persistSettings(successText: string) {
  await configStore.saveConfig(localConfig.value)
  await configStore.saveAuthConfig({
    ...localAuthConfig.value,
    enabled: localAuthConfig.value.scope !== 'none'
  })
  showSuccess(successText)
}

async function saveConfig() {
  if (serviceRestartSettingsChanged()) {
    try {
      serviceRestartStatus.value = await systemStore.fetchPicframeServiceStatus()
    } catch (e) {
      serviceRestartStatus.value = {
        status: 'unavailable',
        active: false,
        restart_available: false,
        message: systemError.value || t('settings.serviceRestartUnavailable')
      }
    }
    showServiceRestartModal.value = true
    return
  }

  try {
    await persistSettings(t('settings.saved'))
  } catch (e) {
    // Store exposes the error.
  }
}

function cancelServiceRestartSave() {
  restoreServiceRestartSettings()
  showServiceRestartModal.value = false
}

async function saveServiceRestartLater() {
  try {
    await persistSettings(t('settings.savedRestartLater'))
    showServiceRestartModal.value = false
  } catch (e) {
    // Store exposes the error.
  }
}

async function saveAndRestartService() {
  try {
    await persistSettings(t('settings.savedRestarting'))
  } catch (e) {
    // Store exposes the error.
    return
  }
  try {
    const result = await systemStore.restartPicframeService()
    showServiceRestartModal.value = false
    if (result?.status === 'manual_required') {
      showSuccess(result.message || t('settings.savedRestartLater'))
      return
    }
    showSuccess(t('settings.savedRestarting'))
  } catch (e) {
    showServiceRestartModal.value = false
    showSuccess(t('settings.savedRestartLater'))
  }
}

async function retryLoadSettings() {
  await configStore.fetchConfig()
  await configStore.fetchAuthConfig()
  await configStore.fetchLocales()
  await configStore.fetchFilterOptions()
}

function unavailablePicframeServiceStatus(message?: string | null): PicframeServiceStatus {
  return {
    status: 'unavailable',
    active: false,
    restart_available: false,
    message: message || t('settings.serviceRestartUnavailable')
  }
}

async function refreshPicframeServiceStatus(): Promise<PicframeServiceStatus> {
  try {
    const status = await systemStore.fetchPicframeServiceStatus()
    picframeServiceStatus.value = status
    return status
  } catch (e) {
    const status = unavailablePicframeServiceStatus(systemError.value)
    picframeServiceStatus.value = status
    return status
  }
}

async function restartPicframeServiceFromDangerZone() {
  const status = await refreshPicframeServiceStatus()
  if (!status.restart_available) {
    showSuccess(status.message || t('settings.picframeRestartManualRequired'))
    return
  }
  try {
    const result = await systemStore.restartPicframeService()
    if (result?.status === 'manual_required') {
      await refreshPicframeServiceStatus()
      showSuccess(result.message || t('settings.picframeRestartManualRequired'))
      return
    }
    showSuccess(t('settings.picframeRestartRequested'))
  } catch (e) {
    showSuccess(t('settings.picframeRestartRequested'))
  }
}

function showSuccess(msg: string) {
  successMessage.value = msg
  setTimeout(() => {
    successMessage.value = ''
  }, 3000)
}

function triggerConfirm(action: () => Promise<void>, message: string, handlesSuccess = false) {
  confirmAction.value = action
  confirmActionHandlesSuccess.value = handlesSuccess
  confirmMessage.value = message
  showConfirmModal.value = true
}

async function executeConfirm() {
  if (!confirmAction.value) return
  try {
    await confirmAction.value()
    showConfirmModal.value = false
    if (!confirmActionHandlesSuccess.value) {
      showSuccess(t('settings.actionCompleted'))
    }
  } catch (e) {
    showConfirmModal.value = false
  } finally {
    confirmActionHandlesSuccess.value = false
  }
}

function exportConfig() {
  const dataStr = 'data:text/json;charset=utf-8,' +
    encodeURIComponent(JSON.stringify(localConfig.value, null, 2))
  const downloadAnchorNode = document.createElement('a')
  downloadAnchorNode.setAttribute('href', dataStr)
  downloadAnchorNode.setAttribute('download', 'picframe_config.json')
  document.body.appendChild(downloadAnchorNode)
  downloadAnchorNode.click()
  downloadAnchorNode.remove()
}

async function importConfig(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  const isYaml = file.name.toLowerCase().endsWith('.yaml') ||
    file.name.toLowerCase().endsWith('.yml')

  if (isYaml) {
    const formData = new FormData()
    formData.append('file', file)
    try {
      const response = await fetch('/api/config/import-yaml', {
        method: 'POST',
        body: formData
      })
      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || t('settings.importFailed'))
      }
      await configStore.fetchConfig()
      showSuccess(t('settings.imported'))
    } catch (err) {
      alert(err instanceof Error ? err.message : t('settings.importFailed'))
    }
  } else {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const imported = JSON.parse(e.target?.result as string)
        localConfig.value = initializeConfig(imported)
        showSuccess(t('settings.importedNeedsSave'))
      } catch (err) {
        alert(t('settings.invalidJson'))
      }
    }
    reader.readAsText(file)
  }
  target.value = ''
}

function matImagesMode() {
  const value = localConfig.value.viewer?.mat_images
  if (value === false || value === 'false' || value === 'off' || value === 0) return 'disabled'
  if (value === true || value === 'true' || value === 'on') return 'always'
  return 'threshold'
}

function setMatImagesMode(mode: string | number | boolean | null) {
  if (mode === 'disabled') localConfig.value.viewer.mat_images = false
  else if (mode === 'always') localConfig.value.viewer.mat_images = true
  else localConfig.value.viewer.mat_images = Number(localConfig.value.viewer.mat_images) || 0.01
}

function matTypesArray() {
  const value = localConfig.value.viewer?.mat_type
  if (!value) return []
  return String(value).split(/\s+/).filter(Boolean)
}

function setMatTypesArray(values: string[]) {
  localConfig.value.viewer.mat_type = values.length ? values.join(' ') : null
}

function setDisplayMode(mode: string) {
  if (!localConfig.value.viewer) return
  if (mode === 'fullscreen') {
    localConfig.value.viewer.display_x = 0
    localConfig.value.viewer.display_y = 0
    localConfig.value.viewer.display_w = null
    localConfig.value.viewer.display_h = null
    return
  }
  if (localConfig.value.viewer.display_w === null || localConfig.value.viewer.display_w === '') {
    localConfig.value.viewer.display_w = '800'
  }
  if (localConfig.value.viewer.display_h === null || localConfig.value.viewer.display_h === '') {
    localConfig.value.viewer.display_h = '480'
  }
}

function setViewerInteger(
  key: string,
  event: Event,
  options: { min?: number, nullable?: boolean } = {}
) {
  if (!localConfig.value.viewer) return
  const rawValue = (event.target as HTMLInputElement).value
  if (options.nullable && rawValue === '') {
    localConfig.value.viewer[key] = null
    return
  }
  const numericValue = Number(rawValue)
  if (!Number.isFinite(numericValue)) return
  const rounded = Math.round(numericValue)
  const nextValue = options.min === undefined ? rounded : Math.max(options.min, rounded)
  localConfig.value.viewer[key] = options.nullable ? String(nextValue) : nextValue
}

function backgroundHex() {
  const value = localConfig.value.viewer?.background
  const channels = Array.isArray(value) ? value : [0, 0, 0]
  const hex = channels.slice(0, 3).map((channel: unknown) => {
    let numeric = Number(channel)
    if (!Number.isFinite(numeric)) numeric = 0
    if (numeric >= 0 && numeric <= 1) numeric *= 255
    return Math.round(Math.max(0, Math.min(255, numeric))).toString(16).padStart(2, '0')
  })
  return `#${hex.join('')}`
}

function setBackgroundColor(event: Event) {
  if (!localConfig.value.viewer) return
  const value = (event.target as HTMLInputElement).value
  const match = /^#([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$/.exec(value)
  if (!match) return
  const alpha = Array.isArray(localConfig.value.viewer.background)
    ? Number(localConfig.value.viewer.background[3] ?? 1)
    : 1
  localConfig.value.viewer.background = [
    parseInt(match[1], 16) / 255,
    parseInt(match[2], 16) / 255,
    parseInt(match[3], 16) / 255,
    Number.isFinite(alpha) ? alpha : 1
  ]
}
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
    <div v-if="renderError" class="rounded border-l-4 border-red-500 bg-red-100 p-4 text-red-700 shadow-sm">
      <h3 class="text-lg font-bold">{{ t('settings.renderErrorTitle') }}</h3>
      <p class="mt-2 font-mono text-sm">{{ renderError.message }}</p>
      <p class="mt-1 text-xs text-red-500">{{ t('settings.renderErrorContext', { context: renderError.info }) }}</p>
      <button class="mt-4 rounded bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700" @click="renderError = null">{{ t('common.dismiss') }}</button>
    </div>

    <template v-else>
      <PageHeader :title="t('settings.title')">
        <template #icon>
          <div class="rounded-lg bg-indigo-50 p-3 dark:bg-indigo-500/10">
            <Cog6ToothIcon class="h-7 w-7 text-indigo-600 dark:text-indigo-400" />
          </div>
        </template>
        <template #actions>
        <ActionBar>
          <button class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700" @click="exportConfig">
            <ArrowDownTrayIcon class="mr-2 h-4 w-4" />
            {{ t('settings.export') }}
          </button>
          <label class="inline-flex cursor-pointer items-center rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700">
            <ArrowUpTrayIcon class="mr-2 h-4 w-4" />
            {{ t('settings.import') }}
            <input type="file" accept=".json,.yaml,.yml,application/json,application/x-yaml,text/yaml" class="hidden" @change="importConfig">
          </label>
          <button :disabled="isConfigLoading" class="inline-flex items-center rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white shadow-sm transition-colors hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-50" @click="saveConfig">
            <ArrowPathIcon v-if="isConfigLoading" class="mr-2 h-4 w-4 animate-spin" />
            <CheckCircleIcon v-else class="mr-2 h-4 w-4" />
            {{ isConfigLoading ? t('settings.saving') : t('settings.save') }}
          </button>
        </ActionBar>
        </template>
      </PageHeader>

      <StatusBanner
        v-if="configError"
        tone="danger"
        :title="t('settings.configUnavailableTitle')"
        :message="t('settings.configUnavailable')"
      />
      <StatusBanner
        v-if="systemError"
        tone="danger"
        :title="t('common.systemError')"
        :message="systemError"
      />
      <StatusBanner v-if="successMessage" tone="success" :message="successMessage" />

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <nav class="h-fit rounded-lg border border-gray-200 bg-white p-2 shadow-sm dark:border-gray-700 dark:bg-gray-800/90 lg:sticky lg:top-6">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            type="button"
            :class="[activeTab === tab.id ? 'bg-indigo-50 font-semibold text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'text-gray-600 hover:bg-gray-50 dark:text-gray-400 dark:hover:bg-gray-700/50', 'block w-full rounded-md px-4 py-3 text-left text-sm transition-colors']"
            @click="activeTab = tab.id"
          >
            {{ t(tab.labelKey, formatLabel(tab.id)) }}
          </button>
          <div class="my-2 border-t border-gray-200 dark:border-gray-700"></div>
          <button
            type="button"
            :class="[activeTab === 'danger' ? 'bg-red-50 font-semibold text-red-700 dark:bg-red-500/10 dark:text-red-300' : 'text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-500/10', 'block w-full rounded-md px-4 py-3 text-left text-sm transition-colors']"
            @click="activeTab = 'danger'"
          >
            {{ t('settings.dangerZone') }}
          </button>
        </nav>

        <main class="min-h-[600px] rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
          <div v-if="configError && activeTab !== 'danger' && !localConfig[activeTab]" class="p-6 sm:p-8">
            <EmptyState :title="t('settings.configUnavailableTitle')" :message="t('settings.configUnavailable')">
              <template #icon>
                <ExclamationTriangleIcon class="h-10 w-10" />
              </template>
              <template #actions>
                <button
                  type="button"
                  class="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60"
                  @click="retryLoadSettings"
                >
                  {{ t('common.retry') }}
                </button>
              </template>
            </EmptyState>
          </div>
          <section v-else-if="activeTab === 'viewer' && localConfig.viewer" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.viewer._title') }}</h2>

            <SettingsSection
              id="settings-viewer-image-surface"
              :title="t('settings.domain.imageSurface')"
              :description="t('settings.domain.imageSurfaceDescription')"
              default-open
            >
              <FieldRow :label="formatLabel('fit')" :help="sectionHelp('viewer', 'fit')">
                <ToggleSwitch v-model="localConfig.viewer.fit" />
              </FieldRow>
              <FieldRow :label="formatLabel('kenburns')" :help="sectionHelp('viewer', 'kenburns')">
                <ToggleSwitch v-model="localConfig.viewer.kenburns" />
              </FieldRow>
              <FieldRow :label="formatLabel('video_fit_display')" :help="sectionHelp('viewer', 'video_fit_display')">
                <ToggleSwitch v-model="localConfig.viewer.video_fit_display" />
              </FieldRow>
              <FieldRow :label="formatLabel('blend_type')" :help="sectionHelp('viewer', 'blend_type')">
                <select v-model="localConfig.viewer.blend_type" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="blend">blend</option>
                  <option value="burn">burn</option>
                  <option value="bump">bump</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('fps')" :help="sectionHelp('viewer', 'fps')">
                <NumberField v-model="localConfig.viewer.fps" :min="1" :max="120" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('background')" :help="sectionHelp('viewer', 'background')">
                <div class="flex items-center gap-3">
                  <input
                    type="color"
                    :value="backgroundHex()"
                    class="h-10 w-14 rounded border border-gray-300 bg-white p-1 dark:border-gray-600 dark:bg-gray-700"
                    @input="setBackgroundColor"
                  >
                  <span class="text-sm font-mono text-gray-600 dark:text-gray-300">{{ backgroundHex() }}</span>
                </div>
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-viewer-display"
              :title="t('settings.domain.display')"
              :description="t('settings.domain.displayDescription')"
            >
              <FieldRow :label="t('settings.displayMode')" :help="sectionHelp('viewer', 'display_w')">
                <SegmentedControl v-model="displayMode" :options="[{ value: 'fullscreen', label: t('settings.fullscreen') }, { value: 'custom', label: t('settings.custom') }]" />
              </FieldRow>
              <div v-if="displayMode === 'custom'" class="grid grid-cols-1 gap-4 rounded-lg border border-gray-200 p-4 dark:border-gray-700 sm:grid-cols-2">
                <label class="space-y-1.5">
                  <span class="block text-sm font-semibold text-gray-900 dark:text-white">{{ formatLabel('display_x') }}</span>
                  <input :value="localConfig.viewer.display_x" type="number" step="1" class="block w-full min-w-0 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white" @input="setViewerInteger('display_x', $event)">
                  <span v-if="sectionHelp('viewer', 'display_x')" class="block text-xs leading-relaxed text-gray-500 dark:text-gray-400">{{ sectionHelp('viewer', 'display_x') }}</span>
                </label>
                <label class="space-y-1.5">
                  <span class="block text-sm font-semibold text-gray-900 dark:text-white">{{ formatLabel('display_y') }}</span>
                  <input :value="localConfig.viewer.display_y" type="number" step="1" class="block w-full min-w-0 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white" @input="setViewerInteger('display_y', $event)">
                  <span v-if="sectionHelp('viewer', 'display_y')" class="block text-xs leading-relaxed text-gray-500 dark:text-gray-400">{{ sectionHelp('viewer', 'display_y') }}</span>
                </label>
                <label class="space-y-1.5">
                  <span class="block text-sm font-semibold text-gray-900 dark:text-white">{{ formatLabel('display_w') }}</span>
                  <input :value="localConfig.viewer.display_w ?? ''" type="number" min="1" step="1" class="block w-full min-w-0 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white" @input="setViewerInteger('display_w', $event, { min: 1, nullable: true })">
                  <span v-if="sectionHelp('viewer', 'display_w')" class="block text-xs leading-relaxed text-gray-500 dark:text-gray-400">{{ sectionHelp('viewer', 'display_w') }}</span>
                </label>
                <label class="space-y-1.5">
                  <span class="block text-sm font-semibold text-gray-900 dark:text-white">{{ formatLabel('display_h') }}</span>
                  <input :value="localConfig.viewer.display_h ?? ''" type="number" min="1" step="1" class="block w-full min-w-0 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white" @input="setViewerInteger('display_h', $event, { min: 1, nullable: true })">
                  <span v-if="sectionHelp('viewer', 'display_h')" class="block text-xs leading-relaxed text-gray-500 dark:text-gray-400">{{ sectionHelp('viewer', 'display_h') }}</span>
                </label>
              </div>
              <FieldRow :label="formatLabel('display_hdmi')" :help="sectionHelp('viewer', 'display_hdmi')">
                <input v-model="localConfig.viewer.display_hdmi" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-viewer-text-clock"
              :title="t('settings.domain.textAndClock')"
              :description="t('settings.domain.textAndClockDescription')"
            >
              <FieldRow :label="formatLabel('text_justify')" :help="sectionHelp('viewer', 'text_justify')">
                <SegmentedControl v-model="localConfig.viewer.text_justify" :options="[{ value: 'L', label: 'Left' }, { value: 'C', label: 'Center' }, { value: 'R', label: 'Right' }]" />
              </FieldRow>
              <FieldRow :label="formatLabel('show_text_sz')" :help="sectionHelp('viewer', 'show_text_sz')">
                <NumberField v-model="localConfig.viewer.show_text_sz" :min="8" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('show_text_fm')" :help="sectionHelp('viewer', 'show_text_fm')">
                <select v-model="localConfig.viewer.show_text_fm" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="%b %d, %Y">Jan 31, 2026</option>
                  <option value="%Y-%m-%d">2026-01-31</option>
                  <option value="%d.%m.%Y">31.01.2026</option>
                  <option :value="localConfig.viewer.show_text_fm">Custom: {{ localConfig.viewer.show_text_fm }}</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('show_text_tm')" :help="sectionHelp('viewer', 'show_text_tm')">
                <NumberField v-model="localConfig.viewer.show_text_tm" :min="0" :step="1" unit="s" />
              </FieldRow>
              <FieldRow :label="formatLabel('text_opacity')" :help="sectionHelp('viewer', 'text_opacity')">
                <NumberField v-model="localConfig.viewer.text_opacity" :min="0" :max="1" :step="0.05" />
              </FieldRow>
              <FieldRow :label="formatLabel('text_bkg_hgt')" :help="sectionHelp('viewer', 'text_bkg_hgt')">
                <NumberField v-model="localConfig.viewer.text_bkg_hgt" :min="0" :max="1" :step="0.05" />
              </FieldRow>
              <FieldRow :label="formatLabel('text_x_margin')" :help="sectionHelp('viewer', 'text_x_margin')">
                <NumberField v-model="localConfig.viewer.text_x_margin" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('text_y_margin')" :help="sectionHelp('viewer', 'text_y_margin')">
                <NumberField v-model="localConfig.viewer.text_y_margin" :step="1" />
              </FieldRow>
              <FieldRow :label="t('settings.clockHourMode')" :help="t('settings.clockHourModeHelp')">
                <div class="space-y-3">
                  <SegmentedControl
                    v-model="clockFormatMode"
                    :options="[
                      { value: '24', label: t('settings.clock24Hour') },
                      { value: '12', label: t('settings.clock12Hour') },
                      { value: 'custom', label: t('settings.clockCustom') }
                    ]"
                  />
                  <input
                    v-if="clockFormatMode === 'custom'"
                    v-model="localConfig.viewer.clock_format"
                    type="text"
                    :aria-label="t('settings.clockCustomFormat')"
                    class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                  >
                </div>
              </FieldRow>
              <FieldRow :label="formatLabel('clock_extra_source')" :help="sectionHelp('viewer', 'clock_extra_source')">
                <select v-model="localConfig.viewer.clock_extra_source" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="off">{{ t('settings.clockExtraSourceOff') }}</option>
                  <option value="clock_txt">{{ t('settings.clockExtraSourceClockTxt') }}</option>
                  <option value="ui_text">{{ t('settings.clockExtraSourceUiText') }}</option>
                </select>
              </FieldRow>
              <FieldRow v-if="localConfig.viewer.clock_extra_source === 'ui_text'" :label="formatLabel('clock_extra_text')" :help="sectionHelp('viewer', 'clock_extra_text')">
                <input v-model="localConfig.viewer.clock_extra_text" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('clock_top_bottom')" :help="sectionHelp('viewer', 'clock_top_bottom')">
                <SegmentedControl v-model="localConfig.viewer.clock_top_bottom" :options="[{ value: 'T', label: 'Top' }, { value: 'B', label: 'Bottom' }]" />
              </FieldRow>
              <FieldRow :label="formatLabel('clock_justify')" :help="sectionHelp('viewer', 'clock_justify')">
                <SegmentedControl v-model="localConfig.viewer.clock_justify" :options="[{ value: 'L', label: 'Left' }, { value: 'C', label: 'Center' }, { value: 'R', label: 'Right' }]" />
              </FieldRow>
              <FieldRow :label="formatLabel('clock_text_sz')" :help="sectionHelp('viewer', 'clock_text_sz')">
                <NumberField v-model="localConfig.viewer.clock_text_sz" :min="8" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('clock_opacity')" :help="sectionHelp('viewer', 'clock_opacity')">
                <NumberField v-model="localConfig.viewer.clock_opacity" :min="0" :max="1" :step="0.05" />
              </FieldRow>
              <FieldRow :label="formatLabel('clock_wdt_offset_pct')" :help="sectionHelp('viewer', 'clock_wdt_offset_pct')">
                <NumberField v-model="localConfig.viewer.clock_wdt_offset_pct" :step="0.5" unit="%" />
              </FieldRow>
              <FieldRow :label="formatLabel('clock_hgt_offset_pct')" :help="sectionHelp('viewer', 'clock_hgt_offset_pct')">
                <NumberField v-model="localConfig.viewer.clock_hgt_offset_pct" :step="0.5" unit="%" />
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-viewer-matting-edges"
              :title="t('settings.domain.mattingEdges')"
              :description="t('settings.domain.mattingEdgesDescription')"
            >
              <FieldRow :label="formatLabel('mat_images')" :help="sectionHelp('viewer', 'mat_images')">
                <div class="space-y-3">
                  <SegmentedControl :model-value="matImagesMode()" :options="[{ value: 'disabled', label: 'Disabled' }, { value: 'always', label: 'Always' }, { value: 'threshold', label: 'Aspect threshold' }]" @update:model-value="setMatImagesMode" />
                  <NumberField v-if="matImagesMode() === 'threshold'" v-model="localConfig.viewer.mat_images" :min="0" :step="0.01" />
                </div>
              </FieldRow>
              <FieldRow :label="formatLabel('mat_type')" :help="sectionHelp('viewer', 'mat_type')">
                <TokenListEditor :model-value="matTypesArray()" placeholder="float" @update:model-value="setMatTypesArray" />
                <div class="mt-2 flex flex-wrap gap-2">
                  <button v-for="style in matStyleOptions" :key="style" type="button" class="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700" @click="setMatTypesArray([...new Set([...matTypesArray(), style])])">{{ style }}</button>
                  <button type="button" class="rounded-md border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700" @click="setMatTypesArray([])">All styles</button>
                </div>
              </FieldRow>
              <FieldRow :label="formatLabel('outer_mat_color')" :help="sectionHelp('viewer', 'outer_mat_color')">
                <ColorField v-model="localConfig.viewer.outer_mat_color" />
              </FieldRow>
              <FieldRow :label="formatLabel('inner_mat_color')" :help="sectionHelp('viewer', 'inner_mat_color')">
                <ColorField v-model="localConfig.viewer.inner_mat_color" />
              </FieldRow>
              <FieldRow :label="formatLabel('outer_mat_use_texture')" :help="sectionHelp('viewer', 'outer_mat_use_texture')">
                <ToggleSwitch v-model="localConfig.viewer.outer_mat_use_texture" />
              </FieldRow>
              <FieldRow :label="formatLabel('inner_mat_use_texture')" :help="sectionHelp('viewer', 'inner_mat_use_texture')">
                <ToggleSwitch v-model="localConfig.viewer.inner_mat_use_texture" />
              </FieldRow>
              <FieldRow :label="formatLabel('outer_mat_border')" :help="sectionHelp('viewer', 'outer_mat_border')">
                <NumberField v-model="localConfig.viewer.outer_mat_border" :min="0" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('inner_mat_border')" :help="sectionHelp('viewer', 'inner_mat_border')">
                <NumberField v-model="localConfig.viewer.inner_mat_border" :min="0" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('blur_amount')" :help="sectionHelp('viewer', 'blur_amount')">
                <NumberField v-model="localConfig.viewer.blur_amount" :min="0" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('blur_zoom')" :help="sectionHelp('viewer', 'blur_zoom')">
                <NumberField v-model="localConfig.viewer.blur_zoom" :min="0" :step="0.05" />
              </FieldRow>
              <FieldRow :label="formatLabel('blur_edges')" :help="sectionHelp('viewer', 'blur_edges')">
                <ToggleSwitch v-model="localConfig.viewer.blur_edges" />
              </FieldRow>
              <FieldRow :label="formatLabel('edge_alpha')" :help="sectionHelp('viewer', 'edge_alpha')">
                <NumberField v-model="localConfig.viewer.edge_alpha" :min="0" :max="1" :step="0.05" />
              </FieldRow>
              <FieldRow :label="formatLabel('mat_resource_folder')" :help="sectionHelp('viewer', 'mat_resource_folder')">
                <PathPicker v-model="localConfig.viewer.mat_resource_folder" kind="directory" />
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-viewer-renderer-backend"
              :title="t('settings.domain.rendererBackend')"
              :description="t('settings.domain.rendererBackendDescription')"
            >
              <FieldRow :label="formatLabel('font_file')" :help="sectionHelp('viewer', 'font_file')">
                <PathPicker v-model="localConfig.viewer.font_file" kind="file" :extensions="fontExtensions" />
              </FieldRow>
              <FieldRow :label="formatLabel('shader')" :help="sectionHelp('viewer', 'shader')">
                <ShaderPicker v-model="localConfig.viewer.shader" />
              </FieldRow>
              <FieldRow :label="formatLabel('max_software_decode_resolution')" :help="sectionHelp('viewer', 'max_software_decode_resolution')">
                <select v-model="localConfig.viewer.max_software_decode_resolution" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="640x480">640x480</option>
                  <option value="1280x720">1280x720</option>
                  <option value="1920x1080">1920x1080</option>
                  <option :value="localConfig.viewer.max_software_decode_resolution">Custom: {{ localConfig.viewer.max_software_decode_resolution }}</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('use_glx')" :help="sectionHelp('viewer', 'use_glx')">
                <div class="space-y-2">
                  <ToggleSwitch v-model="localConfig.viewer.use_glx" />
                  <p class="text-xs leading-relaxed text-amber-700 dark:text-amber-300">{{ t('settings.serviceRestartInline') }}</p>
                </div>
              </FieldRow>
              <FieldRow :label="formatLabel('use_sdl2')" :help="sectionHelp('viewer', 'use_sdl2')">
                <div class="space-y-2">
                  <ToggleSwitch v-model="localConfig.viewer.use_sdl2" />
                  <p class="text-xs leading-relaxed text-amber-700 dark:text-amber-300">{{ t('settings.serviceRestartInline') }}</p>
                </div>
              </FieldRow>
            </SettingsSection>
          </section>

          <section v-else-if="activeTab === 'model' && localConfig.model" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.model._title') }}</h2>
            <SettingsSection
              id="settings-model-media-roots"
              :title="t('settings.domain.mediaRoots')"
              :description="t('settings.domain.mediaRootsDescription')"
              default-open
            >
              <FieldRow :label="formatLabel('pic_dir')" :help="sectionHelp('model', 'pic_dir')">
                <PathPicker v-model="localConfig.model.pic_dir" kind="directory" allow-missing />
              </FieldRow>
              <FieldRow :label="formatLabel('deleted_pictures')" :help="sectionHelp('model', 'deleted_pictures')">
                <PathPicker v-model="localConfig.model.deleted_pictures" kind="directory" allow-missing />
              </FieldRow>
              <FieldRow :label="formatLabel('no_files_img')" :help="sectionHelp('model', 'no_files_img')">
                <PathPicker v-model="localConfig.model.no_files_img" kind="file" :extensions="imageFileExtensions" />
              </FieldRow>
              <FieldRow :label="formatLabel('follow_links')" :help="sectionHelp('model', 'follow_links')">
                <ToggleSwitch v-model="localConfig.model.follow_links" />
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-model-playlist"
              :title="t('settings.domain.playlist')"
              :description="t('settings.domain.playlistDescription')"
            >
              <FieldRow :label="formatLabel('recent_n')" :help="sectionHelp('model', 'recent_n')">
                <NumberField v-model="localConfig.model.recent_n" :min="0" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('reshuffle_num')" :help="sectionHelp('model', 'reshuffle_num')">
                <NumberField v-model="localConfig.model.reshuffle_num" :min="1" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('sort_cols')" :help="sectionHelp('model', 'sort_cols')">
                <SortRulesEditor v-model="localConfig.model.sort_cols" :columns="sortColumns" />
              </FieldRow>
              <FieldRow :label="formatLabel('image_extensions')" :help="sectionHelp('model', 'image_extensions')">
                <FixedChoiceListEditor v-model="localConfig.model.image_extensions" :choices="imageExtensionChoices" />
              </FieldRow>
              <FieldRow :label="formatLabel('video_extensions')" :help="sectionHelp('model', 'video_extensions')">
                <FixedChoiceListEditor v-model="localConfig.model.video_extensions" :choices="videoExtensionChoices" />
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-model-geocoding-locale"
              :title="t('settings.domain.geocodingLocale')"
              :description="t('settings.domain.geocodingLocaleDescription')"
            >
              <FieldRow :label="formatLabel('locale')" :help="sectionHelp('model', 'locale')">
                <select v-model="localConfig.model.locale" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option v-for="locale in localeOptions" :key="locale" :value="locale">{{ locale }}</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('load_geoloc')" :help="sectionHelp('model', 'load_geoloc')">
                <ToggleSwitch v-model="localConfig.model.load_geoloc" />
              </FieldRow>
              <FieldRow :label="formatLabel('geo_key')" :help="sectionHelp('model', 'geo_key')">
                <input v-model="localConfig.model.geo_key" type="email" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="t('settings.geocoding.locationFormat')" :help="sectionHelp('model', 'key_list')">
                <GeocodeKeyListEditor v-model="localConfig.model.key_list" :choices="geocodeKeyChoices" />
              </FieldRow>
              <FieldRow v-if="localConfig.viewer" :label="formatLabel('geo_suppress_list')" :help="sectionHelp('viewer', 'geo_suppress_list')">
                <TokenListEditor v-model="localConfig.viewer.geo_suppress_list" placeholder="County" />
              </FieldRow>
            </SettingsSection>

            <SettingsSection
              id="settings-model-logging"
              :title="t('settings.domain.logging')"
              :description="t('settings.domain.loggingDescription')"
            >
              <FieldRow :label="formatLabel('log_level')" :help="sectionHelp('model', 'log_level')">
                <select v-model="localConfig.model.log_level" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option v-for="level in logLevelOptions" :key="level" :value="level">{{ level }}</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('log_file')" :help="sectionHelp('model', 'log_file')">
                <PathPicker v-model="localConfig.model.log_file" kind="file" allow-missing />
              </FieldRow>
            </SettingsSection>
          </section>

          <section v-else-if="activeTab === 'mqtt' && localConfig.mqtt" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.mqtt._title') }}</h2>
            <SettingsSection
              id="settings-mqtt-broker"
              :title="t('settings.domain.mqttBroker')"
              :description="t('settings.domain.mqttBrokerDescription')"
              default-open
            >
              <FieldRow :label="formatLabel('use_mqtt')" :help="sectionHelp('mqtt', 'use_mqtt')">
                <ToggleSwitch v-model="localConfig.mqtt.use_mqtt" />
              </FieldRow>
              <FieldRow :label="formatLabel('server')" :help="sectionHelp('mqtt', 'server')">
                <input v-model="localConfig.mqtt.server" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('port')" :help="sectionHelp('mqtt', 'port')">
                <NumberField v-model="localConfig.mqtt.port" :min="1" :max="65535" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('login')" :help="sectionHelp('mqtt', 'login')">
                <input v-model="localConfig.mqtt.login" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('password')" :help="sectionHelp('mqtt', 'password')">
                <PasswordField v-model="localConfig.mqtt.password" />
              </FieldRow>
              <FieldRow :label="formatLabel('tls')" :help="sectionHelp('mqtt', 'tls')">
                <PathPicker v-model="localConfig.mqtt.tls" kind="file" :extensions="certificateExtensions" allow-missing />
              </FieldRow>
            </SettingsSection>
            <SettingsSection
              id="settings-mqtt-device"
              :title="t('settings.domain.mqttDevice')"
              :description="t('settings.domain.mqttDeviceDescription')"
            >
              <FieldRow :label="formatLabel('device_id')" :help="sectionHelp('mqtt', 'device_id')">
                <input v-model="localConfig.mqtt.device_id" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('device_url')" :help="sectionHelp('mqtt', 'device_url')">
                <input v-model="localConfig.mqtt.device_url" type="url" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
            </SettingsSection>
          </section>

          <section v-else-if="activeTab === 'http' && localConfig.http" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.http._title') }}</h2>
            <SettingsSection
              id="settings-http-access"
              :title="t('settings.domain.httpAccess')"
              :description="t('settings.domain.httpAccessDescription')"
              default-open
            >
              <FieldRow :label="t('settings.auth.scope')" :help="t('settings.auth.scopeHelp')">
                <div class="space-y-2" role="radiogroup" :aria-label="t('settings.auth.scope')">
                  <label
                    v-for="option in authScopeOptions"
                    :key="option.value"
                    class="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors"
                    :class="localAuthConfig.scope === option.value ? 'border-indigo-500 bg-indigo-50 text-indigo-900 dark:border-indigo-400 dark:bg-indigo-500/10 dark:text-indigo-100' : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'"
                  >
                    <input
                      v-model="localAuthConfig.scope"
                      type="radio"
                      name="auth-scope"
                      :value="option.value"
                      class="h-4 w-4 border-gray-300 text-indigo-600 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700"
                    >
                    <span class="font-medium">{{ option.label }}</span>
                  </label>
                </div>
              </FieldRow>
              <template v-if="localAuthConfig.scope !== 'none'">
                <FieldRow :label="t('settings.auth.username')" :help="t('settings.auth.usernameHelp')">
                  <input v-model="localAuthConfig.username" type="text" autocomplete="username" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                </FieldRow>
                <FieldRow :label="t('settings.auth.password')" :help="localAuthConfig.password_set ? t('settings.auth.passwordPreserveHelp') : t('settings.auth.passwordHelp')">
                  <PasswordField v-model="localAuthConfig.password" />
                </FieldRow>
              </template>
            </SettingsSection>
            <SettingsSection
              id="settings-http-browser-api"
              :title="t('settings.domain.httpBrowserApi')"
              :description="t('settings.domain.httpBrowserApiDescription')"
            >
              <FieldRow :label="formatLabel('cors_allowed_origins')" :help="sectionHelp('http', 'cors_allowed_origins')">
                <TokenListEditor v-model="localConfig.http.cors_allowed_origins" placeholder="http://localhost:5173" />
              </FieldRow>
            </SettingsSection>
            <SettingsSection
              id="settings-http-realtime"
              :title="t('settings.domain.httpRealtime')"
              :description="t('settings.domain.httpRealtimeDescription')"
            >
              <FieldRow :label="formatLabel('websocket_broadcast_rate_limit')" :help="sectionHelp('http', 'websocket_broadcast_rate_limit')">
                <NumberField v-model="localConfig.http.websocket_broadcast_rate_limit" :min="1" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('websocket_broadcast_capacity')" :help="sectionHelp('http', 'websocket_broadcast_capacity')">
                <NumberField v-model="localConfig.http.websocket_broadcast_capacity" :min="1" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('command_debounce_ms')" :help="sectionHelp('http', 'command_debounce_ms')">
                <NumberField v-model="localConfig.http.command_debounce_ms" :min="0" :step="10" />
              </FieldRow>
            </SettingsSection>
          </section>

          <section v-else-if="activeTab === 'hardware_inputs' && localConfig.hardware_inputs" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.hardware_inputs._title') }}</h2>
            <SettingsSection
              id="settings-hardware-inputs"
              :title="t('config.hardware_inputs._title')"
              :description="t('settings.domain.hardwareInputsDescription')"
              default-open
            >
              <HardwareInputsEditor v-model="localConfig.hardware_inputs" />
            </SettingsSection>
          </section>

          <section v-else-if="activeTab === 'danger'" class="space-y-6 p-6 sm:p-8">
            <div class="flex items-center gap-3 border-b border-red-100 pb-4 dark:border-red-900/30">
              <ExclamationTriangleIcon class="h-8 w-8 text-red-600 dark:text-red-500" />
              <h2 class="text-2xl font-bold text-red-600 dark:text-red-500">{{ t('settings.dangerZone') }}</h2>
            </div>
            <SettingsSection
              id="settings-danger-maintenance"
              :title="t('settings.domain.maintenance')"
              :description="t('settings.domain.maintenanceDescription')"
              tone="danger"
              default-open
            >
              <div class="flex flex-col justify-between gap-4 rounded-lg border border-red-100 bg-red-50 p-5 dark:border-red-500/20 dark:bg-red-500/5 sm:flex-row sm:items-center">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.purgeDb') }}</h3>
                  <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.domain.purgeHelp') }}</p>
                </div>
                <button class="inline-flex items-center justify-center rounded-lg bg-red-100 px-4 py-2 font-medium text-red-700 transition-colors hover:bg-red-200 dark:bg-red-600 dark:text-white dark:hover:bg-red-700" @click="triggerConfirm(systemStore.purgeDatabase, t('settings.purgeDb'))">
                  <TrashIcon class="mr-2 h-5 w-5" />
                  {{ t('settings.domain.purge') }}
                </button>
              </div>
              <div class="flex flex-col justify-between gap-4 rounded-lg border border-red-100 bg-red-50 p-5 dark:border-red-500/20 dark:bg-red-500/5 sm:flex-row sm:items-center">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.clearCache') }}</h3>
                  <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.domain.clearCacheHelp') }}</p>
                </div>
                <button class="inline-flex items-center justify-center rounded-lg bg-red-100 px-4 py-2 font-medium text-red-700 transition-colors hover:bg-red-200 dark:bg-red-600 dark:text-white dark:hover:bg-red-700" @click="triggerConfirm(systemStore.clearCache, t('settings.clearCache'))">
                  <TrashIcon class="mr-2 h-5 w-5" />
                  {{ t('settings.domain.clear') }}
                </button>
              </div>
              <div class="flex flex-col justify-between gap-4 rounded-lg border border-red-100 bg-red-50 p-5 dark:border-red-500/20 dark:bg-red-500/5 sm:flex-row sm:items-center">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.restartPicframeService') }}</h3>
                  <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.domain.restartPicframeServiceHelp') }}</p>
                  <p class="mt-2 text-sm font-medium" :class="picframeServiceStatus?.restart_available ? 'text-green-700 dark:text-green-400' : 'text-amber-700 dark:text-amber-300'">
                    {{ picframeServiceStatus?.restart_available ? t('settings.domain.restartPicframeServiceActive') : t('settings.domain.restartPicframeServiceUnavailable') }}
                  </p>
                </div>
                <button
                  :disabled="!picframeServiceStatus?.restart_available"
                  class="inline-flex items-center justify-center rounded-lg bg-red-100 px-4 py-2 font-medium text-red-700 transition-colors hover:bg-red-200 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-red-600 dark:text-white dark:hover:bg-red-700"
                  @click="triggerConfirm(restartPicframeServiceFromDangerZone, t('settings.restartPicframeService'), true)"
                >
                  <ArrowPathIcon class="mr-2 h-5 w-5" />
                  {{ t('settings.domain.restartPicframeService') }}
                </button>
              </div>
              <div class="flex flex-col justify-between gap-4 rounded-lg border border-red-100 bg-red-50 p-5 dark:border-red-500/20 dark:bg-red-500/5 sm:flex-row sm:items-center">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.reboot') }}</h3>
                  <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.domain.rebootHelp') }}</p>
                </div>
                <button class="inline-flex items-center justify-center rounded-lg bg-red-100 px-4 py-2 font-medium text-red-700 transition-colors hover:bg-red-200 dark:bg-red-600 dark:text-white dark:hover:bg-red-700" @click="triggerConfirm(systemStore.reboot, t('settings.reboot'))">
                  <ArrowPathIcon class="mr-2 h-5 w-5" />
                  {{ t('settings.reboot') }}
                </button>
              </div>
              <div class="flex flex-col justify-between gap-4 rounded-lg border border-red-100 bg-red-50 p-5 dark:border-red-500/20 dark:bg-red-500/5 sm:flex-row sm:items-center">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.shutdown') }}</h3>
                  <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.domain.shutdownHelp') }}</p>
                </div>
                <button class="inline-flex items-center justify-center rounded-lg bg-red-100 px-4 py-2 font-medium text-red-700 transition-colors hover:bg-red-200 dark:bg-red-600 dark:text-white dark:hover:bg-red-700" @click="triggerConfirm(systemStore.shutdown, t('settings.shutdown'))">
                  <PowerIcon class="mr-2 h-5 w-5" />
                  {{ t('settings.shutdown') }}
                </button>
              </div>
            </SettingsSection>
          </section>
        </main>
      </div>

      <div v-if="showServiceRestartModal" class="relative z-50" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-gray-900/80"></div>
        <div class="fixed inset-0 z-50 flex min-h-full items-center justify-center p-4">
          <div class="w-full max-w-xl overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-800">
            <div class="p-6">
              <div class="flex gap-4">
                <div class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-amber-100 dark:bg-amber-900/30">
                  <ExclamationTriangleIcon class="h-6 w-6 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.serviceRestartTitle') }}</h3>
                  <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">{{ t('settings.serviceRestartBody') }}</p>
                  <p class="mt-3 text-sm font-medium" :class="serviceRestartStatus?.restart_available ? 'text-green-700 dark:text-green-400' : 'text-amber-700 dark:text-amber-300'">
                    {{ serviceRestartStatus?.restart_available ? t('settings.serviceRestartActive') : t('settings.serviceRestartInactive') }}
                  </p>
                  <p v-if="serviceRestartStatus?.message" class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ serviceRestartStatus.message }}</p>
                </div>
              </div>
            </div>
            <div class="flex flex-col-reverse gap-3 border-t border-gray-100 bg-gray-50 px-6 py-4 dark:border-gray-700 dark:bg-gray-800/50 sm:flex-row sm:justify-end">
              <button type="button" class="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:ring-gray-600 dark:hover:bg-gray-600" @click="cancelServiceRestartSave">{{ t('settings.cancel') }}</button>
              <button type="button" class="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:ring-gray-600 dark:hover:bg-gray-600" @click="saveServiceRestartLater">{{ t('settings.saveRestartLater') }}</button>
              <button v-if="serviceRestartStatus?.restart_available" type="button" class="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500" @click="saveAndRestartService">{{ t('settings.saveAndRestart') }}</button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="showConfirmModal" class="relative z-50" role="dialog" aria-modal="true">
        <div class="fixed inset-0 bg-gray-500/75 dark:bg-gray-900/80"></div>
        <div class="fixed inset-0 z-50 flex min-h-full items-center justify-center p-4">
          <div class="w-full max-w-lg overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl dark:border-gray-700 dark:bg-gray-800">
            <div class="p-6">
              <div class="flex gap-4">
                <div class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/30">
                  <ExclamationTriangleIcon class="h-6 w-6 text-red-600 dark:text-red-500" />
                </div>
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.confirm') }}</h3>
                  <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">
                    {{ t('settings.confirmAction') }}
                    <span class="mt-2 block font-medium text-gray-900 dark:text-gray-300">{{ confirmMessage }}</span>
                  </p>
                </div>
              </div>
            </div>
            <div class="flex flex-col-reverse gap-3 border-t border-gray-100 bg-gray-50 px-6 py-4 dark:border-gray-700 dark:bg-gray-800/50 sm:flex-row sm:justify-end">
              <button type="button" class="rounded-lg bg-white px-3 py-2 text-sm font-semibold text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 dark:bg-gray-700 dark:text-gray-200 dark:ring-gray-600 dark:hover:bg-gray-600" @click="showConfirmModal = false">{{ t('settings.cancel') }}</button>
              <button type="button" class="rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-500" @click="executeConfirm">{{ t('settings.confirm') }}</button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
