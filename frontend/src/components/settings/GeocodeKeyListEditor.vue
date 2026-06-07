<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowDownIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  ArrowUpIcon,
  PlusIcon,
  TrashIcon,
  XMarkIcon
} from '@heroicons/vue/24/outline'

interface Choice {
  value: string
  label?: string
}

const props = defineProps<{
  modelValue: string[][]
  choices: Choice[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[][]]
}>()

const { t } = useI18n()

const defaultRows = [
  ['tourism', 'amenity', 'isolated_dwelling'],
  ['suburb', 'village'],
  ['city', 'county'],
  ['region', 'state', 'province'],
  ['country']
]

const presets = computed(() => [
  { label: t('settings.geocoding.presetDefault'), rows: defaultRows },
  { label: t('settings.geocoding.presetDetailed'), rows: [
    ['tourism', 'amenity', 'historic', 'leisure'],
    ['road', 'square', 'suburb', 'neighbourhood'],
    ['city', 'town', 'village'],
    ['region', 'state', 'province'],
    ['country']
  ] },
  { label: t('settings.geocoding.presetCityRegionCountry'), rows: [
    ['city', 'town', 'village', 'municipality'],
    ['region', 'state', 'province'],
    ['country']
  ] },
  { label: t('settings.geocoding.presetCityCountry'), rows: [
    ['city', 'town', 'village', 'municipality'],
    ['country']
  ] }
])

const sampleAddress: Record<string, string> = {
  tourism: 'Museum Island',
  amenity: 'Cafe',
  historic: 'Old Town',
  leisure: 'Park',
  shop: 'Market',
  office: 'Office',
  building: 'Town Hall',
  isolated_dwelling: 'Farmhouse',
  farm: 'Farm',
  house_number: '12',
  road: 'Main Street',
  pedestrian: 'Promenade',
  square: 'Market Square',
  suburb: 'Mitte',
  village: 'Rothenburg',
  hamlet: 'Hamlet',
  town: 'Potsdam',
  city_district: 'District',
  borough: 'Borough',
  quarter: 'Quarter',
  neighbourhood: 'Neighbourhood',
  city: 'Berlin',
  municipality: 'Municipality',
  county: 'Berlin',
  local_administrative_area: 'Administrative Area',
  region: 'Brandenburg',
  state: 'Berlin',
  province: 'Province',
  state_district: 'State District',
  country: 'Germany',
  country_code: 'de'
}

const rows = computed(() => {
  if (!Array.isArray(props.modelValue)) return []
  return props.modelValue.map(row => Array.isArray(row) ? row.map(String).filter(Boolean) : [])
})

const preview = computed(() => {
  return rows.value
    .map(row => row.map(key => sampleAddress[key]).find(Boolean))
    .filter(Boolean)
    .join(', ')
})

function labelFor(value: string) {
  return props.choices.find(choice => choice.value === value)?.label || value
}

function isSupported(value: string) {
  return props.choices.some(choice => choice.value === value)
}

function updateRows(nextRows: string[][]) {
  emit('update:modelValue', nextRows.map(row => [...row]))
}

function addRow() {
  updateRows([...rows.value, []])
}

function removeRow(index: number) {
  updateRows(rows.value.filter((_row, rowIndex) => rowIndex !== index))
}

function moveRow(index: number, direction: -1 | 1) {
  const nextIndex = index + direction
  if (nextIndex < 0 || nextIndex >= rows.value.length) return
  const nextRows = rows.value.map(row => [...row])
  const [row] = nextRows.splice(index, 1)
  nextRows.splice(nextIndex, 0, row)
  updateRows(nextRows)
}

function addKey(rowIndex: number, key: string) {
  if (!key) return
  const nextRows = rows.value.map(row => [...row])
  if (!nextRows[rowIndex] || nextRows[rowIndex].includes(key)) return
  nextRows[rowIndex].push(key)
  updateRows(nextRows)
}

function removeKey(rowIndex: number, key: string) {
  const nextRows = rows.value.map(row => [...row])
  nextRows[rowIndex] = nextRows[rowIndex].filter(item => item !== key)
  updateRows(nextRows)
}

