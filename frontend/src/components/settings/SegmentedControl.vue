<script setup lang="ts">
import { inject, type ComputedRef } from 'vue'

interface Option {
  value: string | number | boolean | null
  label: string
}

defineProps<{
  modelValue: string | number | boolean | null
  options: Option[]
  label?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | number | boolean | null]
}>()

const fieldLabelId = inject<ComputedRef<string> | undefined>('fieldLabelId', undefined)
const fieldHelpId = inject<ComputedRef<string | undefined> | undefined>('fieldHelpId', undefined)
</script>

<template>
  <div
    class="inline-flex flex-wrap rounded-lg border border-gray-300 bg-white p-1 dark:border-gray-600 dark:bg-gray-800"
    role="group"
    :aria-label="label"
    :aria-labelledby="label ? undefined : fieldLabelId"
    :aria-describedby="fieldHelpId"
  >
    <button
      v-for="option in options"
      :key="String(option.value)"
      type="button"
      :aria-pressed="modelValue === option.value"
      :class="[
        modelValue === option.value
          ? 'bg-indigo-600 text-white shadow-sm'
          : 'text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700',
        'rounded-md px-3 py-1.5 text-sm font-medium transition-colors'
      ]"
      @click="emit('update:modelValue', option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>
