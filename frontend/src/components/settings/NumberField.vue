<script setup lang="ts">
import { inject, type ComputedRef } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: number | string | null | undefined
  min?: number
  max?: number
  step?: number
  unit?: string
  label?: string
}>(), {
  step: 1
})

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

function clamp(value: number) {
  let nextValue = Number.isFinite(value) ? value : 0
  if (props.min !== undefined) nextValue = Math.max(props.min, nextValue)
  if (props.max !== undefined) nextValue = Math.min(props.max, nextValue)
  return Number(nextValue.toFixed(6))
}

function currentValue() {
  return clamp(Number(props.modelValue ?? props.min ?? 0))
}

function updateValue(value: number) {
  emit('update:modelValue', clamp(value))
}

function handleInput(event: Event) {
  updateValue(Number((event.target as HTMLInputElement).value))
}

const fieldLabelId = inject<ComputedRef<string> | undefined>('fieldLabelId', undefined)
const fieldHelpId = inject<ComputedRef<string | undefined> | undefined>('fieldHelpId', undefined)
</script>

<template>
  <div class="flex w-40 items-center gap-2">
    <input
      :value="currentValue()"
      type="number"
      :min="props.min"
      :max="props.max"
      :step="props.step"
      :aria-label="props.label"
      :aria-labelledby="props.label ? undefined : fieldLabelId"
      :aria-describedby="fieldHelpId"
      class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
      @input="handleInput"
    >
    <span v-if="props.unit" class="text-xs font-medium text-gray-500 dark:text-gray-300">{{ props.unit }}</span>
  </div>
</template>
