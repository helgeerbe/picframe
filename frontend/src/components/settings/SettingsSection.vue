<script setup lang="ts">
import { computed, ref } from 'vue'
import { ChevronDownIcon } from '@heroicons/vue/24/outline'

const props = withDefaults(defineProps<{
  title: string
  description?: string
  defaultOpen?: boolean
  id?: string
  tone?: 'default' | 'danger'
}>(), {
  defaultOpen: false,
  tone: 'default'
})

const open = ref(props.defaultOpen)
const generatedId = `settings-section-${Math.random().toString(36).slice(2)}`
const baseId = computed(() => props.id || generatedId)
const buttonId = computed(() => `${baseId.value}-button`)
const panelId = computed(() => `${baseId.value}-panel`)

const sectionClasses = computed(() => {
  if (props.tone === 'danger') {
    return 'border-red-100 bg-red-50/80 dark:border-red-500/20 dark:bg-red-500/5'
  }
  return 'border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800'
})
</script>

<template>
  <section :class="['overflow-hidden rounded-lg border shadow-sm', sectionClasses]">
    <button
      :id="buttonId"
      type="button"
      class="flex w-full items-start justify-between gap-4 px-4 py-4 text-left transition-colors hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-indigo-500/60 dark:hover:bg-gray-700/40 sm:px-5"
      :aria-expanded="open"
      :aria-controls="panelId"
      @click="open = !open"
    >
      <span class="min-w-0">
        <span class="block text-sm font-semibold text-gray-950 dark:text-white sm:text-base">{{ title }}</span>
        <span v-if="description" class="mt-1 block text-xs leading-5 text-gray-500 dark:text-gray-400 sm:text-sm">
          {{ description }}
        </span>
      </span>
      <ChevronDownIcon
        :class="[open ? 'rotate-180' : '', 'mt-0.5 h-5 w-5 flex-shrink-0 text-gray-500 transition-transform dark:text-gray-400']"
      />
    </button>
    <div
      v-if="open"
      :id="panelId"
      role="region"
      :aria-labelledby="buttonId"
      class="space-y-5 border-t border-gray-100 p-4 dark:border-gray-700 sm:p-5"
    >
      <slot />
    </div>
  </section>
</template>
