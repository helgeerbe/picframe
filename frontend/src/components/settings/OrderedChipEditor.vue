<script setup lang="ts">
import { ArrowDownIcon, ArrowUpIcon, XMarkIcon } from '@heroicons/vue/24/outline'

interface Option {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: Option[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

function values() {
  const allowed = new Set(props.options.map(option => option.value))
  return props.modelValue
    .split(/\s+/)
    .map(value => value.trim().toLowerCase())
    .filter(value => value && allowed.has(value))
}

function labelFor(value: string) {
  return props.options.find(option => option.value === value)?.label || value
}

function save(next: string[]) {
  emit('update:modelValue', next.join(' '))
}

function add(value: string) {
  const current = values()
  if (!current.includes(value)) save([...current, value])
}

function remove(value: string) {
  save(values().filter(item => item !== value))
}

function move(value: string, direction: -1 | 1) {
  const current = values()
  const index = current.indexOf(value)
  const nextIndex = index + direction
  if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return
  const next = [...current]
  const item = next.splice(index, 1)[0]
  next.splice(nextIndex, 0, item)
  save(next)
}
</script>

<template>
  <div class="space-y-3">
    <div
      class="flex min-h-11 flex-wrap gap-2 rounded-lg border border-gray-300 bg-white p-2 dark:border-gray-600 dark:bg-gray-700"
    >
      <span
        v-for="value in values()"
        :key="value"
        class="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-1 text-sm font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
      >
        {{ labelFor(value) }}
        <button
          type="button"
          class="rounded p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/20"
          @click="move(value, -1)"
        >
          <ArrowUpIcon class="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          class="rounded p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/20"
          @click="move(value, 1)"
        >
          <ArrowDownIcon class="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          class="rounded p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/20"
          @click="remove(value)"
        >
          <XMarkIcon class="h-3.5 w-3.5" />
        </button>
      </span>
    </div>
    <div class="flex flex-wrap gap-2">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        :disabled="values().includes(option.value)"
        class="rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-700 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        @click="add(option.value)"
      >
        {{ option.label }}
      </button>
    </div>
  </div>
</template>
