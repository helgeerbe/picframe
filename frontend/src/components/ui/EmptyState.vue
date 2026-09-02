<script setup lang="ts">
defineProps<{
  title: string
  message?: string
}>()
</script>

<template>
  <div
    class="flex min-h-48 flex-col items-center justify-center rounded-lg border border-dashed border-gray-300 bg-gray-50 p-8 text-center dark:border-gray-700 dark:bg-gray-900/40"
  >
    <div v-if="$slots.icon" class="mb-4 text-gray-400 dark:text-gray-500">
      <slot name="icon" />
    </div>
    <h2 class="text-base font-semibold text-gray-950 dark:text-white">{{ title }}</h2>
    <p v-if="message" class="mt-2 max-w-md text-sm leading-6 text-gray-500 dark:text-gray-400">
      {{ message }}
    </p>
    <div v-if="$slots.actions" class="mt-5">
      <slot name="actions" />
    </div>
  </div>
</template>
