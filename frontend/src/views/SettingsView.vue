<script setup lang="ts">
import { onMounted, ref, onErrorCaptured } from 'vue'
import { storeToRefs } from 'pinia'
import { useConfigStore, useSystemStore } from '../stores/config'
import { useI18n } from 'vue-i18n'
import configSchema from '../configSchema.json'
import { 
  Cog6ToothIcon, 
  ArrowDownTrayIcon, 
  ArrowUpTrayIcon, 
  ExclamationTriangleIcon,
  TrashIcon,
  ArrowPathIcon,
  PowerIcon,
  CheckCircleIcon
} from '@heroicons/vue/24/outline'

const { t } = useI18n()
const configStore = useConfigStore()
const systemStore = useSystemStore()

const { config, isLoading: isConfigLoading, error: configError } = storeToRefs(configStore)
const { error: systemError } = storeToRefs(systemStore)

const localConfig = ref<Record<string, any>>({})
const activeTab = ref(Object.keys(configSchema || {})[0] || 'viewer')
const showConfirmModal = ref(false)
const renderError = ref<any>(null)

onErrorCaptured((err, _instance, info) => {
  console.error('SettingsView Error:', err, info)
  renderError.value = { message: err instanceof Error ? err.message : String(err), info }
  return false // Prevent error from propagating and unmounting the app
})
const confirmAction = ref<(() => Promise<void>) | null>(null)
const confirmMessage = ref('')
const successMessage = ref('')

import { watch } from 'vue'

onMounted(async () => {
  await configStore.fetchConfig()
})

watch(() => config.value, (newConfig) => {
  if (!newConfig || Object.keys(newConfig).length === 0) return;
  
  console.log('configSchema:', configSchema)
  console.log('config.value:', newConfig)
  
  const getFallbackValue = (type: string) => {
    switch (type) {
      case 'boolean': return false;
      case 'integer': return 0;
      case 'float': return 0.0;
      case 'string': return '';
      case 'array': return [];
      default: return null;
    }
  }

  // Initialize localConfig with all keys from schema to prevent undefined errors
  const initializedConfig: Record<string, any> = {}
  for (const [section, props] of Object.entries(configSchema)) {
    initializedConfig[section] = {}
    for (const [key, propDef] of Object.entries(props as Record<string, any>)) {
      if (key === '_title') continue; // Skip _title keys from schema
      if (propDef.type === 'object' && propDef.properties) {
        initializedConfig[section][key] = {}
        for (const subKey of Object.keys(propDef.properties)) {
          if (subKey === '_title') continue; // Skip _title keys from schema
          const val = newConfig?.[section]?.[key]?.[subKey];
          initializedConfig[section][key][subKey] = val !== undefined && val !== null
            ? val
            : getFallbackValue((propDef.properties as any)[subKey]?.type || 'string');
        }
      } else {
        const val = newConfig?.[section]?.[key];
        initializedConfig[section][key] = val !== undefined && val !== null
          ? val
          : getFallbackValue(propDef.type);
      }
    }
  }
  
  localConfig.value = initializedConfig
}, { immediate: true, deep: true })

const saveConfig = async () => {
  try {
    await configStore.saveConfig(localConfig.value)
    showSuccess(t('settings.saving'))
  } catch (e) {
    // Error handled in store
  }
}

const showSuccess = (msg: string) => {
  successMessage.value = msg
  setTimeout(() => {
    successMessage.value = ''
  }, 3000)
}

const triggerConfirm = (action: () => Promise<void>, message: string) => {
  confirmAction.value = action
  confirmMessage.value = message
  showConfirmModal.value = true
}

const executeConfirm = async () => {
  if (confirmAction.value) {
    try {
      await confirmAction.value()
      showConfirmModal.value = false
      showSuccess('Action completed successfully')
    } catch (e) {
      showConfirmModal.value = false
    }
  }
}

const exportConfig = () => {
  const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(localConfig.value, null, 2))
  const downloadAnchorNode = document.createElement('a')
  downloadAnchorNode.setAttribute("href",     dataStr)
  downloadAnchorNode.setAttribute("download", "picframe_config.json")
  document.body.appendChild(downloadAnchorNode)
  downloadAnchorNode.click()
  downloadAnchorNode.remove()
}

