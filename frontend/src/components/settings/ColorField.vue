<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  modelValue: string | number[] | null
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
}>()

const enabled = computed(() => props.modelValue !== null && props.modelValue !== '')

const colorValue = computed(() => {
  if (Array.isArray(props.modelValue) && props.modelValue.length >= 3) {
    return `#${props.modelValue
      .slice(0, 3)
      .map(value => Number(value).toString(16).padStart(2, '0'))
      .join('')}`
  }
  const value = String(props.modelValue || '').trim()
  if (/^#[0-9a-fA-F]{6}$/.test(value)) return value
  const match = value.match(/^\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*$/)
  if (match) {
    return `#${match
      .slice(1, 4)
      .map(part =>
        Math.max(0, Math.min(255, Number(part)))
          .toString(16)
          .padStart(2, '0')
      )
      .join('')}`
  }
  return '#808080'
})

function setAuto() {
  emit('update:modelValue', null)
}

function setColor(value: string) {
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-3">
    <button
      type="button"
      :class="[
        !enabled
          ? 'bg-indigo-600 text-white'
          : 'border border-gray-300 text-gray-700 dark:border-gray-600 dark:text-gray-300',
        'rounded-md px-3 py-2 text-sm font-medium'
      ]"
      @click="setAuto"
    >
      Auto
    </button>
    <input
      type="color"
      :value="colorValue"
      class="h-10 w-14 rounded border border-gray-300 bg-white p-1 dark:border-gray-600 dark:bg-gray-700"
      @input="setColor(($event.target as HTMLInputElement).value)"
    />
    <input
      type="text"
      :value="enabled ? modelValue : ''"
      placeholder="Auto"
      class="block min-w-[10rem] rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
      @input="setColor(($event.target as HTMLInputElement).value)"
    />
  </div>
</template>
