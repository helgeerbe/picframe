<script setup lang="ts">
import { ref, computed } from 'vue'
import { InformationCircleIcon, XMarkIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  text: string
  mode?: 'tooltip' | 'dialog' | 'auto'
  maxLengthForTooltip?: number
}>()

const isOpen = ref(false)

const displayMode = computed(() => {
  if (props.mode && props.mode !== 'auto') {
    return props.mode
  }
  const limit = props.maxLengthForTooltip || 50
  return props.text.length > limit ? 'dialog' : 'tooltip'
})

const toggleDialog = () => {
  if (displayMode.value === 'dialog') {
    isOpen.value = !isOpen.value
  }
}
</script>

<template>
  <div class="inline-flex items-center relative">
    <template v-if="displayMode === 'tooltip'">
      <div class="group relative flex items-center">
        <InformationCircleIcon class="w-4 h-4 text-gray-400 hover:text-indigo-500 cursor-help transition-colors" />
        <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all whitespace-nowrap z-50 shadow-xl">
          {{ text }}
          <div class="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-900"></div>
        </div>
      </div>
    </template>

    <template v-else>
      <button @click="toggleDialog" class="focus:outline-none rounded-full focus:ring-2 focus:ring-indigo-500/50">
        <InformationCircleIcon class="w-4 h-4 text-gray-400 hover:text-indigo-500 transition-colors" />
      </button>

      <!-- Dialog Overlay -->
      <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm" @click="isOpen = false">
        <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl max-w-sm w-full p-6 relative transform transition-all" @click.stop>
          <button @click="isOpen = false" class="absolute top-4 right-4 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 focus:outline-none">
            <XMarkIcon class="w-5 h-5" />
          </button>
          <div class="flex items-start space-x-3">
            <InformationCircleIcon class="w-6 h-6 text-indigo-500 flex-shrink-0 mt-0.5" />
            <div>
              <h4 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">Information</h4>
              <p class="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">
                {{ text }}
              </p>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
