<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { DocumentIcon, FolderIcon } from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import { useConfigStore, type FilesystemBrowseResponse } from '../../stores/config'
import { getApiErrorMessage } from '../../utils/errors'

const props = defineProps<{
  modelValue: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const configStore = useConfigStore()
const { t } = useI18n()
const browseOpen = ref(false)
const browseState = ref<FilesystemBrowseResponse | null>(null)
const browseError = ref('')
const validationError = ref('')

const normalizedValue = computed(() => stripShaderExtension(props.modelValue || ''))
const counterpartState = computed(() => {
  if (!browseState.value || !normalizedValue.value) return { hasFs: false, hasVs: false }
  const base = basename(normalizedValue.value)
  const hasFs = browseState.value.entries.some(entry => entry.name === `${base}.fs`)
  const hasVs = browseState.value.entries.some(entry => entry.name === `${base}.vs`)
  return { hasFs, hasVs }
})

function stripShaderExtension(value: string) {
  return value.trim().replace(/\.(fs|vs)$/i, '')
}

function dirname(value: string) {
  const stripped = stripShaderExtension(value)
  const index = stripped.lastIndexOf('/')
  if (index < 0) return '${PICFRAME_DATA}/shaders'
  if (index === 0) return '/'
  return stripped.slice(0, index)
}

function basename(value: string) {
  const stripped = stripShaderExtension(value)
  const index = stripped.lastIndexOf('/')
  return index < 0 ? stripped : stripped.slice(index + 1)
}

function emitNormalized(value: string) {
  emit('update:modelValue', stripShaderExtension(value))
}

async function validateShader() {
  validationError.value = ''
  if (!normalizedValue.value) return

  const checks = [
    { path: `${normalizedValue.value}.fs`, extension: '.fs' },
    { path: `${normalizedValue.value}.vs`, extension: '.vs' }
  ]
  for (const check of checks) {
    try {
      const result = await configStore.validateFilesystemPath({
        path: check.path,
        kind: 'file',
        extensions: [check.extension]
      })
      if (!result.valid) {
        validationError.value = `${check.path}: ${result.error}`
        return
      }
    } catch (error: unknown) {
      validationError.value = getApiErrorMessage(error, t('settings.shaderPicker.validateFailed'))
      return
    }
  }
}

async function browse(path = dirname(normalizedValue.value || '${PICFRAME_DATA}/shaders')) {
  browseError.value = ''
  try {
    browseState.value = await configStore.browseFilesystem({
      path,
      kind: 'file',
      extensions: ['.fs', '.vs']
    })
  } catch (error: unknown) {
    browseError.value = getApiErrorMessage(error, t('settings.shaderPicker.browseFailed'))
    browseState.value = await configStore.browseFilesystem({
      path: '~',
      kind: 'file',
      extensions: ['.fs', '.vs']
    })
  }
  browseOpen.value = true
}

function selectEntry(path: string, isDir: boolean) {
  if (isDir) {
    browse(path)
    return
  }
  emitNormalized(path)
  browseOpen.value = false
}

watch(
  () => props.modelValue,
  value => {
    const stripped = stripShaderExtension(value || '')
    if (value && value !== stripped) emit('update:modelValue', stripped)
    validateShader()
  }
)

onMounted(() => {
  validateShader()
  if (props.modelValue)
    browse(dirname(props.modelValue)).then(() => {
      browseOpen.value = false
    })
})
</script>

<template>
  <div class="space-y-2">
    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        type="text"
        :value="normalizedValue"
        class="block min-w-0 flex-1 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 shadow-sm focus:border-indigo-500 focus:ring-indigo-500 dark:border-gray-600 dark:bg-gray-700 dark:text-white"
        @input="emitNormalized(($event.target as HTMLInputElement).value)"
        @blur="emitNormalized(($event.target as HTMLInputElement).value)"
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
    <p class="text-xs text-gray-500 dark:text-gray-400">
      {{ t('settings.shaderPicker.storedWithoutExtension', { value: normalizedValue }) }}
    </p>
    <p v-if="validationError" class="text-xs font-medium text-red-600 dark:text-red-400">
      {{ validationError }}
    </p>
    <p
      v-if="browseState && (!counterpartState.hasFs || !counterpartState.hasVs)"
      class="text-xs font-medium text-amber-600 dark:text-amber-400"
    >
      {{ t('settings.shaderPicker.incompletePair', { name: basename(normalizedValue) }) }}
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
              {{ t('settings.shaderPicker.selectShader') }}
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
        <div class="p-3">
          <p v-if="browseError" class="mb-2 text-xs font-medium text-amber-600">
            {{ browseError }}
          </p>
          <button
            v-if="browseState?.parent"
            type="button"
            class="mb-3 rounded-md border border-gray-300 px-2 py-1 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-700"
            @click="browse(browseState.parent)"
          >
            {{ t('settings.pathPicker.up') }}
          </button>
          <div
            class="max-h-[60vh] divide-y divide-gray-100 overflow-y-auto rounded-lg border border-gray-200 dark:divide-gray-700 dark:border-gray-700"
          >
            <button
              v-for="entry in browseState?.entries || []"
              :key="entry.path"
              type="button"
              class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700"
              @click="selectEntry(entry.path, entry.is_dir)"
            >
              <FolderIcon v-if="entry.is_dir" class="h-4 w-4 flex-shrink-0 text-amber-500" />
              <DocumentIcon v-else class="h-4 w-4 flex-shrink-0 text-gray-500" />
              <span class="truncate text-gray-900 dark:text-white">{{
                entry.is_dir ? entry.name : stripShaderExtension(entry.name)
              }}</span>
              <span v-if="!entry.is_dir" class="text-xs text-gray-500">{{ entry.extension }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
