<script setup lang="ts">
defineProps<{
  label: string
  help?: string
}>()
</script>

<template>
  <div class="grid grid-cols-1 gap-3 border-b border-gray-100 pb-5 last:border-0 last:pb-0 dark:border-gray-700/60 md:grid-cols-[14rem_minmax(0,1fr)]">
    <div>
      <label class="block text-sm font-semibold text-gray-900 dark:text-white">{{ label }}</label>
      <p v-if="help" class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">{{ help }}</p>
    </div>
    <div class="min-w-0">
      <slot />
    </div>
  </div>
</template>
