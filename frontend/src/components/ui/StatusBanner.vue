<script setup lang="ts">
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  InformationCircleIcon,
  XCircleIcon
} from '@heroicons/vue/24/outline'

withDefaults(
  defineProps<{
    tone?: 'info' | 'success' | 'warning' | 'danger'
    title?: string
    message: string
  }>(),
  {
    tone: 'info'
  }
)

const iconMap = {
  info: InformationCircleIcon,
  success: CheckCircleIcon,
  warning: ExclamationTriangleIcon,
  danger: XCircleIcon
}
</script>

<template>
  <div
    :class="[
      'flex gap-3 rounded-lg border p-4 text-sm',
      tone === 'success'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-200'
        : tone === 'warning'
          ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200'
          : tone === 'danger'
            ? 'border-red-200 bg-red-50 text-red-800 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-200'
            : 'border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-200'
    ]"
    role="status"
    aria-live="polite"
  >
    <component :is="iconMap[tone]" class="mt-0.5 h-5 w-5 flex-shrink-0" />
    <div class="min-w-0">
      <p v-if="title" class="font-semibold">{{ title }}</p>
      <p :class="title ? 'mt-1' : ''">{{ message }}</p>
      <div v-if="$slots.actions" class="mt-3">
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>
