import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

/**
 * A discovered overlay plugin with its effective (merged) config, mirroring the
 * backend `OverlayPluginResponse` Pydantic model (#739).
 */
export interface OverlayPlugin {
  id: string
  name: string
  description: string
  icon: string
  trigger: string
  position: string
  has_config: boolean
  // The dynamic config_schema is an arbitrary mapping the UI renders by type;
  // `unknown`/`Record<string, unknown>` keeps the index accesses ergonomic.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config_schema: Record<string, Record<string, any>>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config: Record<string, any>
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

  return {
    plugins,
    isLoading,
    error,
    fetchPlugins,
    updatePluginConfig
  }
})
