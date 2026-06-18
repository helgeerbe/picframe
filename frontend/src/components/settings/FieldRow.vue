<script setup lang="ts">
import { computed, provide } from 'vue'

const props = defineProps<{
  label: string
  help?: string
}>()

const fieldId = computed(() => `field-${props.label.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}`)
const labelId = computed(() => `${fieldId.value}-label`)
const helpId = computed(() => `${fieldId.value}-help`)

provide('fieldLabelId', labelId)
provide('fieldHelpId', computed(() => props.help ? helpId.value : undefined))
</script>

<template>
  <div class="grid grid-cols-1 gap-3 border-b border-gray-100 pb-5 last:border-0 last:pb-0 dark:border-gray-700/60 md:grid-cols-[14rem_minmax(0,1fr)]">
    <div>
      <div :id="labelId" class="block text-sm font-semibold text-gray-900 dark:text-white">{{ label }}</div>
      <p v-if="help" :id="helpId" class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">{{ help }}</p>
    </div>
    <div class="min-w-0" role="group" :aria-labelledby="labelId" :aria-describedby="help ? helpId : undefined">
      <slot />
    </div>
  </div>
</template>
