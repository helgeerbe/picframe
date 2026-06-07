<script setup lang="ts">
import { computed, onErrorCaptured, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useConfigStore, useSystemStore } from '../stores/config'
import { useI18n } from 'vue-i18n'
import configSchema from '../configSchema.json'
import HardwareInputsEditor from '../components/HardwareInputsEditor.vue'
import AdvancedDisclosure from '../components/settings/AdvancedDisclosure.vue'
import ColorField from '../components/settings/ColorField.vue'
import FieldRow from '../components/settings/FieldRow.vue'
import FilterExpressionEditor from '../components/settings/FilterExpressionEditor.vue'
import FixedChoiceListEditor from '../components/settings/FixedChoiceListEditor.vue'
import GeocodeKeyListEditor from '../components/settings/GeocodeKeyListEditor.vue'
import KeyboardShortcutCapture from '../components/settings/KeyboardShortcutCapture.vue'
import NumberField from '../components/settings/NumberField.vue'
import OrderedChipEditor from '../components/settings/OrderedChipEditor.vue'
import PathPicker from '../components/settings/PathPicker.vue'
import PasswordField from '../components/settings/PasswordField.vue'
import SegmentedControl from '../components/settings/SegmentedControl.vue'
import ShaderPicker from '../components/settings/ShaderPicker.vue'
import SortRulesEditor from '../components/settings/SortRulesEditor.vue'
import ToggleSwitch from '../components/settings/ToggleSwitch.vue'
import TokenListEditor from '../components/settings/TokenListEditor.vue'
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

const { config, isLoading: isConfigLoading, error: configError, filterOptions } = storeToRefs(configStore)
const { error: systemError } = storeToRefs(systemStore)

const localConfig = ref<Record<string, any>>({})
const activeTab = ref('viewer')
const showConfirmModal = ref(false)
const confirmAction = ref<(() => Promise<void>) | null>(null)
const confirmMessage = ref('')
const successMessage = ref('')
const renderError = ref<any>(null)

const tabs = [
  { id: 'viewer', labelKey: 'config.viewer._title' },
  { id: 'model', labelKey: 'config.model._title' },
  { id: 'mqtt', labelKey: 'config.mqtt._title' },
  { id: 'http', labelKey: 'config.http._title' },
  { id: 'peripherals', labelKey: 'config.peripherals._title' },
  { id: 'hardware_inputs', labelKey: 'config.hardware_inputs._title' }
]

