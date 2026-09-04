<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ChevronDownIcon, Squares2X2Icon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import { useOverlayStore } from '../../stores/overlay'
import { useConfigStore } from '../../stores/config'
import StatusBanner from '../ui/StatusBanner.vue'

const { t } = useI18n()
const overlayStore = useOverlayStore()
const configStore = useConfigStore()
const { config } = storeToRefs(configStore)
const { plugins, isLoading, error: overlayError } = storeToRefs(overlayStore)

const isExpanded = ref(true)
const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')
let statusTimer: number | undefined

const overlayEnabled = computed(() => config.value?.overlay?.enabled === true)

const enabledPlugins = computed<string[]>(() => {
  const ov = config.value?.overlay
  return Array.isArray(ov?.enabled_plugins) ? [...(ov!.enabled_plugins as string[])] : []
})

const visiblePlugins = computed<string[]>(() => {
  const v = config.value?.overlay?.visible_plugins
  return Array.isArray(v) ? [...(v as string[])] : []
})

// Only plugins the user has activated (via Appearance) appear as tiles.
const dockPlugins = computed(() => plugins.value.filter(p => enabledPlugins.value.includes(p.id)))

const showStatus = (tone: 'success' | 'danger', message: string) => {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer)
  statusTone.value = tone
  statusMessage.value = message
  statusTimer = window.setTimeout(() => {
    statusMessage.value = ''
  }, 3000)
}

