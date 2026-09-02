<script setup lang="ts">
import { computed, ref, toRef } from 'vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { useFocusTrap } from './useFocusTrap'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    description?: string
    side?: 'right' | 'left'
  }>(),
  {
    side: 'right'
  }
)

const emit = defineEmits<{
  close: []
}>()

const panelRef = ref<HTMLElement | null>(null)
useFocusTrap(toRef(props, 'open'), panelRef, () => emit('close'))

const placementClass = computed(() => {
  return props.side === 'left' ? 'sm:left-0 sm:right-auto' : 'sm:right-0 sm:left-auto'
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 bg-gray-950/70 backdrop-blur-sm"
      role="presentation"
      @click.self="emit('close')"
    >
      <section
        ref="panelRef"
        tabindex="-1"
        :class="[
          'fixed bottom-0 left-0 right-0 max-h-[88vh] overflow-hidden rounded-t-xl border border-gray-200 bg-white shadow-xl outline-none dark:border-gray-700 dark:bg-gray-800',
          'sm:bottom-0 sm:top-0 sm:h-full sm:max-h-none sm:w-full sm:max-w-md sm:rounded-none',
          placementClass
        ]"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`${title.replace(/\s+/g, '-').toLowerCase()}-sheet-title`"
      >
        <header
          class="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4 dark:border-gray-700"
        >
          <div class="min-w-0">
            <h2
              :id="`${title.replace(/\s+/g, '-').toLowerCase()}-sheet-title`"
              class="truncate text-lg font-semibold text-gray-950 dark:text-white"
            >
              {{ title }}
            </h2>
            <p v-if="description" class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
              {{ description }}
            </p>
          </div>
          <button
            type="button"
            class="inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-sky-500/60 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
            :aria-label="$t('common.close')"
            @click="emit('close')"
          >
            <XMarkIcon class="h-5 w-5" />
          </button>
        </header>
        <div class="max-h-[calc(88vh-4.5rem)] overflow-y-auto p-5 sm:max-h-[calc(100vh-4.5rem)]">
          <slot />
        </div>
      </section>
    </div>
  </Teleport>
</template>
