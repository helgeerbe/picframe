import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export const useConfigStore = defineStore('config', () => {
  const config = ref<Record<string, any>>({})
  const isLoading = ref(false)
  const error = ref<string | null>(null)

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

  return {
    config,
    isLoading,
    error,
    fetchConfig,
    saveConfig
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
