<script setup lang="ts">
withDefaults(defineProps<{
  as?: string
  padded?: boolean
  tone?: 'default' | 'muted'
}>(), {
  as: 'section',
  padded: false,
  tone: 'default'
})
</script>

<template>
  <component
    :is="as"
    :class="[
      'rounded-lg border shadow-sm',
      tone === 'muted'
        ? 'border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/40'
        : 'border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800',
      padded ? 'p-4 sm:p-6' : ''
    ]"
  >
    <slot />
  </component>
</template>
