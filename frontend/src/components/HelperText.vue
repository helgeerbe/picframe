<script setup lang="ts">
import { ref, computed, nextTick, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { InformationCircleIcon, XMarkIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  text: string
  mode?: 'tooltip' | 'dialog' | 'auto'
  maxLengthForTooltip?: number
}>()

const { t } = useI18n()
const isOpen = ref(false)
const isTooltipOpen = ref(false)
const isTooltipPositioned = ref(false)
const buttonRef = ref<HTMLButtonElement | null>(null)
const tooltipRef = ref<HTMLElement | null>(null)
const tooltipPlacement = ref<'top' | 'bottom'>('bottom')
const tooltipStyle = ref<Record<string, string>>({
  left: '0px',
  top: '0px'
})
const arrowStyle = ref<Record<string, string>>({
  left: '50%'
})

const VIEWPORT_MARGIN = 12
const TOOLTIP_OFFSET = 8

const displayMode = computed(() => {
  if (props.mode && props.mode !== 'auto') {
    return props.mode
  }
  const limit = props.maxLengthForTooltip || 50
  return props.text.length > limit ? 'dialog' : 'tooltip'
})

const toggleDialog = () => {
  closeTooltip()
  isOpen.value = !isOpen.value
}

const closeDialog = () => {
  isOpen.value = false
}

const clamp = (value: number, min: number, max: number) => {
  return Math.min(Math.max(value, min), max)
}

const updateTooltipPosition = async () => {
  if (displayMode.value !== 'tooltip' || !buttonRef.value || !isTooltipOpen.value) return

  await nextTick()
  if (!tooltipRef.value) return

  const buttonRect = buttonRef.value.getBoundingClientRect()
  const tooltipRect = tooltipRef.value.getBoundingClientRect()
  const maxLeft = Math.max(VIEWPORT_MARGIN, window.innerWidth - tooltipRect.width - VIEWPORT_MARGIN)
  const desiredLeft = buttonRect.left + buttonRect.width / 2 - tooltipRect.width / 2
  const left = clamp(desiredLeft, VIEWPORT_MARGIN, maxLeft)
  const hasRoomBelow =
    buttonRect.bottom + TOOLTIP_OFFSET + tooltipRect.height + VIEWPORT_MARGIN <= window.innerHeight
  const hasRoomAbove = buttonRect.top - TOOLTIP_OFFSET - tooltipRect.height - VIEWPORT_MARGIN >= 0
  const placeAbove = !hasRoomBelow && hasRoomAbove
  const top = placeAbove
    ? buttonRect.top - tooltipRect.height - TOOLTIP_OFFSET
    : buttonRect.bottom + TOOLTIP_OFFSET
  const arrowLeft = clamp(buttonRect.left + buttonRect.width / 2 - left, 12, tooltipRect.width - 12)

  tooltipPlacement.value = placeAbove ? 'top' : 'bottom'
  tooltipStyle.value = {
    left: `${Math.round(left)}px`,
    top: `${Math.round(top)}px`
  }
  arrowStyle.value = {
    left: `${Math.round(arrowLeft)}px`
  }
  isTooltipPositioned.value = true
}

const scheduleTooltipPositionUpdate = () => {
  void updateTooltipPosition()
}

const openTooltip = () => {
  if (displayMode.value !== 'tooltip') return
  isTooltipOpen.value = true
  isTooltipPositioned.value = false
  scheduleTooltipPositionUpdate()
}

const closeTooltip = () => {
  isTooltipOpen.value = false
  isTooltipPositioned.value = false
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    closeDialog()
  }
}

watch(isOpen, open => {
  if (open) {
    document.addEventListener('keydown', handleKeydown)
  } else {
    document.removeEventListener('keydown', handleKeydown)
  }
})

watch(isTooltipOpen, open => {
  if (open) {
    window.addEventListener('resize', scheduleTooltipPositionUpdate)
    window.addEventListener('scroll', scheduleTooltipPositionUpdate, true)
    scheduleTooltipPositionUpdate()
  } else {
    window.removeEventListener('resize', scheduleTooltipPositionUpdate)
    window.removeEventListener('scroll', scheduleTooltipPositionUpdate, true)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', scheduleTooltipPositionUpdate)
  window.removeEventListener('scroll', scheduleTooltipPositionUpdate, true)
})
</script>

<template>
  <div class="inline-flex items-center relative">
    <div class="relative inline-flex items-center">
      <button
        ref="buttonRef"
        type="button"
        :aria-expanded="isOpen"
        :aria-label="t('common.help')"
        class="inline-flex h-7 w-7 items-center justify-center rounded-full text-gray-400 transition-colors hover:text-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 dark:text-gray-500 dark:hover:text-indigo-400"
        @click="toggleDialog"
        @mouseenter="openTooltip"
        @mouseleave="closeTooltip"
        @focus="openTooltip"
        @blur="closeTooltip"
      >
        <InformationCircleIcon class="w-4 h-4" />
      </button>
    </div>

    <Teleport to="body">
      <div
        v-if="displayMode === 'tooltip' && isTooltipOpen"
        ref="tooltipRef"
        role="tooltip"
        :style="tooltipStyle"
        :class="[
          isTooltipPositioned ? 'opacity-100' : 'opacity-0',
          'pointer-events-none fixed z-[70] hidden max-w-[calc(100vw-1.5rem)] rounded-lg bg-gray-900 px-3 py-2 text-xs leading-5 text-white shadow-xl transition-opacity sm:block'
        ]"
      >
        {{ text }}
        <div
          :style="arrowStyle"
          :class="[
            tooltipPlacement === 'bottom'
              ? 'bottom-full border-b-gray-900'
              : 'top-full border-t-gray-900',
            'absolute -translate-x-1/2 border-4 border-transparent'
          ]"
        ></div>
      </div>
    </Teleport>

    <Teleport to="body">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
        role="dialog"
        aria-modal="true"
        :aria-label="t('common.help')"
        @click="closeDialog"
      >
        <div
          class="relative w-full max-w-sm rounded-2xl bg-white p-6 shadow-2xl transition-all dark:bg-gray-800"
          @click.stop
        >
          <button
            type="button"
            :aria-label="t('common.close')"
            class="absolute right-4 top-4 inline-flex h-9 w-9 items-center justify-center rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 dark:hover:bg-gray-700 dark:hover:text-gray-300"
            @click.stop="closeDialog"
          >
            <XMarkIcon class="w-5 h-5" />
          </button>
          <div class="flex items-start space-x-3 pr-8">
            <InformationCircleIcon class="mt-0.5 h-6 w-6 flex-shrink-0 text-indigo-500" />
            <div>
              <h4 class="mb-2 text-lg font-semibold text-gray-900 dark:text-white">
                {{ t('common.help') }}
              </h4>
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
