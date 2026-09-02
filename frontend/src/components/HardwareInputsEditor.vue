<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'

type DeviceType = 'button' | 'pir'

interface HardwareInputMapping {
  label?: string
  type: DeviceType
  pin: number
  bounce_time?: number
  no_motion_delay_seconds?: number
  actions: Record<string, string>
}

interface HardwareInputsConfig {
  enabled: boolean
  inputs: Record<string, HardwareInputMapping>
}

const props = defineProps<{
  modelValue: HardwareInputsConfig
}>()

const emit = defineEmits<{
  'update:modelValue': [value: HardwareInputsConfig]
}>()

const { t } = useI18n()

const commandOptions = [
  'NEXT',
  'PREV',
  'PAUSE',
  'PLAY',
  'DISPLAY_ON',
  'DISPLAY_OFF',
  'DISPLAY_TOGGLE',
  'TOGGLE_TEXT',
  'REFRESH_TEXT',
  'REBOOT_HOST',
  'SHUTDOWN_HOST',
  'STOP'
]

const actionsByType: Record<DeviceType, string[]> = {
  button: ['pressed', 'released'],
  pir: ['motion_detected', 'no_motion']
}

const defaultActionsByType: Record<DeviceType, Record<string, string>> = {
  button: { pressed: 'NEXT' },
  pir: { motion_detected: 'DISPLAY_ON', no_motion: 'DISPLAY_OFF' }
}

const config = computed<HardwareInputsConfig>(() => ({
  enabled: Boolean(props.modelValue?.enabled),
  inputs: props.modelValue?.inputs || {}
}))

const rows = computed(() => Object.entries(config.value.inputs))

const duplicatePins = computed(() => {
  const seen = new Map<number, string>()
  const duplicates = new Set<number>()
  for (const [id, mapping] of rows.value) {
    const pin = Number(mapping.pin)
    if (!Number.isInteger(pin)) continue
    const previous = seen.get(pin)
    if (previous && previous !== id) duplicates.add(pin)
    seen.set(pin, id)
  }
  return duplicates
})

function updateConfig(next: HardwareInputsConfig) {
  emit('update:modelValue', next)
}

function updateEnabled(enabled: boolean) {
  updateConfig({ ...config.value, enabled })
}

function nextInputId() {
  let index = rows.value.length + 1
  while (config.value.inputs[`input_${index}`]) index += 1
  return `input_${index}`
}

function addInput() {
  const id = nextInputId()
  updateConfig({
    ...config.value,
    inputs: {
      ...config.value.inputs,
      [id]: {
        label: '',
        type: 'button',
        pin: 17,
        bounce_time: 0.1,
        actions: { pressed: 'NEXT' }
      }
    }
  })
}

function removeInput(id: string) {
  const nextInputs = { ...config.value.inputs }
  delete nextInputs[id]
  updateConfig({ ...config.value, inputs: nextInputs })
}

function updateInput(id: string, patch: Partial<HardwareInputMapping>) {
  const current = config.value.inputs[id]
  if (!current) return
  updateConfig({
    ...config.value,
    inputs: {
      ...config.value.inputs,
      [id]: { ...current, ...patch }
    }
  })
}

function updateType(id: string, type: DeviceType) {
  const current = config.value.inputs[id]
  if (!current) return
  const next: HardwareInputMapping = {
    label: current.label,
    type,
    pin: current.pin,
    actions: { ...defaultActionsByType[type] }
  }
  if (type === 'button') {
    next.bounce_time = 0.1
  } else {
    next.no_motion_delay_seconds = current.no_motion_delay_seconds ?? 0
  }
  updateConfig({
    ...config.value,
    inputs: {
      ...config.value.inputs,
      [id]: next
    }
  })
}

function updateAction(id: string, action: string, command: string) {
  const current = config.value.inputs[id]
  if (!current) return
  const actions = { ...(current.actions || {}) }
  if (command) {
    actions[action] = command
  } else {
    delete actions[action]
  }
  updateInput(id, { actions })
}

function hasDuplicatePin(pin: number) {
  return duplicatePins.value.has(Number(pin))
}
</script>

