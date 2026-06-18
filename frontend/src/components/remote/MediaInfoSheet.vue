<script setup lang="ts">
import { computed } from 'vue'
import { DocumentTextIcon, MapPinIcon, TagIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import AppSheet from '../ui/AppSheet.vue'
import EmptyState from '../ui/EmptyState.vue'

type MetadataField = {
  key: string
  label: string
  icon: string
  value: unknown
}

const props = defineProps<{
  open: boolean
  title: string
  fileName: string
  caption?: string | null
  locationName?: string | null
  tags: string[]
  fields: MetadataField[]
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()

const visibleFields = computed(() => {
  return props.fields.filter((field) => field.value !== undefined && field.value !== null && String(field.value) !== '')
})
</script>

<template>
  <AppSheet
    :open="open"
    :title="t('remote.mediaInfo.title')"
    :description="fileName"
    @close="emit('close')"
  >
    <div v-if="visibleFields.length || caption || tags.length || locationName" class="space-y-6">
      <section>
        <h3 class="text-lg font-semibold text-gray-950 dark:text-white">{{ title || fileName }}</h3>
        <p v-if="caption" class="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">{{ caption }}</p>
      </section>

      <section v-if="locationName" class="flex items-start gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-900/40">
        <MapPinIcon class="mt-0.5 h-5 w-5 flex-shrink-0 text-gray-400" />
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">{{ t('remote.location') }}</p>
          <p class="mt-1 text-sm font-medium text-gray-950 dark:text-white">{{ locationName }}</p>
        </div>
      </section>

      <section v-if="tags.length">
        <div class="mb-2 flex items-center gap-2 text-sm font-semibold text-gray-950 dark:text-white">
          <TagIcon class="h-4 w-4 text-gray-400" />
          {{ t('remote.metadata.tags') }}
        </div>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="tag in tags"
            :key="tag"
            class="rounded-md border border-sky-100 bg-sky-50 px-2 py-1 text-xs font-semibold text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-200"
          >
            {{ tag }}
          </span>
        </div>
      </section>

      <section>
        <h3 class="mb-3 text-sm font-semibold text-gray-950 dark:text-white">{{ t('remote.mediaInfo.technical') }}</h3>
        <dl class="divide-y divide-gray-100 rounded-lg border border-gray-200 dark:divide-gray-700 dark:border-gray-700">
          <div
            v-for="field in visibleFields"
            :key="field.key"
            class="grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-3 px-3 py-3 text-sm"
          >
            <dt class="flex min-w-0 items-center gap-2 text-gray-500 dark:text-gray-400">
              <svg class="h-4 w-4 flex-shrink-0" viewBox="0 0 24 24" aria-hidden="true">
                <path :d="field.icon" fill="currentColor" />
              </svg>
              <span class="truncate">{{ field.label }}</span>
            </dt>
            <dd class="truncate text-right font-medium text-gray-950 dark:text-gray-100" :title="String(field.value)">
              {{ field.value }}
            </dd>
          </div>
        </dl>
      </section>
    </div>

    <EmptyState v-else :title="t('remote.noMetadata')" :message="t('remote.mediaInfo.empty')">
      <template #icon>
        <DocumentTextIcon class="h-10 w-10" />
      </template>
    </EmptyState>
  </AppSheet>
</template>
