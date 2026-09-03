<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useI18n } from 'vue-i18n'
import { ComputerDesktopIcon } from '@heroicons/vue/24/outline'
import { useConfigStore } from '../stores/config'
import { useOverlayStore, type OverlayPlugin } from '../stores/overlay'
import FieldRow from './settings/FieldRow.vue'
import NumberField from './settings/NumberField.vue'
import SegmentedControl from './settings/SegmentedControl.vue'
import ToggleSwitch from './settings/ToggleSwitch.vue'
import Panel from './ui/Panel.vue'
import StatusBanner from './ui/StatusBanner.vue'

const { t } = useI18n()
const configStore = useConfigStore()
const overlayStore = useOverlayStore()
const { config } = storeToRefs(configStore)
const { plugins, isLoading: isPluginsLoading, error: overlayError } = storeToRefs(overlayStore)

const isSaving = ref(false)
const statusMessage = ref('')
const statusTone = ref<'success' | 'danger'>('success')
let statusTimer: number | undefined

const overlay = reactive({
  display_mode: 'auto_hide' as 'persistent' | 'auto_hide',
  auto_hide_seconds: 5,
  idle_hide_seconds: 5,
  transparent: true
})

const overlayEnabled = computed(() => config.value?.overlay?.enabled === true)

const enabledPlugins = computed<string[]>(() => {
  const ov = config.value?.overlay
  return Array.isArray(ov?.enabled_plugins) ? [...(ov!.enabled_plugins as string[])] : []
})

const visiblePlugin = computed<string | null>(() => {
  const v = config.value?.overlay?.visible_plugin
  return typeof v === 'string' ? v : null
})

const showStatus = (tone: 'success' | 'danger', message: string) => {
  if (statusTimer !== undefined) window.clearTimeout(statusTimer)
  statusTone.value = tone
  statusMessage.value = message
  statusTimer = window.setTimeout(() => {
    statusMessage.value = ''
  }, 3000)
}

