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

/** Global idle fade (the per-plugin default when a layout omits it). */
const overlay = reactive({
  idle_hide_seconds: 5
})

/** Nine anchors for the position/content_align selects (#752). */
const ANCHORS = [
  'top-left',
  'top-center',
  'top-right',
  'middle-left',
  'middle-center',
  'middle-right',
  'bottom-left',
  'bottom-center',
  'bottom-right'
] as const

const overlayEnabled = computed(() => config.value?.overlay?.enabled === true)

const enabledPlugins = computed<string[]>(() => {
  const ov = config.value?.overlay
  return Array.isArray(ov?.enabled_plugins) ? [...(ov!.enabled_plugins as string[])] : []
})

const visiblePlugins = computed<string[]>(() => {
  const v = config.value?.overlay?.visible_plugins
  return Array.isArray(v) ? [...(v as string[])] : []
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
  overlay.idle_hide_seconds = asNumber(ov.idle_hide_seconds, 5)
}

const saveIdle = async () => {
  if (isSaving.value) return
  isSaving.value = true
  statusMessage.value = ''
  try {
    await configStore.savePartialConfig({
      overlay: { idle_hide_seconds: Number(overlay.idle_hide_seconds) }
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
  // If disabling a plugin, also remove it from the visible set (#752).
  if (!activate && visiblePlugins.value.includes(plugin.id)) {
    patch.visible_plugins = visiblePlugins.value.filter(id => id !== plugin.id)
  }
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

/** Effective layout for a plugin (from the discovered plugin's merged layout),
 * or sensible defaults. Drives the per-plugin layout editor working copy. */
const layoutOf = (plugin: OverlayPlugin): Record<string, unknown> => {
  const l = plugin.layout ?? {}
  return {
    position: l.position ?? plugin.position ?? 'top-right',
    width: l.width ?? 0,
    height: l.height ?? 0,
    content_align: l.content_align ?? '',
    display_mode: l.display_mode ?? 'auto_hide',
    idle_hide_seconds: l.idle_hide_seconds ?? 0,
    z_order: l.z_order ?? 0
  }
}

/** Per-plugin layout working copies, keyed by plugin id. */
const layoutDrafts = reactive<Record<string, Record<string, unknown>>>({})

const ensureDraft = (plugin: OverlayPlugin): Record<string, unknown> => {
  if (!layoutDrafts[plugin.id]) {
    layoutDrafts[plugin.id] = layoutOf(plugin)
  }
  return layoutDrafts[plugin.id]
}

/** Save a plugin's layout via the dedicated PUT endpoint (#752). 0/empty for
 * width/height/idle_hide_seconds/content_align is sent as null (inherit/default). */
const saveLayout = async (plugin: OverlayPlugin) => {
  if (isSaving.value) return
  const draft = layoutDrafts[plugin.id]
  if (!draft) return
  const payload: Record<string, unknown> = {
    position: draft.position,
    display_mode: draft.display_mode,
    z_order: Number(draft.z_order) || 0
  }
  const w = Number(draft.width)
  payload.width = Number.isFinite(w) && w > 0 ? Math.round(w) : null
  const h = Number(draft.height)
  payload.height = Number.isFinite(h) && h > 0 ? Math.round(h) : null
  const align = draft.content_align
  payload.content_align = align && align !== '' ? align : null
  const idle = Number(draft.idle_hide_seconds)
  payload.idle_hide_seconds = Number.isFinite(idle) && idle > 0 ? idle : null
  isSaving.value = true
  statusMessage.value = ''
  try {
    const result = await overlayStore.updatePluginLayout(plugin.id, payload)
    // Reflect the effective layout the backend persisted back into the draft.
    layoutDrafts[plugin.id] = result.layout
    showStatus('success', t('appearance.overlay.layout.saved'))
  } catch (e) {
    console.error(e)
    showStatus('danger', t('appearance.overlay.layout.failed'))
  } finally {
    isSaving.value = false
  }
}

onMounted(async () => {
  // `fetchConfig()` (full) is required here: Appearance otherwise only loads
  // the workflow-config allowlist, which excludes enabled_plugins/visible_plugins.
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
  () => [config.value?.overlay?.idle_hide_seconds],
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
          :label="t('appearance.overlay.idleHideSeconds.label')"
          :help="t('appearance.overlay.idleHideSeconds.help')"
        >
          <NumberField
            v-model="overlay.idle_hide_seconds"
            :min="0"
            :step="0.5"
            unit="s"
            @update:model-value="saveIdle()"
          />
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
            <li v-for="plugin in plugins" :key="plugin.id" class="py-4 first:pt-0 last:pb-0">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span v-if="plugin.icon" class="text-base leading-none">{{ plugin.icon }}</span>
                    <span class="truncate text-sm font-semibold text-gray-900 dark:text-white">
                      {{ plugin.name || plugin.id }}
                    </span>
                  </div>
                  <p
                    v-if="plugin.description"
                    class="mt-1 text-xs text-gray-500 dark:text-gray-400"
                  >
                    {{ plugin.description }}
                  </p>
                </div>
                <ToggleSwitch
                  :model-value="enabledPlugins.includes(plugin.id)"
                  :disabled="isSaving"
                  :label="t('appearance.overlay.plugins.activate')"
                  @update:model-value="value => togglePlugin(plugin, value)"
                />
              </div>

              <!-- Per-plugin layout editor (#752): shown only for activated
                   plugins. Position, display mode, size, z-order, and a
                   per-plugin idle fade (0 = inherit the global value above). -->
              <div
                v-if="enabledPlugins.includes(plugin.id)"
                class="mt-4 rounded-lg border border-gray-200 bg-gray-50 p-4 dark:border-gray-700 dark:bg-gray-900/40"
              >
                <h4
                  class="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400"
                >
                  {{ t('appearance.overlay.layout.title') }}
                </h4>
                <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label
                      class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                      :for="`layout-${plugin.id}-position`"
                      >{{ t('appearance.overlay.layout.position') }}</label
                    >
                    <select
                      :id="`layout-${plugin.id}-position`"
                      v-model="ensureDraft(plugin)['position']"
                      class="w-full rounded-md border border-gray-300 bg-white px-2 py-1.5 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
                    >
                      <option v-for="a in ANCHORS" :key="a" :value="a">{{ a }}</option>
                    </select>
                  </div>
                  <div>
                    <label
                      class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                      :for="`layout-${plugin.id}-display-mode`"
                      >{{ t('appearance.overlay.layout.displayMode') }}</label
                    >
                    <SegmentedControl
                      :model-value="ensureDraft(plugin)['display_mode'] as string"
                      :options="[
                        {
                          value: 'persistent',
                          label: t('appearance.overlay.displayMode.persistent')
                        },
                        { value: 'auto_hide', label: t('appearance.overlay.displayMode.autoHide') }
                      ]"
                      @update:model-value="ensureDraft(plugin)['display_mode'] = $event as string"
                    />
                  </div>
                  <div>
                    <label
                      class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                      :for="`layout-${plugin.id}-width`"
                      >{{ t('appearance.overlay.layout.width') }}</label
                    >
                    <NumberField
                      :model-value="(ensureDraft(plugin)['width'] as number) ?? 0"
                      :min="0"
                      :step="10"
                      unit="px"
                      @update:model-value="ensureDraft(plugin)['width'] = $event"
                    />
                  </div>
                  <div>
                    <label
                      class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                      :for="`layout-${plugin.id}-height`"
                      >{{ t('appearance.overlay.layout.height') }}</label
                    >
                    <NumberField
                      :model-value="(ensureDraft(plugin)['height'] as number) ?? 0"
                      :min="0"
                      :step="10"
                      unit="px"
                      @update:model-value="ensureDraft(plugin)['height'] = $event"
                    />
                  </div>
                  <div>
                    <label
                      class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                      :for="`layout-${plugin.id}-z-order`"
                      >{{ t('appearance.overlay.layout.zOrder') }}</label
                    >
                    <NumberField
                      :model-value="(ensureDraft(plugin)['z_order'] as number) ?? 0"
                      :min="0"
                      :step="1"
                      @update:model-value="ensureDraft(plugin)['z_order'] = $event"
                    />
                  </div>
                  <div>
                    <label
                      class="mb-1 block text-xs font-medium text-gray-600 dark:text-gray-300"
                      :for="`layout-${plugin.id}-idle`"
                      >{{ t('appearance.overlay.layout.idleHideSeconds') }}</label
                    >
                    <NumberField
                      :model-value="(ensureDraft(plugin)['idle_hide_seconds'] as number) ?? 0"
                      :min="0"
                      :step="0.5"
                      unit="s"
                      @update:model-value="ensureDraft(plugin)['idle_hide_seconds'] = $event"
                    />
                  </div>
                </div>
                <p class="mt-2 text-xs text-gray-400 dark:text-gray-500">
                  {{ t('appearance.overlay.layout.inheritHint') }}
                </p>
                <div class="mt-3 flex justify-end">
                  <button
                    type="button"
                    :disabled="isSaving"
                    class="rounded-md bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-violet-500 disabled:opacity-60 dark:bg-violet-500 dark:hover:bg-violet-400"
                    @click="saveLayout(plugin)"
                  >
                    {{ t('appearance.overlay.layout.save') }}
                  </button>
                </div>
              </div>
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
