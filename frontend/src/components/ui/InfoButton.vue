<script setup lang="ts">
import { InformationCircleIcon } from '@heroicons/vue/24/outline'
import IconButton from './IconButton.vue'

defineProps<{
  label: string
}>()

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()
</script>

<template>
  <IconButton :label="label" variant="soft" @click="emit('click', $event)">
    <InformationCircleIcon class="h-5 w-5" />
  </IconButton>
</template>
