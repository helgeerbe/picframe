import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

/**
 * A discovered overlay plugin with its effective (merged) config, mirroring the
 * backend `OverlayPluginResponse` Pydantic model (#739, #752).
 */
export interface OverlayPlugin {
  id: string
  name: string
  description: string
  icon: string
  trigger: string
  position: string
  has_config: boolean
  /** Manifest design size `{ w, h }` in CSS px; `null` for fill-mode plugins.
   * The settings UI branches on this: scale-mode plugins show a Scale slider,
   * fill-mode plugins show Width/Height (#752). */
  size?: { w: number; h: number } | null
  // The dynamic config_schema is an arbitrary mapping the UI renders by type;
  // `unknown`/`Record<string, unknown>` keeps the index accesses ergonomic.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config_schema: Record<string, Record<string, any>>
  /** Effective per-plugin config. Redacted from the public plugin *list* (may
   *  carry secrets such as the weather api_key); fetch on demand via
   *  `fetchPluginConfig` (Settings-protected) when editing (#756). Absent from
   *  the list response. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config?: Record<string, any>
  /** Effective per-plugin layout (#752): manifest defaults <- db overrides. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  layout?: Record<string, any>
}

export const useOverlayStore = defineStore('overlay', () => {
  const plugins = ref<OverlayPlugin[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function fetchPlugins() {
    isLoading.value = true
    error.value = null
    try {
      const response = await api.get('/overlay/plugins')
      plugins.value = response.data as OverlayPlugin[]
    } catch (e: unknown) {
      error.value = getApiErrorMessage(e, 'Failed to load overlay plugins')
      console.error(e)
      plugins.value = []
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Fetch a single plugin's effective config (manifest defaults merged with
   * persisted user values) from the Settings-protected per-plugin endpoint.
   * The public plugin *list* redacts `config` (it may carry secrets such as
   * the weather api_key), so the Settings config editor loads values on demand
   * here (#756). Throws on HTTP error.
   */
  async function fetchPluginConfig(pluginId: string) {
    const response = await api.get(`/overlay/plugins/${encodeURIComponent(pluginId)}/config`)
    return response.data as {
      plugin_id: string
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      config: Record<string, any>
    }
  }

  /**
   * Validate and persist a single plugin's config. Returns the validated
   * config the backend persisted, or throws on validation/HTTP error.
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  async function updatePluginConfig(pluginId: string, config: Record<string, any>) {
    const response = await api.put(
      `/overlay/plugins/${encodeURIComponent(pluginId)}/config`,
      config
    )
    return response.data as {
      status: string
      message?: string
      plugin_id: string
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      config: Record<string, any>
    }
  }

  /**
   * Validate and persist a single plugin's layout (#752): position/scale/
   * width/height/display_mode/idle_hide_seconds/z_order. Returns the
   * effective (merged) layout the backend persisted, or throws on
   * validation/HTTP error. `null` values mean "inherit/default" and are not
   * stored (an absent key reads back as the manifest default).
   */
  async function updatePluginLayout(
    pluginId: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    layout: Record<string, any>
  ) {
    const response = await api.put(
      `/overlay/plugins/${encodeURIComponent(pluginId)}/layout`,
      layout
    )
    return response.data as {
      status: string
      message?: string
      plugin_id: string
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      layout: Record<string, any>
    }
  }

  /**
   * Validate and persist the dock (plugin-icon row) placement (#758):
   * position/margin/idle_hide_seconds. Returns the validated dock layout the
   * backend persisted, or throws on validation/HTTP error. `null`
   * `idle_hide_seconds` means "inherit the global value" and is not stored.
   */
  async function updateDockLayout(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    layout: Record<string, any>
  ) {
    const response = await api.put('/overlay/dock-layout', layout)
    return response.data as {
      status: string
      message?: string
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      dock_layout: Record<string, any>
    }
  }

  return {
    plugins,
    isLoading,
    error,
    fetchPlugins,
    fetchPluginConfig,
    updatePluginConfig,
    updatePluginLayout,
    updateDockLayout
  }
})