// Toggle a plugin in/out of the visible set (#752 multi-widget). Several
// plugins can be expanded at once; tapping an active tile collapses just it.
const toggleVisible = async (pluginId: string) => {
  if (isSaving.value) return
  const next = visiblePlugins.value.includes(pluginId)
    ? visiblePlugins.value.filter(id => id !== pluginId)
    : [...visiblePlugins.value, pluginId]
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({ overlay: { visible_plugins: next } })
    showStatus('success', t('remote.touchOverlay.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('remote.touchOverlay.failed'))
  } finally {
    isSaving.value = false
  }
}

// Collapse all panels back to dock-only.
const setDockOnly = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({ overlay: { visible_plugins: [] } })
    showStatus('success', t('remote.touchOverlay.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('remote.touchOverlay.failed'))
  } finally {
    isSaving.value = false
  }
}

onMounted(async () => {
  await overlayStore.fetchPlugins()
  // Plugin discovery (`GET /api/overlay/plugins`) is settings-auth-protected, so
  // a 401 here means the caller is not authenticated to manage the overlay and
  // the dock is non-functional regardless. In that case we must NOT call
  // `fetchConfig()` (also settings-protected): its failure would clobber the
  // shared `configStore.error`, which Remote renders as the "media selection
  // unavailable" banner and would break Remote's core UI (#750). The contained
  // `overlayError` is already shown in-panel.
  if (overlayError.value) return
  // `fetchConfig()` (full) is required: the workflow-config allowlist excludes
  // enabled_plugins/visible_plugins, which the dock reads live.
  const ov = config.value?.overlay
  if (!Array.isArray(ov?.enabled_plugins)) {
    await configStore.fetchConfig()
  }
})
</script>

<template>
  <!-- The whole panel is hidden when the master overlay toggle is off (#750). -->
  <div
    v-if="overlayEnabled"
    class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800"
  >
    <button
      type="button"
      class="flex w-full items-center justify-between border-b border-gray-100 bg-white px-6 py-5 text-left transition-colors hover:bg-gray-50 dark:border-gray-700/50 dark:bg-gray-800 dark:hover:bg-gray-700/40"
      :aria-expanded="isExpanded"
      @click="isExpanded = !isExpanded"
    >
      <div class="flex items-center space-x-3 overflow-hidden">
        <div class="flex-shrink-0 rounded-lg bg-violet-50 p-2 dark:bg-violet-500/10">
          <Squares2X2Icon class="h-5 w-5 text-violet-600 dark:text-violet-400" />
        </div>
        <div class="min-w-0">
          <h3 class="truncate text-lg font-bold tracking-tight text-gray-900 dark:text-white">
            {{ t('remote.touchOverlay.title') }}
          </h3>
          <p class="mt-0.5 truncate text-xs text-gray-500 dark:text-gray-400">
            {{ t('remote.touchOverlay.description') }}
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="!isLoading"
          type="button"
          class="rounded-lg p-2 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-700/50 dark:hover:text-gray-200"
          :title="t('common.retry')"
          @click.stop="overlayStore.fetchPlugins()"
        >
          <ArrowPathIcon class="h-4 w-4" />
        </button>
        <ChevronDownIcon
          class="h-5 w-5 flex-shrink-0 text-gray-400 transition-transform"
          :class="{ 'rotate-180': isExpanded }"
        />
      </div>
    </button>

    <div v-show="isExpanded" class="p-6">
      <div
        v-if="isLoading"
        class="flex justify-center py-6"
        role="status"
        :aria-label="t('remote.touchOverlay.loading')"
      >
        <div class="h-8 w-8 animate-spin rounded-full border-b-2 border-violet-600"></div>
      </div>

      <div v-else-if="overlayError" class="py-2">
        <StatusBanner tone="danger" :message="overlayError" />
      </div>

      <div v-else-if="plugins.length === 0" class="py-6 text-center">
        <p class="text-sm text-gray-500 dark:text-gray-400">
          {{ t('remote.touchOverlay.noPluginsDiscovered') }}
        </p>
      </div>

      <div v-else-if="dockPlugins.length === 0" class="py-6 text-center">
        <p class="text-sm text-gray-500 dark:text-gray-400">
          {{ t('remote.touchOverlay.empty') }}
        </p>
      </div>

      <div v-else class="space-y-5">
        <p class="text-xs text-gray-500 dark:text-gray-400">
          {{ t('remote.touchOverlay.description') }}
        </p>

        <!-- Tile dock: one tile per activated plugin. Several can be active at once (#752). -->
        <div class="flex flex-wrap gap-3">
          <button
            v-for="plugin in dockPlugins"
            :key="plugin.id"
            type="button"
            :disabled="isSaving"
            :aria-pressed="visiblePlugins.includes(plugin.id)"
            :title="
              visiblePlugins.includes(plugin.id)
                ? t('remote.touchOverlay.collapse')
                : t('remote.touchOverlay.expand', { plugin: plugin.name || plugin.id })
            "
            :class="[
              visiblePlugins.includes(plugin.id)
                ? 'border-violet-500 bg-violet-50 ring-2 ring-violet-500/40 dark:bg-violet-500/15 dark:ring-violet-400/40'
                : 'border-gray-200 bg-white hover:bg-gray-50 dark:border-gray-700 dark:bg-gray-800 dark:hover:bg-gray-700/40',
              'flex min-w-[7rem] flex-col items-center gap-1.5 rounded-xl border px-4 py-3 text-center transition-colors disabled:cursor-not-allowed disabled:opacity-60'
            ]"
            @click="toggleVisible(plugin.id)"
          >
            <span class="text-xl leading-none" aria-hidden="true">{{ plugin.icon || '🗂️' }}</span>
            <span class="text-xs font-semibold text-gray-900 dark:text-white">{{
              plugin.name || plugin.id
            }}</span>
          </button>
        </div>

        <div v-if="visiblePlugins.length > 0" class="flex items-center justify-end">
          <button
            type="button"
            :disabled="isSaving"
            class="text-xs font-semibold text-violet-600 transition-colors hover:text-violet-500 disabled:opacity-60 dark:text-violet-400"
            @click="setDockOnly()"
          >
            {{ t('remote.touchOverlay.dockOnly') }}
          </button>
        </div>

        <StatusBanner v-if="statusMessage" :tone="statusTone" :message="statusMessage" />
      </div>
    </div>
  </div>
</template>
