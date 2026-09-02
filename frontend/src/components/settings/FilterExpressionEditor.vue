<script setup lang="ts">
const props = defineProps<{
  modelValue: string
  options: string[]
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

function quoteTerm(term: string) {
  const trimmed = term.trim()
  return /\s/.test(trimmed) ? `"${trimmed.replaceAll('"', '\\"')}"` : trimmed
}

function containsTerm(expression: string, term: string) {
  return expression.toLowerCase().includes(term.toLowerCase())
}

function toggleTerm(term: string, joiner: 'OR' | 'AND') {
  const value = quoteTerm(term)
  if (!props.modelValue.trim()) {
    emit('update:modelValue', value)
    return
  }
  if (containsTerm(props.modelValue, value)) {
    const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const next = props.modelValue
      .replace(new RegExp(`\\s+(AND|OR)\\s+${escaped}`, 'i'), '')
      .replace(new RegExp(`${escaped}\\s+(AND|OR)\\s+`, 'i'), '')
      .replace(new RegExp(escaped, 'i'), '')
      .trim()
    emit('update:modelValue', next)
    return
  }
  emit('update:modelValue', `${props.modelValue.trim()} ${joiner} ${value}`)
}
</script>

<template>
  <div class="space-y-3">
    <textarea
      :value="modelValue"
      rows="2"
      :placeholder="placeholder"
      class="block w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
      @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
    ></textarea>
    <div
      v-if="options.length"
      class="max-h-28 overflow-y-auto rounded-lg border border-gray-200 p-2 dark:border-gray-700"
    >
      <div class="flex flex-wrap gap-2">
        <button
          v-for="option in options"
          :key="option"
          type="button"
          :class="[
            containsTerm(modelValue, quoteTerm(option))
              ? 'bg-indigo-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600',
            'rounded-md px-2 py-1 text-xs font-medium transition-colors'
          ]"
          @click="toggleTerm(option, ($event as MouseEvent).shiftKey ? 'AND' : 'OR')"
        >
          {{ option }}
        </button>
      </div>
    </div>
  </div>
</template>
