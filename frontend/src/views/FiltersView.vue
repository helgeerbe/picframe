<script setup lang="ts">
import TextOverlayControls from '../components/TextOverlayControls.vue'
</script>

<template>
  <div class="max-w-7xl mx-auto space-y-6 p-4 sm:p-6 lg:p-8">
    <div class="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
      <div class="xl:col-span-12 flex flex-col space-y-6">
        <TextOverlayControls />
      </div>
    </div>
  </div>
</template>