<template>
  <div class="space-y-6">
    <div
      class="flex flex-col gap-3 border-b border-gray-100 pb-5 dark:border-gray-700/50 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <h3 class="text-base font-semibold text-gray-900 dark:text-white">
          {{ t('settings.hardwareInputs.enabled') }}
        </h3>
      </div>
      <button
        type="button"
        :class="[
          config.enabled ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700',
          'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2'
        ]"
        @click="updateEnabled(!config.enabled)"
      >
        <span
          :class="[
            config.enabled ? 'translate-x-5' : 'translate-x-0',
            'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition'
          ]"
        ></span>
      </button>
    </div>

    <div class="flex justify-end">
      <button
        type="button"
        class="inline-flex items-center rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
        @click="addInput"
      >
        <PlusIcon class="mr-2 h-4 w-4" />
        {{ t('settings.hardwareInputs.add') }}
      </button>
    </div>

    <div
      v-if="rows.length === 0"
      class="rounded-lg border border-dashed border-gray-300 p-6 text-center text-sm text-gray-500 dark:border-gray-700 dark:text-gray-400"
    >
      {{ t('settings.hardwareInputs.empty') }}
    </div>

    <div v-else class="overflow-x-auto">
      <table class="min-w-full divide-y divide-gray-200 text-sm dark:divide-gray-700">
        <thead>
          <tr
            class="text-left text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
          >
            <th class="py-3 pr-4">{{ t('settings.hardwareInputs.label') }}</th>
            <th class="py-3 pr-4">{{ t('settings.hardwareInputs.type') }}</th>
            <th class="py-3 pr-4">{{ t('settings.hardwareInputs.pin') }}</th>
            <th class="py-3 pr-4">{{ t('settings.hardwareInputs.actions') }}</th>
            <th class="py-3 text-right">{{ t('settings.hardwareInputs.remove') }}</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100 dark:divide-gray-800">
          <tr v-for="[id, mapping] in rows" :key="id" class="align-top">
            <td class="py-4 pr-4">
              <input
                type="text"
                :value="mapping.label"
                class="block w-44 rounded-lg border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                @input="updateInput(id, { label: ($event.target as HTMLInputElement).value })"
              />
              <div class="mt-1 text-xs text-gray-400">{{ id }}</div>
            </td>
            <td class="py-4 pr-4">
              <select
                :value="mapping.type"
                class="block w-32 rounded-lg border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                @change="updateType(id, ($event.target as HTMLSelectElement).value as DeviceType)"
              >
                <option value="button">{{ t('settings.hardwareInputs.button') }}</option>
                <option value="pir">{{ t('settings.hardwareInputs.pir') }}</option>
              </select>
            </td>
            <td class="py-4 pr-4">
              <input
                type="number"
                min="0"
                max="27"
                step="1"
                :value="mapping.pin"
                :class="[
                  hasDuplicatePin(mapping.pin)
                    ? 'border-red-500 text-red-600 focus:border-red-500 focus:ring-red-500'
                    : 'border-gray-300 focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600',
                  'block w-24 rounded-lg bg-white px-3 py-2 text-gray-900 shadow-sm dark:bg-gray-700 dark:text-white'
                ]"
                @input="updateInput(id, { pin: Number(($event.target as HTMLInputElement).value) })"
              />
              <div
                v-if="hasDuplicatePin(mapping.pin)"
                class="mt-1 text-xs font-medium text-red-600"
              >
                {{ t('settings.hardwareInputs.duplicatePin') }}
              </div>
            </td>
            <td class="py-4 pr-4">
              <div class="space-y-2">
                <label
                  v-for="action in actionsByType[mapping.type]"
                  :key="action"
                  class="grid grid-cols-[8rem_minmax(10rem,1fr)] items-center gap-2"
                >
                  <span class="text-xs font-medium text-gray-500 dark:text-gray-400">{{
                    t(`settings.hardwareInputs.action.${action}`)
                  }}</span>
                  <select
                    :value="mapping.actions?.[action] || ''"
                    class="block rounded-lg border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    @change="updateAction(id, action, ($event.target as HTMLSelectElement).value)"
                  >
                    <option value="">{{ t('settings.hardwareInputs.noCommand') }}</option>
                    <option v-for="command in commandOptions" :key="command" :value="command">
                      {{ command }}
                    </option>
                  </select>
                </label>
                <label
                  v-if="mapping.type === 'pir'"
                  class="grid grid-cols-[8rem_minmax(10rem,1fr)] items-center gap-2"
                >
                  <span class="text-xs font-medium text-gray-500 dark:text-gray-400">{{
                    t('settings.hardwareInputs.noMotionDelay')
                  }}</span>
                  <input
                    type="number"
                    min="0"
                    step="1"
                    :value="mapping.no_motion_delay_seconds ?? 0"
                    class="block rounded-lg border-gray-300 bg-white px-3 py-2 text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
                    @input="
                      updateInput(id, {
                        no_motion_delay_seconds: Number(($event.target as HTMLInputElement).value)
                      })
                    "
                  />
                </label>
              </div>
            </td>
            <td class="py-4 text-right">
              <button
                type="button"
                class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-red-600 transition-colors hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 dark:text-red-400 dark:hover:bg-red-500/10"
                :title="t('settings.hardwareInputs.remove')"
                @click="removeInput(id)"
              >
                <TrashIcon class="h-4 w-4" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
