<script setup lang="ts">
import { ref } from 'vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'

const props = withDefaults(
  defineProps<{
    modelValue: string[]
    placeholder?: string
    extensionMode?: boolean
  }>(),
  {
    placeholder: '',
    extensionMode: false
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const draft = ref('')

function normalizeToken(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (!props.extensionMode) return trimmed
  const lower = trimmed.toLowerCase()
  return lower.startsWith('.') ? lower : `.${lower}`
}

function addToken(rawValue = draft.value) {
  const token = normalizeToken(rawValue)
  if (!token) return
  if (!props.modelValue.includes(token)) {
    emit('update:modelValue', [...props.modelValue, token])
  }
  draft.value = ''
}

function removeToken(token: string) {
  emit(
    'update:modelValue',
    props.modelValue.filter(item => item !== token)
  )
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    addToken()
  }
}
</script>

<template>
  <div class="rounded-lg border border-gray-300 bg-white p-2 dark:border-gray-600 dark:bg-gray-700">
    <div class="flex flex-wrap gap-2">
      <span
        v-for="token in modelValue"
        :key="token"
        class="inline-flex items-center gap-1 rounded-md bg-indigo-50 px-2 py-1 text-sm font-medium text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300"
      >
        {{ token }}
        <button
          type="button"
          class="rounded p-0.5 hover:bg-indigo-100 dark:hover:bg-indigo-500/20"
          @click="removeToken(token)"
        >
          <XMarkIcon class="h-3.5 w-3.5" />
        </button>
      </span>
      <input
        v-model="draft"
        type="text"
        :placeholder="placeholder"
        class="min-w-[10rem] flex-1 border-0 bg-transparent px-1 py-1 text-sm text-gray-900 shadow-none outline-none focus:ring-0 dark:text-white"
        @keydown="handleKeydown"
        @blur="addToken()"
      />
    </div>
  </div>
</template>