const textOverlayOptions = [
  { value: 'title', label: t('remote.overlays.textTitle') },
  { value: 'caption', label: t('remote.overlays.textCaption') },
  { value: 'name', label: t('remote.overlays.textName') },
  { value: 'date', label: t('remote.overlays.textDate') },
  { value: 'folder', label: t('remote.overlays.textFolder') },
  { value: 'location', label: t('remote.overlays.textLocation') }
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

const imageAttributeChoices = [
  'PICFRAME GPS',
  'PICFRAME LOCATION',
  'EXIF FNumber',
  'EXIF ExposureTime',
  'EXIF ISOSpeedRatings',
  'EXIF FocalLength',
  'EXIF DateTimeOriginal',
  'Image Model',
  'Image Make',
  'IPTC Caption/Abstract',
  'IPTC Object Name',
  'IPTC Keywords'
].map(value => ({ value }))

const imageExtensionChoices = ['.jpg', '.jpeg', '.png', '.heic', '.heif'].map(value => ({ value }))
const videoExtensionChoices = ['.mp4', '.mkv', '.flv', '.mov', '.avi', '.webm', '.hevc'].map(value => ({ value }))
const imageFileExtensions = imageExtensionChoices.map(choice => choice.value)
const fontExtensions = ['.ttf', '.otf']
const certificateExtensions = ['.pem', '.crt', '.cer', '.key']

onErrorCaptured((err, _instance, info) => {
  console.error('SettingsView Error:', err, info)
  renderError.value = { message: err instanceof Error ? err.message : String(err), info }
  return false
})

onMounted(async () => {
  await configStore.fetchConfig()
  await configStore.fetchFilterOptions()
})

watch(() => config.value, (newConfig) => {
  if (!newConfig || Object.keys(newConfig).length === 0) return
  localConfig.value = initializeConfig(newConfig)
}, { immediate: true, deep: true })

const sortColumns = computed(() => filterOptions.value.sort_columns || [])
const locationOptions = computed(() => filterOptions.value.locations || [])
const tagOptions = computed(() => filterOptions.value.tags || [])

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

function nestedHelp(section: string, key: string, subKey: string) {
  return t(`config.${section}.${key}.${subKey}`, '')
}

function formatLabel(key: string | undefined | null) {
  if (!key) return ''
  return String(key).split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}

async function saveConfig() {
  try {
    await configStore.saveConfig(localConfig.value)
    showSuccess(t('settings.saved'))
  } catch (e) {
    // Store exposes the error.
  }
}

function showSuccess(msg: string) {
  successMessage.value = msg
  setTimeout(() => {
    successMessage.value = ''
  }, 3000)
}

function triggerConfirm(action: () => Promise<void>, message: string) {
  confirmAction.value = action
  confirmMessage.value = message
  showConfirmModal.value = true
}

async function executeConfirm() {
  if (!confirmAction.value) return
  try {
    await confirmAction.value()
    showConfirmModal.value = false
    showSuccess(t('settings.actionCompleted'))
  } catch (e) {
    showConfirmModal.value = false
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
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
    <div v-if="renderError" class="rounded border-l-4 border-red-500 bg-red-100 p-4 text-red-700 shadow-sm">
      <h3 class="text-lg font-bold">Component Crash Detected</h3>
      <p class="mt-2 font-mono text-sm">{{ renderError.message }}</p>
      <p class="mt-1 text-xs text-red-500">Context: {{ renderError.info }}</p>
      <button class="mt-4 rounded bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700" @click="renderError = null">Dismiss</button>
    </div>

    <template v-else>
      <div class="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div class="flex items-center gap-3">
          <div class="rounded-lg bg-indigo-50 p-3 dark:bg-indigo-500/10">
            <Cog6ToothIcon class="h-7 w-7 text-indigo-600 dark:text-indigo-400" />
          </div>
          <h1 class="text-3xl font-bold tracking-tight text-gray-900 dark:text-white">{{ t('settings.title') }}</h1>
        </div>

        <div class="flex flex-wrap items-center gap-3">
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
        </div>
      </div>

      <div v-if="configError || systemError" class="rounded-r-lg border-l-4 border-red-500 bg-red-50 p-4 dark:bg-red-900/20">
        <p class="text-sm text-red-700 dark:text-red-400">{{ configError || systemError }}</p>
      </div>
      <div v-if="successMessage" class="rounded-r-lg border-l-4 border-green-500 bg-green-50 p-4 dark:bg-green-900/20">
        <p class="text-sm font-medium text-green-700 dark:text-green-400">{{ successMessage }}</p>
      </div>

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
          <section v-if="activeTab === 'viewer' && localConfig.viewer" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.viewer._title') }}</h2>

            <div class="space-y-5">
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
            </div>

            <section class="space-y-5">
              <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.domain.textAndClock') }}</h3>
              <FieldRow :label="formatLabel('show_text_enabled')" :help="sectionHelp('viewer', 'show_text_enabled')">
                <ToggleSwitch v-model="localConfig.viewer.show_text_enabled" />
              </FieldRow>
              <FieldRow :label="formatLabel('text_overlay_format')" :help="sectionHelp('viewer', 'text_overlay_format')">
                <OrderedChipEditor v-model="localConfig.viewer.text_overlay_format" :options="textOverlayOptions" />
              </FieldRow>
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
              <FieldRow :label="formatLabel('show_clock')" :help="sectionHelp('viewer', 'show_clock')">
                <ToggleSwitch v-model="localConfig.viewer.show_clock" />
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
            </section>

            <section class="space-y-5">
              <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.domain.matting') }}</h3>
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
              <FieldRow :label="formatLabel('outer_mat_border')" :help="sectionHelp('viewer', 'outer_mat_border')">
                <NumberField v-model="localConfig.viewer.outer_mat_border" :min="0" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('inner_mat_border')" :help="sectionHelp('viewer', 'inner_mat_border')">
                <NumberField v-model="localConfig.viewer.inner_mat_border" :min="0" :step="1" />
              </FieldRow>
            </section>

            <AdvancedDisclosure :title="t('settings.domain.advanced')" :description="t('settings.domain.advancedDescription')">
              <FieldRow :label="formatLabel('font_file')" :help="sectionHelp('viewer', 'font_file')">
                <PathPicker v-model="localConfig.viewer.font_file" kind="file" :extensions="fontExtensions" />
              </FieldRow>
              <FieldRow :label="formatLabel('shader')" :help="sectionHelp('viewer', 'shader')">
                <ShaderPicker v-model="localConfig.viewer.shader" />
              </FieldRow>
              <FieldRow :label="formatLabel('mat_resource_folder')" :help="sectionHelp('viewer', 'mat_resource_folder')">
                <PathPicker v-model="localConfig.viewer.mat_resource_folder" kind="directory" />
              </FieldRow>
              <FieldRow :label="formatLabel('max_software_decode_resolution')" :help="sectionHelp('viewer', 'max_software_decode_resolution')">
                <select v-model="localConfig.viewer.max_software_decode_resolution" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="640x480">640x480</option>
                  <option value="1280x720">1280x720</option>
                  <option value="1920x1080">1920x1080</option>
                  <option :value="localConfig.viewer.max_software_decode_resolution">Custom: {{ localConfig.viewer.max_software_decode_resolution }}</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('display_hdmi')" :help="sectionHelp('viewer', 'display_hdmi')">
                <input v-model="localConfig.viewer.display_hdmi" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('fps')" :help="sectionHelp('viewer', 'fps')">
                <NumberField v-model="localConfig.viewer.fps" :min="1" :max="120" :step="1" />
              </FieldRow>
            </AdvancedDisclosure>
          </section>

          <section v-else-if="activeTab === 'model' && localConfig.model" class="space-y-8 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.model._title') }}</h2>
            <div class="space-y-5">
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
              <FieldRow :label="formatLabel('portrait_pairs')" :help="sectionHelp('model', 'portrait_pairs')">
                <ToggleSwitch v-model="localConfig.model.portrait_pairs" />
              </FieldRow>
            </div>

            <section class="space-y-5">
              <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.domain.playlist') }}</h3>
              <FieldRow :label="formatLabel('date_from')" :help="sectionHelp('model', 'date_from')">
                <input v-model="localConfig.model.date_from" type="date" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('date_to')" :help="sectionHelp('model', 'date_to')">
                <input v-model="localConfig.model.date_to" type="date" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('shuffle')" :help="sectionHelp('model', 'shuffle')">
                <ToggleSwitch v-model="localConfig.model.shuffle" />
              </FieldRow>
              <FieldRow :label="formatLabel('shuffle_mode')" :help="sectionHelp('model', 'shuffle_mode')">
                <select v-model="localConfig.model.shuffle_mode" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="standard">{{ t('remote.controls.shuffleModeStandard') }}</option>
                  <option value="fewer_repeats">{{ t('remote.controls.shuffleModeFewerRepeats') }}</option>
                </select>
              </FieldRow>
              <FieldRow :label="formatLabel('sort_cols')" :help="sectionHelp('model', 'sort_cols')">
                <SortRulesEditor v-model="localConfig.model.sort_cols" :columns="sortColumns" />
              </FieldRow>
              <FieldRow :label="formatLabel('location_filter')" :help="sectionHelp('model', 'location_filter')">
                <FilterExpressionEditor v-model="localConfig.model.location_filter" :options="locationOptions" placeholder="Berlin OR Hamburg" />
              </FieldRow>
              <FieldRow :label="formatLabel('tags_filter')" :help="sectionHelp('model', 'tags_filter')">
                <FilterExpressionEditor v-model="localConfig.model.tags_filter" :options="tagOptions" placeholder="family AND holiday" />
              </FieldRow>
            </section>

            <section class="space-y-5">
              <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.domain.geocoding') }}</h3>
              <FieldRow :label="formatLabel('load_geoloc')" :help="sectionHelp('model', 'load_geoloc')">
                <ToggleSwitch v-model="localConfig.model.load_geoloc" />
              </FieldRow>
              <FieldRow :label="formatLabel('geo_key')" :help="sectionHelp('model', 'geo_key')">
                <input v-model="localConfig.model.geo_key" type="email" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('geo_suppress_list')" :help="sectionHelp('model', 'geo_suppress_list')">
                <TokenListEditor v-model="localConfig.model.geo_suppress_list" placeholder="County" />
              </FieldRow>
              <FieldRow :label="t('settings.geocoding.locationFormat')" :help="sectionHelp('model', 'key_list')">
                <GeocodeKeyListEditor v-model="localConfig.model.key_list" :choices="geocodeKeyChoices" />
              </FieldRow>
            </section>

            <AdvancedDisclosure :title="t('settings.domain.advanced')" :description="t('settings.domain.advancedDescription')">
              <FieldRow :label="formatLabel('image_extensions')" :help="sectionHelp('model', 'image_extensions')">
                <FixedChoiceListEditor v-model="localConfig.model.image_extensions" :choices="imageExtensionChoices" />
              </FieldRow>
              <FieldRow :label="formatLabel('video_extensions')" :help="sectionHelp('model', 'video_extensions')">
                <FixedChoiceListEditor v-model="localConfig.model.video_extensions" :choices="videoExtensionChoices" />
              </FieldRow>
              <FieldRow :label="formatLabel('image_attr')" :help="sectionHelp('model', 'image_attr')">
                <FixedChoiceListEditor v-model="localConfig.model.image_attr" :choices="imageAttributeChoices" />
              </FieldRow>
              <FieldRow :label="formatLabel('log_file')" :help="sectionHelp('model', 'log_file')">
                <PathPicker v-model="localConfig.model.log_file" kind="file" allow-missing />
              </FieldRow>
              <FieldRow :label="formatLabel('log_level')" :help="sectionHelp('model', 'log_level')">
                <select v-model="localConfig.model.log_level" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                  <option value="CRITICAL">CRITICAL</option>
                </select>
              </FieldRow>
            </AdvancedDisclosure>
          </section>

          <section v-else-if="activeTab === 'mqtt' && localConfig.mqtt" class="space-y-5 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.mqtt._title') }}</h2>
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
            <AdvancedDisclosure :title="t('settings.domain.advanced')" :description="t('settings.domain.advancedDescription')">
              <FieldRow :label="formatLabel('device_id')" :help="sectionHelp('mqtt', 'device_id')">
                <input v-model="localConfig.mqtt.device_id" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('device_url')" :help="sectionHelp('mqtt', 'device_url')">
                <input v-model="localConfig.mqtt.device_url" type="url" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
            </AdvancedDisclosure>
          </section>

          <section v-else-if="activeTab === 'http' && localConfig.http" class="space-y-5 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.http._title') }}</h2>
            <FieldRow :label="formatLabel('auth')" :help="sectionHelp('http', 'auth')">
              <ToggleSwitch v-model="localConfig.http.auth" />
            </FieldRow>
            <FieldRow :label="formatLabel('username')" :help="sectionHelp('http', 'username')">
              <input v-model="localConfig.http.username" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
            </FieldRow>
            <FieldRow :label="formatLabel('password')" :help="sectionHelp('http', 'password')">
              <PasswordField v-model="localConfig.http.password" />
            </FieldRow>
            <FieldRow :label="formatLabel('use_ssl')" :help="sectionHelp('http', 'use_ssl')">
              <ToggleSwitch v-model="localConfig.http.use_ssl" />
            </FieldRow>
            <FieldRow :label="formatLabel('keyfile')" :help="sectionHelp('http', 'keyfile')">
              <PathPicker v-model="localConfig.http.keyfile" kind="file" :extensions="certificateExtensions" allow-missing />
            </FieldRow>
            <FieldRow :label="formatLabel('certfile')" :help="sectionHelp('http', 'certfile')">
              <PathPicker v-model="localConfig.http.certfile" kind="file" :extensions="certificateExtensions" allow-missing />
            </FieldRow>
            <FieldRow :label="formatLabel('cors_allowed_origins')" :help="sectionHelp('http', 'cors_allowed_origins')">
              <TokenListEditor v-model="localConfig.http.cors_allowed_origins" placeholder="http://localhost:5173" />
            </FieldRow>
            <AdvancedDisclosure :title="t('settings.domain.advanced')" :description="t('settings.domain.advancedDescription')">
              <FieldRow :label="formatLabel('websocket_broadcast_rate_limit')" :help="sectionHelp('http', 'websocket_broadcast_rate_limit')">
                <NumberField v-model="localConfig.http.websocket_broadcast_rate_limit" :min="1" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('websocket_broadcast_capacity')" :help="sectionHelp('http', 'websocket_broadcast_capacity')">
                <NumberField v-model="localConfig.http.websocket_broadcast_capacity" :min="1" :step="1" />
              </FieldRow>
              <FieldRow :label="formatLabel('command_debounce_ms')" :help="sectionHelp('http', 'command_debounce_ms')">
                <NumberField v-model="localConfig.http.command_debounce_ms" :min="0" :step="10" />
              </FieldRow>
            </AdvancedDisclosure>
          </section>

          <section v-else-if="activeTab === 'peripherals' && localConfig.peripherals" class="space-y-5 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.peripherals._title') }}</h2>
            <FieldRow :label="formatLabel('enable')" :help="sectionHelp('peripherals', 'enable')">
              <ToggleSwitch v-model="localConfig.peripherals.enable" />
            </FieldRow>
            <FieldRow :label="formatLabel('input_type')" :help="sectionHelp('peripherals', 'input_type')">
              <select v-model="localConfig.peripherals.input_type" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
                <option :value="null">None</option>
                <option value="keyboard">Keyboard</option>
                <option value="touch">Touch</option>
                <option value="mouse">Mouse</option>
              </select>
            </FieldRow>
            <div class="space-y-5 rounded-lg border border-gray-200 p-4 dark:border-gray-700">
              <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ formatLabel('buttons') }}</h3>
              <FieldRow v-for="(_value, key) in localConfig.peripherals.buttons" :key="key" :label="formatLabel(String(key))" :help="nestedHelp('peripherals', 'buttons', String(key))">
                <KeyboardShortcutCapture v-model="localConfig.peripherals.buttons[key]" />
              </FieldRow>
            </div>
            <AdvancedDisclosure :title="t('settings.domain.advanced')" :description="t('settings.domain.advancedDescription')">
              <FieldRow :label="formatLabel('label')" :help="sectionHelp('peripherals', 'label')">
                <input v-model="localConfig.peripherals.label" type="text" class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white">
              </FieldRow>
              <FieldRow :label="formatLabel('shortcut')" :help="sectionHelp('peripherals', 'shortcut')">
                <KeyboardShortcutCapture v-model="localConfig.peripherals.shortcut" />
              </FieldRow>
            </AdvancedDisclosure>
          </section>

          <section v-else-if="activeTab === 'hardware_inputs' && localConfig.hardware_inputs" class="space-y-5 p-6 sm:p-8">
            <h2 class="border-b border-gray-100 pb-4 text-2xl font-bold text-gray-900 dark:border-gray-700 dark:text-white">{{ t('config.hardware_inputs._title') }}</h2>
            <HardwareInputsEditor v-model="localConfig.hardware_inputs" />
          </section>

          <section v-else-if="activeTab === 'danger'" class="space-y-6 p-6 sm:p-8">
            <div class="flex items-center gap-3 border-b border-red-100 pb-4 dark:border-red-900/30">
              <ExclamationTriangleIcon class="h-8 w-8 text-red-600 dark:text-red-500" />
              <h2 class="text-2xl font-bold text-red-600 dark:text-red-500">{{ t('settings.dangerZone') }}</h2>
            </div>
            <div class="space-y-4">
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
            </div>
          </section>
        </main>
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
