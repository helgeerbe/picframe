<script setup lang="ts">
import { ArrowDownIcon, ArrowUpIcon, XMarkIcon } from '@heroicons/vue/24/outline'

interface Choice {
  value: string
  label?: string
}

const props = defineProps<{
  modelValue: string[]
  choices: Choice[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

function labelFor(value: string) {
  return props.choices.find(choice => choice.value === value)?.label || value
}

function isSupported(value: string) {
  return props.choices.some(choice => choice.value === value)
}

function add(value: string) {
  if (props.modelValue.includes(value)) return
  emit('update:modelValue', [...props.modelValue, value])
}

function remove(value: string) {
  emit('update:modelValue', props.modelValue.filter(item => item !== value))
}

function move(value: string, direction: -1 | 1) {
  const index = props.modelValue.indexOf(value)
  const nextIndex = index + direction
  if (index < 0 || nextIndex < 0 || nextIndex >= props.modelValue.length) return
  const next = [...props.modelValue]
  const [item] = next.splice(index, 1)
  next.splice(nextIndex, 0, item)
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="space-y-3">
    <div class="flex min-h-11 flex-wrap gap-2 rounded-lg border border-gray-300 bg-white p-2 dark:border-gray-600 dark:bg-gray-700">
      <span
        v-for="value in modelValue"
        :key="value"
        :class="[isSupported(value) ? 'bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'bg-amber-50 text-amber-800 dark:bg-amber-500/10 dark:text-amber-300', 'inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium']"
      >
        {{ labelFor(value) }}
        <span v-if="!isSupported(value)" class="text-xs opacity-75">(unsupported)</span>
        <button type="button" class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10" @click="move(value, -1)">
          <ArrowUpIcon class="h-3.5 w-3.5" />
        </button>
        <button type="button" class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10" @click="move(value, 1)">
          <ArrowDownIcon class="h-3.5 w-3.5" />
        </button>
        <button type="button" class="rounded p-0.5 hover:bg-black/5 dark:hover:bg-white/10" @click="remove(value)">
          <XMarkIcon class="h-3.5 w-3.5" />
        </button>
      </span>
    </div>
    <div class="flex flex-wrap gap-2">
      <button
        v-for="choice in choices"
        :key="choice.value"
        type="button"
        :disabled="modelValue.includes(choice.value)"
        class="rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        @click="add(choice.value)"
      >
        {{ choice.label || choice.value }}
      </button>
    </div>
  </div>
</template>
