<script setup lang="ts">
withDefaults(
  defineProps<{
    label: string
    title?: string
    pressed?: boolean
    variant?: 'ghost' | 'soft' | 'primary' | 'danger'
    size?: 'sm' | 'md' | 'lg'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
  }>(),
  {
    variant: 'ghost',
    size: 'md',
    type: 'button',
    disabled: false
  }
)

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <button
    :type="type"
    :aria-label="label"
    :aria-pressed="pressed === undefined ? undefined : pressed"
    :title="title || label"
    :disabled="disabled"
    :class="[
      'inline-flex flex-shrink-0 items-center justify-center rounded-lg border transition-colors focus:outline-none focus:ring-2 focus:ring-sky-500/60 disabled:cursor-not-allowed disabled:opacity-60',
      size === 'sm' ? 'h-9 w-9' : size === 'lg' ? 'h-12 w-12' : 'h-10 w-10',
      variant === 'primary'
        ? 'border-sky-600 bg-sky-600 text-white hover:bg-sky-500'
        : variant === 'danger'
          ? 'border-red-600 bg-red-600 text-white hover:bg-red-500'
          : variant === 'soft'
            ? 'border-gray-200 bg-gray-100 text-gray-700 hover:bg-gray-200 dark:border-gray-700 dark:bg-gray-700 dark:text-gray-100 dark:hover:bg-gray-600'
            : 'border-transparent bg-transparent text-gray-500 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white'
    ]"
    @click="emit('click', $event)"
  >
    <slot />
  </button>
</template>