function moveKey(rowIndex: number, key: string, direction: -1 | 1) {
  const row = rows.value[rowIndex] || []
  const index = row.indexOf(key)
  const nextIndex = index + direction
  if (index < 0 || nextIndex < 0 || nextIndex >= row.length) return
  const nextRows = rows.value.map(row => [...row])
  const [item] = nextRows[rowIndex].splice(index, 1)
  nextRows[rowIndex].splice(nextIndex, 0, item)
  updateRows(nextRows)
}

function applyPreset(nextRows: string[][]) {
  updateRows(nextRows.map(row => [...row]))
}

function availableChoices(row: string[]) {
  return props.choices.filter(choice => !row.includes(choice.value))
}

function handleSelect(event: Event, rowIndex: number) {
  const select = event.target as HTMLSelectElement
  addKey(rowIndex, select.value)
  select.value = ''
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap gap-2">
      <button
        v-for="preset in presets"
        :key="preset.label"
        type="button"
        class="rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-700 transition-colors hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        @click="applyPreset(preset.rows)"
      >
        {{ preset.label }}
      </button>
    </div>

    <div class="space-y-3">
      <div
        v-for="(row, rowIndex) in rows"
        :key="rowIndex"
        class="rounded-lg border border-gray-200 bg-white p-3 dark:border-gray-700 dark:bg-gray-800"
      >
        <div class="mb-3 flex items-center justify-between gap-3">
          <div class="text-sm font-semibold text-gray-900 dark:text-white">
            {{ t('settings.geocoding.part', { number: rowIndex + 1 }) }}
          </div>
          <div class="flex items-center gap-1">
            <button type="button" class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-30 dark:text-gray-300 dark:hover:bg-gray-700" :disabled="rowIndex === 0" :title="t('settings.geocoding.moveUp')" @click="moveRow(rowIndex, -1)">
              <ArrowUpIcon class="h-4 w-4" />
            </button>
            <button type="button" class="rounded p-1 text-gray-500 hover:bg-gray-100 disabled:opacity-30 dark:text-gray-300 dark:hover:bg-gray-700" :disabled="rowIndex === rows.length - 1" :title="t('settings.geocoding.moveDown')" @click="moveRow(rowIndex, 1)">
              <ArrowDownIcon class="h-4 w-4" />
            </button>
            <button type="button" class="rounded p-1 text-red-600 hover:bg-red-50 dark:text-red-300 dark:hover:bg-red-500/10" :title="t('settings.geocoding.removePart')" @click="removeRow(rowIndex)">
              <TrashIcon class="h-4 w-4" />
            </button>
          </div>
        </div>

        <div class="flex flex-wrap gap-2">
          <span
            v-for="key in row"
            :key="key"
            :class="[isSupported(key) ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300', 'inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium']"
          >
            {{ labelFor(key) }}
            <span v-if="!isSupported(key)" class="text-xs opacity-75">{{ t('settings.geocoding.unsupported') }}</span>
            <button type="button" class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10" :title="t('settings.geocoding.moveLeft')" @click="moveKey(rowIndex, key, -1)">
              <ArrowLeftIcon class="h-3.5 w-3.5" />
            </button>
            <button type="button" class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10" :title="t('settings.geocoding.moveRight')" @click="moveKey(rowIndex, key, 1)">
              <ArrowRightIcon class="h-3.5 w-3.5" />
            </button>
            <button type="button" class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10" :title="t('settings.geocoding.removeKey')" @click="removeKey(rowIndex, key)">
              <XMarkIcon class="h-3.5 w-3.5" />
            </button>
          </span>
        </div>

        <select
          class="mt-3 block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
          value=""
          @change="handleSelect($event, rowIndex)"
        >
          <option value="">{{ t('settings.geocoding.addFallback') }}</option>
          <option v-for="choice in availableChoices(row)" :key="choice.value" :value="choice.value">{{ choice.label || choice.value }}</option>
        </select>
      </div>
    </div>

    <button
      type="button"
      class="inline-flex items-center rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600"
      @click="addRow"
    >
      <PlusIcon class="mr-2 h-4 w-4" />
      {{ t('settings.geocoding.addPart') }}
    </button>

    <div v-if="preview" class="rounded-lg bg-gray-50 px-3 py-2 text-sm text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
      <span class="font-medium">{{ t('settings.geocoding.preview') }}:</span>
      {{ preview }}
    </div>
  </div>
</template>