const asNumber = (value: unknown, fallback: number) => {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

const syncFromConfig = () => {
  const ov = config.value?.overlay || {}
  overlay.display_mode = ov.display_mode === 'persistent' ? 'persistent' : 'auto_hide'
  overlay.auto_hide_seconds = asNumber(ov.auto_hide_seconds, 5)
  overlay.idle_hide_seconds = asNumber(ov.idle_hide_seconds, 5)
  overlay.transparent = ov.transparent !== false
}

const save = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({
      overlay: {
        display_mode: overlay.display_mode,
        auto_hide_seconds: Number(overlay.auto_hide_seconds),
        idle_hide_seconds: Number(overlay.idle_hide_seconds),
        transparent: Boolean(overlay.transparent)
      }
    })
    showStatus('success', t('appearance.overlay.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('appearance.overlay.failed'))
    syncFromConfig()
  } finally {
    isSaving.value = false
  }
}

const togglePlugin = async (plugin: OverlayPlugin, activate: boolean) => {
  if (isSaving.value) return
  let next = activate
    ? [...enabledPlugins.value, plugin.id]
    : enabledPlugins.value.filter(id => id !== plugin.id)
  // Drop ids that no longer correspond to a discovered plugin.
  next = next.filter(id => plugins.value.some(p => p.id === id))
  const patch: Record<string, unknown> = { enabled_plugins: next }
  // If disabling the currently visible plugin, clear it.
  if (!activate && visiblePlugin.value === plugin.id) patch.visible_plugin = null
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({ overlay: patch })
    showStatus('success', t('appearance.overlay.plugins.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('appearance.overlay.plugins.failed'))
  } finally {
    isSaving.value = false
  }
}

onMounted(async () => {
  // `fetchConfig()` (full) is required here: Appearance otherwise only loads
  // the workflow-config allowlist, which excludes enabled_plugins/visible_plugin.
  const ov = config.value?.overlay
  if (
    !config.value ||
    Object.keys(config.value).length === 0 ||
    !Array.isArray(ov?.enabled_plugins)
  ) {
    await configStore.fetchConfig()
  }
  await overlayStore.fetchPlugins()
  syncFromConfig()
})

watch(
  () => [config.value?.overlay?.display_mode, config.value?.overlay?.auto_hide_seconds],
  () => {
    if (!isSaving.value) syncFromConfig()
  }
)
</script>

<template>
  <Panel padded>
    <div class="space-y-6">
      <div class="border-b border-gray-100 pb-5 dark:border-gray-700/60">
        <div class="flex items-center gap-3">
          <div
            class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
          >
            <ComputerDesktopIcon class="h-5 w-5" />
          </div>
          <div>
            <h2 class="text-lg font-semibold text-gray-950 dark:text-white">
              {{ t('appearance.overlay.title') }}
            </h2>
            <p class="mt-0.5 text-sm leading-6 text-gray-600 dark:text-gray-300">
              {{ t('appearance.overlay.description') }}
            </p>
          </div>
        </div>
      </div>

      <div>
        <FieldRow
          :label="t('appearance.overlay.displayMode.label')"
          :help="t('appearance.overlay.displayMode.help')"
        >
          <SegmentedControl
            :model-value="overlay.display_mode"
            :options="[
              { value: 'persistent', label: t('appearance.overlay.displayMode.persistent') },
              { value: 'auto_hide', label: t('appearance.overlay.displayMode.autoHide') }
            ]"
            @update:model-value="
              value => {
                overlay.display_mode = value as 'persistent' | 'auto_hide'
                save()
              }
            "
          />
        </FieldRow>

        <FieldRow
          v-if="overlay.display_mode === 'auto_hide'"
          :label="t('appearance.overlay.autoHideSeconds.label')"
          :help="t('appearance.overlay.autoHideSeconds.help')"
        >
          <NumberField
            v-model="overlay.auto_hide_seconds"
            :min="1"
            :step="1"
            unit="s"
            @update:model-value="save()"
          />
        </FieldRow>

        <FieldRow
          :label="t('appearance.overlay.idleHideSeconds.label')"
          :help="t('appearance.overlay.idleHideSeconds.help')"
        >
          <NumberField
            v-model="overlay.idle_hide_seconds"
            :min="0"
            :step="0.5"
            unit="s"
            @update:model-value="save()"
          />
        </FieldRow>

        <FieldRow
          :label="t('appearance.overlay.transparent.label')"
          :help="t('appearance.overlay.transparent.help')"
        >
          <ToggleSwitch v-model="overlay.transparent" @update:model-value="save()" />
        </FieldRow>
      </div>

      <!-- Plugin catalog: activate which overlay plugins the frame offers -->
      <div class="border-t border-gray-100 pt-6 dark:border-gray-700/60">
        <div class="mb-4">
          <h3 class="text-sm font-semibold text-gray-950 dark:text-white">
            {{ t('appearance.overlay.plugins.title') }}
          </h3>
          <p class="mt-0.5 text-xs leading-5 text-gray-500 dark:text-gray-400">
            {{ t('appearance.overlay.plugins.description') }}
          </p>
        </div>

        <div
          v-if="isPluginsLoading"
          class="flex justify-center py-6"
          role="status"
          :aria-label="t('remote.touchOverlay.loading')"
        >
          <div class="h-8 w-8 animate-spin rounded-full border-b-2 border-violet-600"></div>
        </div>

        <div v-else-if="overlayError" class="py-2">
          <StatusBanner tone="danger" :message="overlayError" />
        </div>

        <div
          v-else-if="plugins.length === 0"
          class="py-4 text-center text-sm text-gray-500 dark:text-gray-400"
        >
          {{ t('appearance.overlay.plugins.noPlugins') }}
        </div>

        <div v-else :class="{ 'pointer-events-none opacity-50': !overlayEnabled }">
          <p
            v-if="!overlayEnabled"
            class="mb-4 text-xs leading-relaxed text-amber-700 dark:text-amber-300"
          >
            {{ t('appearance.overlay.plugins.enableFirstHint') }}
          </p>
          <ul class="divide-y divide-gray-100 dark:divide-gray-700/60">
            <li
              v-for="plugin in plugins"
              :key="plugin.id"
              class="flex items-start justify-between gap-3 py-4 first:pt-0 last:pb-0"
            >
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span v-if="plugin.icon" class="text-base leading-none">{{ plugin.icon }}</span>
                  <span class="truncate text-sm font-semibold text-gray-900 dark:text-white">
                    {{ plugin.name || plugin.id }}
                  </span>
                </div>
                <p v-if="plugin.description" class="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {{ plugin.description }}
                </p>
              </div>
              <ToggleSwitch
                :model-value="enabledPlugins.includes(plugin.id)"
                :disabled="isSaving"
                :label="t('appearance.overlay.plugins.activate')"
                @update:model-value="value => togglePlugin(plugin, value)"
              />
            </li>
          </ul>
        </div>
      </div>

      <div v-if="statusMessage">
        <StatusBanner :tone="statusTone" :message="statusMessage" />
      </div>
    </div>
  </Panel>
</template>
