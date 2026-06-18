<script setup lang="ts">
import { computed, ref, toRef } from 'vue'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { useFocusTrap } from './useFocusTrap'

const props = withDefaults(defineProps<{
  open: boolean
  title: string
  description?: string
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl'
}>(), {
  maxWidth: 'md'
})

const emit = defineEmits<{
  close: []
}>()

const panelRef = ref<HTMLElement | null>(null)
useFocusTrap(toRef(props, 'open'), panelRef, () => emit('close'))

const widthClass = computed(() => {
  switch (props.maxWidth) {
    case 'sm': return 'max-w-sm'
    case 'lg': return 'max-w-2xl'
    case 'xl': return 'max-w-4xl'
    default: return 'max-w-lg'
  }
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/70 p-4 backdrop-blur-sm"
      role="presentation"
      @click.self="emit('close')"
    >
      <section
        ref="panelRef"
        tabindex="-1"
        :class="['w-full overflow-hidden rounded-lg border border-gray-200 bg-white shadow-xl outline-none dark:border-gray-700 dark:bg-gray-800', widthClass]"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="`${title.replace(/\s+/g, '-').toLowerCase()}-dialog-title`"
      >
        <header class="flex items-start justify-between gap-4 border-b border-gray-100 px-5 py-4 dark:border-gray-700">
          <div>
            <h2 :id="`${title.replace(/\s+/g, '-').toLowerCase()}-dialog-title`" class="text-lg font-semibold text-gray-950 dark:text-white">
              {{ title }}
            </h2>
            <p v-if="description" class="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">{{ description }}</p>
          </div>
          <button
            type="button"
            class="inline-flex h-9 w-9 items-center justify-center rounded-lg text-gray-500 hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-sky-500/60 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
            :aria-label="$t('common.close')"
            @click="emit('close')"
          >
            <XMarkIcon class="h-5 w-5" />
          </button>
        </header>
        <div class="p-5">
          <slot />
        </div>
        <footer v-if="$slots.footer" class="border-t border-gray-100 bg-gray-50 px-5 py-4 dark:border-gray-700 dark:bg-gray-900/40">
          <slot name="footer" />
        </footer>
      </section>
    </div>
  </Teleport>
</template>
