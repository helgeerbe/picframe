<script setup lang="ts">
import { ref } from 'vue'
import { ChevronDownIcon } from '@heroicons/vue/24/outline'

defineProps<{
  title: string
  description?: string
}>()

const open = ref(false)
</script>

<template>
  <section class="rounded-lg border border-gray-200 bg-gray-50/70 dark:border-gray-700 dark:bg-gray-900/30">
    <button
      type="button"
      class="flex w-full items-center justify-between gap-4 px-4 py-3 text-left"
      @click="open = !open"
    >
      <span>
        <span class="block text-sm font-semibold text-gray-900 dark:text-white">{{ title }}</span>
        <span v-if="description" class="mt-1 block text-xs text-gray-500 dark:text-gray-400">{{ description }}</span>
      </span>
      <ChevronDownIcon :class="[open ? 'rotate-180' : '', 'h-5 w-5 text-gray-500 transition-transform']" />
    </button>
    <div v-if="open" class="space-y-5 border-t border-gray-200 p-4 dark:border-gray-700">
      <slot />
    </div>
  </section>
</template>
