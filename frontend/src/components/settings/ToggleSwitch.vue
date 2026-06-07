<script setup lang="ts">
const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()
</script>

<template>
  <button
    type="button"
    :class="[props.modelValue ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700', 'relative inline-flex h-6 w-11 flex-shrink-0 rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2']"
    @click="emit('update:modelValue', !props.modelValue)"
  >
    <span :class="[props.modelValue ? 'translate-x-5' : 'translate-x-0', 'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow transition']"></span>
  </button>
</template>
