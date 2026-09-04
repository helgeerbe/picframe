<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { FolderIcon, DocumentIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import {
  useConfigStore,
  type FilesystemBrowseResponse,
  type FilesystemValidateResponse
} from '../../stores/config'
import { getApiErrorMessage } from '../../utils/errors'

const props = withDefaults(
  defineProps<{
    modelValue: string
    kind?: 'any' | 'file' | 'directory'
    allowMissing?: boolean
    extensions?: string[]
  }>(),
  {
    kind: 'any',
    allowMissing: false,
    extensions: () => []
  }
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const configStore = useConfigStore()
const { t } = useI18n()
const browseOpen = ref(false)
const browseState = ref<FilesystemBrowseResponse | null>(null)
const validation = ref<FilesystemValidateResponse | null>(null)
const browseError = ref('')

async function validatePath() {
  if (!props.modelValue) {
    validation.value = null
    return
  }
  try {
    validation.value = await configStore.validateFilesystemPath({
      path: props.modelValue,
      kind: props.kind,
      allow_missing: props.allowMissing,
      extensions: props.extensions
    })
  } catch (error: unknown) {
    validation.value = {
      valid: false,
      path: props.modelValue,
      exists: false,
      is_dir: false,
      is_file: false,
      warnings: [],
      error: getApiErrorMessage(error, t('settings.pathPicker.notAllowed'))
    }
  }
}

async function browse(path = props.modelValue || '~') {
  browseError.value = ''
  try {
    browseState.value = await configStore.browseFilesystem({
      path,
      kind: props.kind,
      extensions: props.extensions
    })
    browseOpen.value = true
  } catch (error: unknown) {
    browseError.value = getApiErrorMessage(error, t('settings.pathPicker.browseFailed'))
    browseState.value = await configStore.browseFilesystem({
      path: '~',
      kind: props.kind,
      extensions: props.extensions
    })
    browseOpen.value = true
  }
}

function selectPath(path: string) {
  emit('update:modelValue', path)
  browseOpen.value = false
}

watch(
  () => props.modelValue,
  () => {
    validatePath()
  }
)

onMounted(validatePath)
</script>

<template>
  <div class="space-y-2">
    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        type="text"
        :value="modelValue"
        class="block min-w-0 flex-1 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
        @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
        @blur="validatePath"
      />
      <button
        type="button"
        class="inline-flex items-center justify-center rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
        @click="browse()"
      >
        <FolderIcon class="mr-2 h-4 w-4" />
        {{ t('settings.pathPicker.browse') }}
      </button>
    </div>
    <p
      v-if="validation && !validation.valid"
      class="text-xs font-medium text-red-600 dark:text-red-400"
    >
      {{ validation.error }}
    </p>
    <p
      v-else-if="validation?.warnings.length"
      class="text-xs font-medium text-amber-600 dark:text-amber-400"
    >
      {{ validation.warnings.join(', ') }}
    </p>
    <p v-else-if="validation?.valid" class="text-xs text-gray-500 dark:text-gray-400">
      {{ validation.exists ? t('settings.pathPicker.exists') : t('settings.pathPicker.later') }}
    </p>

    <div
      v-if="browseOpen"
      class="fixed inset-0 z-40 flex items-center justify-center bg-gray-900/60 p-4"
    >
      <div
        class="max-h-[85vh] w-full max-w-3xl overflow-hidden rounded-lg bg-white shadow-xl dark:bg-gray-800"
      >
        <div
          class="flex items-center justify-between border-b border-gray-200 px-4 py-3 dark:border-gray-700"
        >
          <div>
            <h3 class="text-sm font-semibold text-gray-900 dark:text-white">
              {{ t('settings.pathPicker.selectPath') }}
            </h3>
            <p class="text-xs text-gray-500 dark:text-gray-400">{{ browseState?.path }}</p>
          </div>
          <button
            type="button"
            class="rounded-md px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
            @click="browseOpen = false"
          >
            {{ t('common.close') }}
          </button>
        </div>
        <div
          class="grid max-h-[70vh] grid-cols-1 overflow-y-auto md:grid-cols-[12rem_minmax(0,1fr)]"
        >
          <aside
            class="border-b border-gray-200 p-3 dark:border-gray-700 md:border-b-0 md:border-r"
          >
            <p class="mb-2 text-xs font-semibold uppercase text-gray-500">
              {{ t('settings.pathPicker.shortcuts') }}
            </p>
            <button
              v-for="shortcut in browseState?.shortcuts || []"
              :key="shortcut.path"
              type="button"
              class="block w-full rounded-md px-2 py-1.5 text-left text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700"
              @click="browse(shortcut.path)"
            >
              {{ shortcut.name }}
            </button>
          </aside>
          <main class="p-3">
            <p v-if="browseError" class="mb-2 text-xs font-medium text-amber-600">
              {{ browseError }}
            </p>
            <div class="mb-3 flex gap-2">
              <button
                v-if="browseState?.parent"
                type="button"
                class="rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
                @click="browse(browseState.parent)"
              >
                {{ t('settings.pathPicker.up') }}
              </button>
              <button
                v-if="kind !== 'file' && browseState"
                type="button"
                class="rounded-md bg-indigo-600 px-2 py-1 text-sm font-medium text-white hover:bg-indigo-700"
                @click="selectPath(browseState.path)"
              >
                {{ t('settings.pathPicker.useFolder') }}
              </button>
            </div>
            <div
              class="divide-y divide-gray-100 rounded-lg border border-gray-200 dark:divide-gray-700 dark:border-gray-700"
            >
              <div
                v-for="entry in browseState?.entries || []"
                :key="entry.path"
                role="button"
                tabindex="0"
                class="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
                @click="entry.is_dir ? browse(entry.path) : selectPath(entry.path)"
                @keydown.enter="entry.is_dir ? browse(entry.path) : selectPath(entry.path)"
                @keydown.space.prevent="entry.is_dir ? browse(entry.path) : selectPath(entry.path)"
              >
                <span class="flex min-w-0 items-center gap-2">
                  <FolderIcon v-if="entry.is_dir" class="h-4 w-4 flex-shrink-0 text-amber-500" />
                  <DocumentIcon v-else class="h-4 w-4 flex-shrink-0 text-gray-500" />
                  <span class="truncate text-gray-900 dark:text-white">{{ entry.name }}</span>
                </span>
                <button
                  v-if="entry.is_dir && kind === 'directory'"
                  type="button"
                  class="ml-3 rounded-md px-2 py-1 text-xs font-medium text-indigo-700 hover:bg-indigo-50 dark:text-indigo-300 dark:hover:bg-indigo-500/10"
                  @click.stop="selectPath(entry.path)"
                >
                  {{ t('settings.pathPicker.select') }}
                </button>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  </div>
</template>
