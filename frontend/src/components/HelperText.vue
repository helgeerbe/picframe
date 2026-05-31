<script setup lang="ts">
import { ref, computed, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { InformationCircleIcon, XMarkIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  text: string
  mode?: 'tooltip' | 'dialog' | 'auto'
  maxLengthForTooltip?: number
}>()

const { t } = useI18n()
const isOpen = ref(false)

const displayMode = computed(() => {
  if (props.mode && props.mode !== 'auto') {
    return props.mode
  }
  const limit = props.maxLengthForTooltip || 50
  return props.text.length > limit ? 'dialog' : 'tooltip'
})

const toggleDialog = () => {
  isOpen.value = !isOpen.value
}

const closeDialog = () => {
  isOpen.value = false
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    closeDialog()
  }
}

watch(isOpen, (open) => {
  if (open) {
    document.addEventListener('keydown', handleKeydown)
  } else {
    document.removeEventListener('keydown', handleKeydown)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="inline-flex items-center relative">
    <div class="group relative inline-flex items-center">
      <button
        type="button"
        @click="toggleDialog"
        :aria-expanded="isOpen"
        :aria-label="t('common.help')"
        class="inline-flex h-7 w-7 items-center justify-center rounded-full text-gray-400 transition-colors hover:text-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 dark:text-gray-500 dark:hover:text-indigo-400"
      >
        <InformationCircleIcon class="w-4 h-4" />
      </button>

      <div
        v-if="displayMode === 'tooltip'"
        class="pointer-events-none absolute bottom-full left-1/2 z-50 mb-2 hidden -translate-x-1/2 rounded-lg bg-gray-900 px-3 py-2 text-xs text-white opacity-0 shadow-xl transition-all group-hover:opacity-100 group-focus-within:opacity-100 sm:block whitespace-nowrap"
      >
        {{ text }}
        <div class="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900"></div>
      </div>
    </div>

    <Teleport to="body">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        :aria-label="t('common.help')"
        @click="closeDialog"
      >
        <div class="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl transition-all dark:bg-gray-800" @click.stop>
          <button
            type="button"
            @click.stop="closeDialog"
            :aria-label="t('common.close')"
            class="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 dark:hover:bg-gray-700 dark:hover:text-gray-300"
          >
            <XMarkIcon class="w-5 h-5" />
          </button>
          <div class="flex items-start space-x-3 pr-8">
            <InformationCircleIcon class="mt-0.5 h-6 w-6 flex-shrink-0 text-indigo-500" />
            <div>
              <h4 class="mb-2 text-lg font-semibold text-gray-900 dark:text-white">{{ t('common.help') }}</h4>
              <p class="text-sm leading-relaxed text-gray-600 dark:text-gray-300">
                {{ text }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
