<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const isListening = ref(false)

function formatKey(value: string) {
  if (!value) return 'Click, then press key'
  return value === ' ' ? 'Space' : value
}

function stopListening() {
  if (!isListening.value) return
  window.removeEventListener('keydown', capture, true)
  isListening.value = false
}

function startListening() {
  if (isListening.value) return
  isListening.value = true
  window.addEventListener('keydown', capture, true)
}

function capture(event: KeyboardEvent) {
  event.preventDefault()
  event.stopPropagation()
  const key = event.key === ' ' ? ' ' : event.key
  emit('update:modelValue', key)
  stopListening()
}

onBeforeUnmount(stopListening)
</script>

<template>
  <button
    type="button"
    :class="[
      isListening
        ? 'border-indigo-500 bg-indigo-50 text-indigo-700 ring-2 ring-indigo-500 dark:border-indigo-400 dark:bg-indigo-950 dark:text-indigo-200'
        : 'border-gray-300 bg-white text-gray-900 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600',
      'inline-flex min-h-10 min-w-36 items-center justify-center rounded-lg border px-3 py-2 font-mono text-sm shadow-sm transition-colors focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500'
    ]"
    @click="startListening"
  >
    {{ isListening ? 'Listening...' : formatKey(modelValue) }}
  </button>
</template>
