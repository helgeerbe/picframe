import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export interface FilterOptions {
  subdirectories: string[]
  locations: string[]
  tags: string[]
  sort_columns: Array<{ key: string, label: string }>
}

export interface MediaSelectionCount {
  selected_count: number
  total_count: number
  scope: string
  scope_label: string
}

export interface FilesystemEntry {
  name: string
  path: string
  is_dir: boolean
  is_file: boolean
  extension: string
}

export interface FilesystemBrowseResponse {
  root: string
  path: string
  parent: string | null
  entries: FilesystemEntry[]
  shortcuts: FilesystemEntry[]
}

export interface FilesystemValidateResponse {
  valid: boolean
  path: string
  exists: boolean
  is_dir: boolean
  is_file: boolean
  warnings: string[]
  error: string
}

function isPlainObject(value: unknown): value is Record<string, any> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function mergeConfig(base: Record<string, any>, patch: Record<string, any>): Record<string, any> {
  const merged = { ...base }
  for (const [key, value] of Object.entries(patch)) {
    merged[key] = isPlainObject(value) && isPlainObject(merged[key])
      ? mergeConfig(merged[key], value)
      : value
  }
  return merged
}

export const useConfigStore = defineStore('config', () => {
  const config = ref<Record<string, any>>({})
  const filterOptions = ref<FilterOptions>({
    subdirectories: [],
    locations: [],
    tags: [],
    sort_columns: []
  })
  const selectionCount = ref<MediaSelectionCount>({
    selected_count: 0,
    total_count: 0,
    scope: 'pic_dir',
    scope_label: ''
  })
  const isLoading = ref(false)
  const isSelectionCountLoading = ref(false)
  const error = ref<string | null>(null)
  const selectionCountError = ref<string | null>(null)

  async function fetchConfig() {
    isLoading.value = true
    error.value = null
    try {
      const response = await api.get('/config')
      config.value = response.data
    } catch (e: any) {
      error.value = e.message || 'Failed to fetch configuration'
      console.error(e)
    } finally {
      isLoading.value = false
    }
  }

  async function saveConfig(newConfig: Record<string, any>) {
    isLoading.value = true
    error.value = null
    try {
      await api.put('/config', newConfig)
      config.value = newConfig
    } catch (e: any) {
      error.value = e.message || 'Failed to save configuration'
      console.error(e)
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function savePartialConfig(partialConfig: Record<string, any>) {
    isLoading.value = true
    error.value = null
    try {
      await api.put('/config', partialConfig)
      config.value = mergeConfig(config.value, partialConfig)
    } catch (e: any) {
      error.value = e.message || 'Failed to save configuration'
      console.error(e)
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function fetchFilterOptions() {
    try {
      const response = await api.get('/media/filter-options')
      filterOptions.value = response.data
    } catch (e: any) {
      error.value = e.message || 'Failed to fetch media filter options'
      console.error(e)
    }
  }

  async function fetchSelectionCount(payload: Record<string, any>) {
    isSelectionCountLoading.value = true
    selectionCountError.value = null
    try {
      const response = await api.post('/media/selection-count', payload)
      selectionCount.value = response.data
    } catch (e: any) {
      selectionCountError.value = e.message || 'Failed to fetch media selection count'
      console.error(e)
    } finally {
      isSelectionCountLoading.value = false
    }
  }

  async function browseFilesystem(params: {
    path?: string
    kind?: 'any' | 'file' | 'directory'
    extensions?: string[]
  }): Promise<FilesystemBrowseResponse> {
    const response = await api.get('/filesystem/browse', {
      params: {
        path: params.path || '~',
        kind: params.kind || 'any',
        extensions: (params.extensions || []).join(',')
      }
    })
    return response.data
  }

  async function validateFilesystemPath(payload: {
    path: string
    kind?: 'any' | 'file' | 'directory'
    field?: string
    allow_missing?: boolean
    extensions?: string[]
  }): Promise<FilesystemValidateResponse> {
    const response = await api.post('/filesystem/validate', payload)
    return response.data
  }

  return {
    config,
    filterOptions,
    selectionCount,
    isLoading,
    isSelectionCountLoading,
    error,
    selectionCountError,
    fetchConfig,
    fetchFilterOptions,
    fetchSelectionCount,
    browseFilesystem,
    validateFilesystemPath,
    saveConfig,
    savePartialConfig
  }
})

export const useSystemStore = defineStore('system', () => {
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  async function purgeDatabase() {
    isLoading.value = true
    error.value = null
    try {
      await api.post('/maintenance/purge-db')
    } catch (e: any) {
      error.value = e.message || 'Failed to purge database'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function clearCache() {
    isLoading.value = true
    error.value = null
    try {
      await api.post('/maintenance/clear-cache')
    } catch (e: any) {
      error.value = e.message || 'Failed to clear cache'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function reboot() {
    isLoading.value = true
    error.value = null
    try {
      await api.post('/system/reboot')
    } catch (e: any) {
      error.value = e.message || 'Failed to reboot system'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function shutdown() {
    isLoading.value = true
    error.value = null
    try {
      await api.post('/system/shutdown')
    } catch (e: any) {
      error.value = e.message || 'Failed to shutdown system'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  return {
    isLoading,
    error,
    purgeDatabase,
    clearCache,
    reboot,
    shutdown
  }
})