const importConfig = (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      const imported = JSON.parse(e.target?.result as string)
      localConfig.value = imported
      showSuccess('Configuration imported. Please save to apply.')
    } catch (err) {
      console.error('Failed to parse imported config', err)
      alert('Invalid configuration file.')
    }
  }
  reader.readAsText(file)
}

const formatLabel = (key: string | undefined | null) => {
  if (!key) return ''
  return String(key).split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')
}
</script>

<template>
  <div class="max-w-7xl mx-auto space-y-6 p-4 sm:p-6 lg:p-8">
    
    <!-- Error Boundary Display -->
    <div v-if="renderError" class="bg-red-100 border-l-4 border-red-500 text-red-700 p-4 rounded shadow-sm mb-6">
      <h3 class="font-bold text-lg">Component Crash Detected</h3>
      <p class="font-mono text-sm mt-2">{{ renderError.message }}</p>
      <p class="text-xs mt-1 text-red-500">Context: {{ renderError.info }}</p>
      <button @click="renderError = null" class="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 text-sm">Dismiss</button>
    </div>

    <div v-if="!renderError" class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
      <div class="flex items-center space-x-3">
        <div class="p-3 bg-indigo-50 dark:bg-indigo-500/10 rounded-xl">
          <Cog6ToothIcon class="w-8 h-8 text-indigo-600 dark:text-indigo-400" />
        </div>
        <h1 class="text-3xl font-bold text-gray-900 dark:text-white tracking-tight">{{ t('settings.title') }}</h1>
      </div>
      
      <div class="flex items-center space-x-3">
        <button @click="exportConfig" class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 shadow-sm text-sm font-medium rounded-lg text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-colors">
          <ArrowDownTrayIcon class="w-4 h-4 mr-2" />
          {{ t('settings.export') }}
        </button>
        
        <label class="inline-flex items-center px-4 py-2 border border-gray-300 dark:border-gray-600 shadow-sm text-sm font-medium rounded-lg text-gray-700 dark:text-gray-200 bg-white dark:bg-gray-800 hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 cursor-pointer transition-colors">
          <ArrowUpTrayIcon class="w-4 h-4 mr-2" />
          {{ t('settings.import') }}
          <input type="file" accept=".json" class="hidden" @change="importConfig">
        </label>
        
        <button @click="saveConfig" :disabled="isConfigLoading" class="inline-flex items-center px-5 py-2 border border-transparent shadow-sm text-sm font-medium rounded-lg text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 transition-colors">
          <ArrowPathIcon v-if="isConfigLoading" class="w-4 h-4 mr-2 animate-spin" />
          <CheckCircleIcon v-else class="w-4 h-4 mr-2" />
          {{ isConfigLoading ? t('settings.saving') : t('settings.save') }}
        </button>
      </div>
    </div>

    <!-- Alerts -->
    <div v-if="!renderError && (configError || systemError)" class="bg-red-50 dark:bg-red-900/20 border-l-4 border-red-500 p-4 rounded-r-lg mb-6">
      <div class="flex">
        <div class="flex-shrink-0">
          <ExclamationTriangleIcon class="h-5 w-5 text-red-400" aria-hidden="true" />
        </div>
        <div class="ml-3">
          <p class="text-sm text-red-700 dark:text-red-400">
            {{ configError || systemError }}
          </p>
        </div>
      </div>
    </div>

    <div v-if="!renderError && successMessage" class="bg-green-50 dark:bg-green-900/20 border-l-4 border-green-500 p-4 rounded-r-lg mb-6 transition-all duration-500">
      <div class="flex">
        <div class="flex-shrink-0">
          <CheckCircleIcon class="h-5 w-5 text-green-400" aria-hidden="true" />
        </div>
        <div class="ml-3">
          <p class="text-sm text-green-700 dark:text-green-400 font-medium">
            {{ successMessage }}
          </p>
        </div>
      </div>
    </div>

    <div v-if="!renderError" class="grid grid-cols-1 lg:grid-cols-4 gap-8">
      
      <!-- Sidebar Navigation -->
      <div class="lg:col-span-1">
        <nav class="space-y-1 bg-white dark:bg-gray-800/90 backdrop-blur-xl p-2 rounded-2xl shadow-sm border border-gray-200/50 dark:border-gray-700/50 sticky top-6">
          <button 
            v-for="section in Object.keys(configSchema)" 
            :key="section"
            @click="activeTab = section"
            :class="[
              activeTab === section 
                ? 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 font-semibold' 
                : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700/50 hover:text-gray-900 dark:hover:text-white',
              'group flex items-center px-4 py-3 text-sm font-medium rounded-xl w-full text-left transition-colors'
            ]"
          >
            <span class="truncate">{{ t(`config.${section}._title`, formatLabel(section)) }}</span>
          </button>
          
          <div class="my-2 border-t border-gray-200 dark:border-gray-700"></div>
          
          <button 
            @click="activeTab = 'danger'"
            :class="[
              activeTab === 'danger' 
                ? 'bg-red-50 dark:bg-red-500/10 text-red-700 dark:text-red-400 font-semibold' 
                : 'text-red-600 dark:text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10',
              'group flex items-center px-4 py-3 text-sm font-medium rounded-xl w-full text-left transition-colors'
            ]"
          >
            <ExclamationTriangleIcon class="w-5 h-5 mr-3 flex-shrink-0" />
            <span class="truncate">{{ t('settings.dangerZone') }}</span>
          </button>
        </nav>
      </div>

      <!-- Main Content Area -->
      <div class="lg:col-span-3">
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl shadow-xl rounded-3xl border border-gray-200/50 dark:border-gray-700/50 overflow-hidden min-h-[600px]">
          
          <!-- Dynamic Config Form -->
          <div v-if="activeTab !== 'danger' && localConfig && localConfig[activeTab]" class="p-6 sm:p-8">
            <h2 class="text-2xl font-bold text-gray-900 dark:text-white mb-8 pb-4 border-b border-gray-100 dark:border-gray-700/50">
              {{ t(`config.${activeTab}._title`, formatLabel(activeTab)) }}
            </h2>
            
            <div class="space-y-8">
              <template v-for="(propDef, key) in (configSchema as Record<string, any>)[activeTab]" :key="key">
                
                <!-- Handle nested objects (like peripherals.buttons) -->
                <div v-if="propDef.type === 'object'" class="bg-gray-50/50 dark:bg-gray-900/30 p-6 rounded-2xl border border-gray-100 dark:border-gray-700/50">
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-6">{{ formatLabel(String(key)) }}</h3>
                  <div class="space-y-6">
                    <div v-for="(subPropDef, subKey) in propDef.properties as Record<string, any>" :key="subKey" class="grid grid-cols-1 md:grid-cols-3 gap-4 items-start">
                      <div class="md:col-span-1">
                        <label :for="`${activeTab}-${key}-${subKey}`" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                          {{ formatLabel(String(subKey)) }}
                        </label>
                        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                          {{ t(`config.${activeTab}.${key}.${subKey}`, '') }}
                        </p>
                      </div>
                      <div class="md:col-span-2">
                        <!-- Boolean Toggle -->
                        <div v-if="subPropDef.type === 'boolean'" class="flex items-center h-full pt-1">
                          <button 
                            type="button" 
                            @click="localConfig[activeTab][key][subKey] = !localConfig[activeTab][key][subKey]"
                            :class="[localConfig[activeTab][key][subKey] ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700', 'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2']"
                          >
                            <span :class="[localConfig[activeTab][key][subKey] ? 'translate-x-5' : 'translate-x-0', 'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out']"></span>
                          </button>
                        </div>
                        <!-- String Input -->
                        <input 
                          v-else-if="subPropDef.type === 'string'" 
                          type="text" 
                          :id="`${activeTab}-${key}-${subKey}`" 
                          v-model="localConfig[activeTab][key][subKey]"
                          class="block w-full rounded-lg border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm px-4 py-2.5"
                        >
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Standard Properties -->
                <div v-else class="grid grid-cols-1 md:grid-cols-3 gap-4 items-start border-b border-gray-100 dark:border-gray-700/50 pb-6 last:border-0 last:pb-0">
                  <div class="md:col-span-1">
                    <label :for="`${activeTab}-${key}`" class="block text-sm font-medium text-gray-700 dark:text-gray-300">
                      {{ formatLabel(String(key)) }}
                    </label>
                    <p class="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
                      {{ t(`config.${activeTab}.${key}`, '') }}
                    </p>
                  </div>
                  
                  <div class="md:col-span-2">
                    <!-- Boolean Toggle -->
                    <div v-if="propDef.type === 'boolean'" class="flex items-center h-full pt-1">
                      <button 
                        type="button" 
                        @click="localConfig[activeTab][key] = !localConfig[activeTab][key]"
                        :class="[localConfig[activeTab][key] ? 'bg-indigo-600' : 'bg-gray-200 dark:bg-gray-700', 'relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2']"
                      >
                        <span :class="[localConfig[activeTab][key] ? 'translate-x-5' : 'translate-x-0', 'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out']"></span>
                      </button>
                    </div>
                    
                    <!-- Select Dropdown -->
                    <select
                      v-else-if="propDef.type === 'select'"
                      :id="`${activeTab}-${key}`"
                      v-model="localConfig[activeTab][key]"
                      class="block w-full rounded-lg border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm px-4 py-2.5"
                    >
                      <option v-for="opt in (propDef as any).options" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    
                    <!-- Number Input -->
                    <input 
                      v-else-if="propDef.type === 'integer' || propDef.type === 'float'" 
                      type="number" 
                      :step="propDef.type === 'float' ? '0.01' : '1'"
                      :id="`${activeTab}-${key}`" 
                      v-model.number="localConfig[activeTab][key]"
                      class="block w-full rounded-lg border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm px-4 py-2.5"
                    >
                    
                    <!-- Array Input (Simple comma separated for now) -->
                    <input 
                      v-else-if="propDef.type === 'array'" 
                      type="text" 
                      :id="`${activeTab}-${key}`" 
                      :value="Array.isArray(localConfig[activeTab][key]) ? localConfig[activeTab][key].join(', ') : localConfig[activeTab][key]"
                      @change="e => localConfig[activeTab][key] = (e.target as HTMLInputElement).value.split(',').map(s => s.trim())"
                      class="block w-full rounded-lg border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm px-4 py-2.5"
                      placeholder="Comma separated values"
                    >
                    
                    <!-- Default String Input -->
                    <input 
                      v-else 
                      type="text" 
                      :id="`${activeTab}-${key}`" 
                      v-model="localConfig[activeTab][key]"
                      class="block w-full rounded-lg border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm focus:border-indigo-500 focus:ring-indigo-500 sm:text-sm px-4 py-2.5"
                    >
                  </div>
                </div>
              </template>
            </div>
          </div>

          <!-- Danger Zone -->
          <div v-if="activeTab === 'danger'" class="p-6 sm:p-8">
            <div class="flex items-center space-x-3 mb-8 pb-4 border-b border-red-100 dark:border-red-900/30">
              <ExclamationTriangleIcon class="w-8 h-8 text-red-600 dark:text-red-500" />
              <h2 class="text-2xl font-bold text-red-600 dark:text-red-500">
                {{ t('settings.dangerZone') }}
              </h2>
            </div>
            
            <div class="space-y-6">
              <div class="bg-red-50 dark:bg-red-500/5 border border-red-100 dark:border-red-500/20 rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.purgeDb') }}</h3>
                  <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">Removes database entries for files that no longer exist on disk.</p>
                </div>
                <button @click="triggerConfirm(systemStore.purgeDatabase, t('settings.purgeDb'))" class="inline-flex items-center justify-center px-4 py-2 border border-transparent font-medium rounded-lg text-red-700 bg-red-100 hover:bg-red-200 dark:text-white dark:bg-red-600 dark:hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors sm:w-auto w-full">
                  <TrashIcon class="w-5 h-5 mr-2" />
                  Purge
                </button>
              </div>

              <div class="bg-red-50 dark:bg-red-500/5 border border-red-100 dark:border-red-500/20 rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.clearCache') }}</h3>
                  <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">Deletes all pre-processed matting images and resized thumbnails from the disk cache.</p>
                </div>
                <button @click="triggerConfirm(systemStore.clearCache, t('settings.clearCache'))" class="inline-flex items-center justify-center px-4 py-2 border border-transparent font-medium rounded-lg text-red-700 bg-red-100 hover:bg-red-200 dark:text-white dark:bg-red-600 dark:hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors sm:w-auto w-full">
                  <TrashIcon class="w-5 h-5 mr-2" />
                  Clear
                </button>
              </div>

              <div class="bg-red-50 dark:bg-red-500/5 border border-red-100 dark:border-red-500/20 rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.reboot') }}</h3>
                  <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">Safely reboots the host operating system.</p>
                </div>
                <button @click="triggerConfirm(systemStore.reboot, t('settings.reboot'))" class="inline-flex items-center justify-center px-4 py-2 border border-transparent font-medium rounded-lg text-red-700 bg-red-100 hover:bg-red-200 dark:text-white dark:bg-red-600 dark:hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors sm:w-auto w-full">
                  <ArrowPathIcon class="w-5 h-5 mr-2" />
                  Reboot
                </button>
              </div>

              <div class="bg-red-50 dark:bg-red-500/5 border border-red-100 dark:border-red-500/20 rounded-2xl p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <h3 class="text-lg font-semibold text-gray-900 dark:text-white">{{ t('settings.shutdown') }}</h3>
                  <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">Safely shuts down the host operating system.</p>
                </div>
                <button @click="triggerConfirm(systemStore.shutdown, t('settings.shutdown'))" class="inline-flex items-center justify-center px-4 py-2 border border-transparent font-medium rounded-lg text-red-700 bg-red-100 hover:bg-red-200 dark:text-white dark:bg-red-600 dark:hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors sm:w-auto w-full">
                  <PowerIcon class="w-5 h-5 mr-2" />
                  Shutdown
                </button>
              </div>
            </div>
          </div>

        </div>
      </div>
    </div>

    <!-- Confirmation Modal -->
    <div v-if="showConfirmModal" class="relative z-10" aria-labelledby="modal-title" role="dialog" aria-modal="true">
      <div class="fixed inset-0 bg-gray-500/75 dark:bg-gray-900/80 backdrop-blur-sm transition-opacity"></div>

      <div class="fixed inset-0 z-10 overflow-y-auto">
        <div class="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
          <div class="relative transform overflow-hidden rounded-2xl bg-white dark:bg-gray-800 text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-lg border border-gray-200 dark:border-gray-700">
            <div class="bg-white dark:bg-gray-800 px-4 pb-4 pt-5 sm:p-6 sm:pb-4">
              <div class="sm:flex sm:items-start">
                <div class="mx-auto flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-100 dark:bg-red-900/30 sm:mx-0 sm:h-10 sm:w-10">
                  <ExclamationTriangleIcon class="h-6 w-6 text-red-600 dark:text-red-500" aria-hidden="true" />
                </div>
                <div class="mt-3 text-center sm:ml-4 sm:mt-0 sm:text-left">
                  <h3 class="text-lg font-semibold leading-6 text-gray-900 dark:text-white" id="modal-title">Confirm Action</h3>
                  <div class="mt-2">
                    <p class="text-sm text-gray-500 dark:text-gray-400">
                      {{ t('settings.confirmAction') }}<br>
                      <span class="font-medium text-gray-900 dark:text-gray-300 mt-2 block">{{ confirmMessage }}</span>
                    </p>
                  </div>
                </div>
              </div>
            </div>
            <div class="bg-gray-50 dark:bg-gray-800/50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6 border-t border-gray-100 dark:border-gray-700">
              <button type="button" @click="executeConfirm" class="inline-flex w-full justify-center rounded-lg bg-red-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-red-500 sm:ml-3 sm:w-auto transition-colors">
                {{ t('settings.confirm') }}
              </button>
              <button type="button" @click="showConfirmModal = false" class="mt-3 inline-flex w-full justify-center rounded-lg bg-white dark:bg-gray-700 px-3 py-2 text-sm font-semibold text-gray-900 dark:text-gray-200 shadow-sm ring-1 ring-inset ring-gray-300 dark:ring-gray-600 hover:bg-gray-50 dark:hover:bg-gray-600 sm:mt-0 sm:w-auto transition-colors">
                {{ t('settings.cancel') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>
