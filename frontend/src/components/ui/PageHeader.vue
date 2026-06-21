<script setup lang="ts">
defineProps<{
  title: string
  description?: string
}>()
</script>

<template>
  <header class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
    <div class="min-w-0 xl:flex-1">
      <div class="flex min-w-0 items-center gap-3">
        <slot name="icon" />
        <h1 class="min-w-0 break-words text-2xl font-bold tracking-normal text-gray-950 dark:text-white sm:text-3xl xl:text-4xl">
          {{ title }}
        </h1>
      </div>
      <p v-if="description" class="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
        {{ description }}
      </p>
    </div>
    <div v-if="$slots.actions" class="flex w-full min-w-0 justify-end xl:w-auto xl:shrink-0">
      <slot name="actions" />
    </div>
  </header>
</template>
