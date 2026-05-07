<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { useI18n } from 'vue-i18n'
import {
  mdiCalendarClock,
  mdiCameraTimer,
  mdiCameraIris,
  mdiFilm,
  mdiSignalDistanceVariant,
  mdiCamera,
  mdiImageSizeSelectActual,
  mdiScreenRotation,
  mdiFileImage,
  mdiClockOutline,
  mdiVideo,
  mdiPalette,
  mdiAnimationPlay,
  mdiSpeedometer
} from '@mdi/js'
import {
  ForwardIcon,
  BackwardIcon,
  SunIcon,
  PhotoIcon,
  InformationCircleIcon,
  DocumentTextIcon
} from '@heroicons/vue/24/outline'
import {
  PlayIcon as PlayIconSolid,
  PauseIcon as PauseIconSolid,
  PowerIcon,
  TrashIcon as TrashIconSolid
} from '@heroicons/vue/24/solid'
import MapComponent from '../components/MapComponent.vue'

const { t } = useI18n()
const playerStore = usePlayerStore()
const { currentMedia, isPlaying, brightness, isDisplayOn, isConnected } = storeToRefs(playerStore)

// Initialize WebSocket connection if not already connected
onMounted(() => {
  if (!isConnected.value) {
    playerStore.connect()
  }
})

const togglePlayPause = () => {
  if (isPlaying.value) {
    playerStore.pause()
  } else {
    playerStore.play()
  }
}

const handleBrightnessChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  playerStore.setBrightness(parseFloat(target.value))
}

// Computed properties for safe access
const displayFileName = computed(() => {
  if (!currentMedia.value?.file_path) return t('remote.unknownFile')
  try {
    const url = new URL(currentMedia.value.file_path, window.location.origin)
    const pathParam = url.searchParams.get('path')
    const pathToUse = pathParam || url.pathname
    const decoded = decodeURIComponent(pathToUse)
    return decoded.split('/').pop() || t('remote.unknownFile')
  } catch (e) {
    return currentMedia.value.file_path.split('/').pop() || t('remote.unknownFile')
  }
})

const metadataFields = computed(() => {
  const data = currentMedia.value?.exif || {}
  const fields = []

  // Title
  if (data.title) {
    fields.push({
      key: 'title',
      label: t('remote.metadata.title'),
      icon: mdiFileImage, // Or another appropriate icon
      value: data.title
    })
  }

  // File Name
  fields.push({
    key: 'fileName',
    label: t('remote.metadata.fileName'),
    icon: mdiFileImage,
    value: displayFileName.value
  })

  // Date
  if (data.exif_datetime) {
    fields.push({
      key: 'date',
      label: t('remote.metadata.date'),
      icon: mdiCalendarClock,
      value: new Date(data.exif_datetime * 1000).toLocaleString()
    })
  }

  // Exposure Time
  if (data.exposure_time) {
    fields.push({
      key: 'exposureTime',
      label: t('remote.metadata.exposureTime'),
      icon: mdiCameraTimer,
      value: `${data.exposure_time} sec`
    })
  }

  // Aperture
  if (data.f_number) {
    fields.push({
      key: 'aperture',
      label: t('remote.metadata.aperture'),
      icon: mdiCameraIris,
      value: `f/${data.f_number}`
    })
  }

  // ISO
  if (data.iso) {
    fields.push({
      key: 'iso',
      label: t('remote.metadata.iso'),
      icon: mdiFilm,
      value: data.iso
    })
  }

  // Focal Length
  if (data.focal_length) {
    fields.push({
      key: 'focalLength',
      label: t('remote.metadata.focalLength'),
      icon: mdiSignalDistanceVariant,
      value: `${data.focal_length} mm`
    })
  }

  // Camera Model
  if (data.make || data.model) {
    const camera = [data.make, data.model].filter(Boolean).join(' ')
    fields.push({
      key: 'camera',
      label: t('remote.metadata.camera'),
      icon: mdiCamera,
      value: camera
    })
  }

  // Resolution
  if (data.width && data.height) {
    fields.push({
      key: 'resolution',
      label: t('remote.metadata.resolution'),
      icon: mdiImageSizeSelectActual,
      value: `${data.width} × ${data.height}`
    })
  }

  // Orientation
  if (data.orientation) {
    fields.push({
      key: 'orientation',
      label: t('remote.metadata.orientation'),
      icon: mdiScreenRotation,
      value: data.orientation
    })
  }

  // Duration
  if (data.duration) {
    fields.push({
      key: 'duration',
      label: t('remote.metadata.duration') || 'Duration',
      icon: mdiClockOutline,
      value: `${Number(data.duration).toFixed(2)} sec`
    })
  }

  // Codec
  if (data.codec) {
    fields.push({
      key: 'codec',
      label: t('remote.metadata.codec') || 'Codec',
      icon: mdiVideo,
      value: data.codec
    })
  }

  // Pixel Format
  if (data.pixel_format) {
    fields.push({
      key: 'pixelFormat',
      label: t('remote.metadata.pixelFormat') || 'Pixel Format',
      icon: mdiPalette,
      value: data.pixel_format
    })
  }

  // Framerate
  if (data.framerate) {
    fields.push({
      key: 'framerate',
      label: t('remote.metadata.framerate') || 'Framerate',
      icon: mdiAnimationPlay,
      value: `${data.framerate} fps`
    })
  }

  // Bitrate
  if (data.bitrate) {
    fields.push({
      key: 'bitrate',
      label: t('remote.metadata.bitrate') || 'Bitrate',
      icon: mdiSpeedometer,
      value: `${(Number(data.bitrate) / 1000).toFixed(0)} kbps`
    })
  }

  return fields
})

</script>

<template>
  <div class="max-w-7xl mx-auto space-y-6 p-4 sm:p-6 lg:p-8">
    
    <!-- Connection Status Banner -->
    <div v-if="!isConnected" class="bg-amber-500/10 border-l-4 border-amber-500 text-amber-700 dark:text-amber-400 p-4 rounded-r-lg shadow-sm flex items-center" role="alert">
      <div class="animate-pulse mr-3 h-3 w-3 bg-amber-500 rounded-full"></div>
      <div>
        <p class="font-bold text-sm">Connecting to Picframe...</p>
        <p class="text-xs opacity-80">Establishing real-time WebSocket connection.</p>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
      
      <!-- Left Column: Media & Controls -->
      <div class="xl:col-span-7 flex flex-col space-y-6">
        
        <!-- Media Player Card -->
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-2xl overflow-hidden border border-gray-200/50 dark:border-gray-700/50 flex-grow flex flex-col">
          
          <!-- Image Preview Area -->
          <div class="relative w-full bg-black/5 dark:bg-black/40 flex items-center justify-center overflow-hidden group aspect-video">
            <img
              v-if="currentMedia?.file_path"
              :src="currentMedia.file_path"
              alt="Current Media"
              class="absolute inset-0 w-full h-full object-contain transition-transform duration-1000 ease-out group-hover:scale-[1.02]"
              @error="console.error('Failed to load image:', currentMedia.file_path)"
            />
            <div v-else class="flex flex-col items-center text-gray-400 dark:text-gray-500">
              <PhotoIcon class="w-24 h-24 mb-4 opacity-20" />
              <p class="text-lg font-medium tracking-wide uppercase text-sm opacity-60">No Media Playing</p>
            </div>
            
            <!-- Adaptive Cinematic Gradient Overlay -->
            <div class="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent opacity-40 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
            
            <!-- Narrative Metadata Overlay (Progressive Disclosure) -->
            <div class="absolute bottom-0 left-0 right-0 p-6 transition-all duration-500 flex justify-between items-end group-hover:backdrop-blur-sm">
              <div class="flex-1 min-w-0 pr-4 pointer-events-none">
                <!-- Title (Always visible) -->
                <h2 class="text-2xl font-bold text-white truncate drop-shadow-md transition-transform duration-500 group-hover:-translate-y-1">
                  {{ currentMedia?.exif?.title || displayFileName }}
                </h2>
                
                <!-- Progressive Disclosure: Caption & Tags (Visible on hover) -->
                <div class="grid grid-rows-[0fr] group-hover:grid-rows-[1fr] transition-all duration-500 ease-in-out opacity-0 group-hover:opacity-100">
                  <div class="overflow-hidden">
                    <p v-if="currentMedia?.exif?.caption" class="text-sm text-gray-200 mt-2 line-clamp-3 drop-shadow">
                      {{ currentMedia.exif.caption }}
                    </p>
                    
                    <div v-if="currentMedia?.exif?.tags" class="flex overflow-x-auto hide-scrollbar space-x-2 mt-3 pb-1 pointer-events-auto">
                      <span v-for="tag in currentMedia.exif.tags.split(',')" :key="tag" class="whitespace-nowrap px-2.5 py-1 bg-white/20 hover:bg-white/30 backdrop-blur-md rounded-full text-xs text-white transition-colors cursor-default">
                        {{ tag.trim() }}
                      </span>
                    </div>
                  </div>
                </div>
              </div>
              
              <button @click="playerStore.sendCommand('DELETE')" class="pointer-events-auto p-3 rounded-full bg-red-600/80 hover:bg-red-500 text-white shadow-lg backdrop-blur-sm transition-all transform hover:scale-110 focus:outline-none focus:ring-2 focus:ring-red-500/50 active:scale-95 flex-shrink-0 opacity-0 group-hover:opacity-100" title="Delete Current Image">
                <TrashIconSolid class="w-6 h-6" />
              </button>
            </div>
          </div>

          <!-- Controls Area -->
          <div class="p-6 sm:p-8 bg-white dark:bg-gray-800/90 border-t border-gray-100 dark:border-gray-700/50">
            
            <!-- Transport Controls -->
            <div class="flex items-center justify-center space-x-6 sm:space-x-10 mb-8 relative">
              <button @click="playerStore.toggleDisplayPower()" :class="['absolute left-0 p-3 rounded-full transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95', isDisplayOn ? 'text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-500/10' : 'text-red-500 hover:bg-red-50 dark:hover:bg-red-500/10']" :title="isDisplayOn ? 'Turn Display Off' : 'Turn Display On'">
                <PowerIcon class="w-6 h-6" />
              </button>
              <button @click="playerStore.previous()" class="p-4 rounded-full hover:bg-gray-100 dark:hover:bg-gray-700/50 text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95">
                <BackwardIcon class="w-8 h-8" />
              </button>
              
              <button @click="togglePlayPause" class="p-6 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/30 hover:shadow-indigo-600/50 transition-all transform hover:-translate-y-1 focus:outline-none focus:ring-4 focus:ring-indigo-500/50 active:scale-95">
                <PauseIconSolid v-if="isPlaying" class="w-10 h-10" />
                <PlayIconSolid v-else class="w-10 h-10 ml-1" />
              </button>
              
              <button @click="playerStore.next()" class="p-4 rounded-full hover:bg-gray-100 dark:hover:bg-gray-700/50 text-gray-500 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95">
                <ForwardIcon class="w-8 h-8" />
              </button>
            </div>

            <!-- Brightness Control -->
            <div class="flex items-center space-x-4 px-6 py-4 bg-gray-50 dark:bg-gray-900/50 rounded-2xl border border-gray-100 dark:border-gray-800">
              <SunIcon class="w-6 h-6 text-gray-400 dark:text-gray-500" />
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                :value="brightness"
                @input="handleBrightnessChange"
                class="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer dark:bg-gray-700 accent-indigo-600 hover:accent-indigo-500 transition-all"
              >
              <span class="text-sm font-bold text-gray-600 dark:text-gray-300 w-12 text-right tabular-nums">{{ Math.round(brightness * 100) }}%</span>
            </div>
          </div>
        </div>

        <!-- Map Card -->
        <MapComponent
          :latitude="currentMedia?.location?.lat"
          :longitude="currentMedia?.location?.lon"
          :location-name="currentMedia?.exif?.location_name"
        />
      </div>

      <!-- Right Column: Metadata & Controls -->
      <div class="xl:col-span-5 flex flex-col space-y-6">

        <!-- Metadata Card -->
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-xl border border-gray-200/50 dark:border-gray-700/50 overflow-hidden flex-grow">
          <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <div class="p-2 bg-indigo-50 dark:bg-indigo-500/10 rounded-lg">
                <InformationCircleIcon class="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <h3 class="text-lg font-bold text-gray-900 dark:text-white tracking-tight">Media Details</h3>
            </div>
          </div>
          
          <div class="p-6 max-h-[400px] overflow-y-auto custom-scrollbar">
            <div v-if="metadataFields.length > 0" class="space-y-4">
              <div v-for="field in metadataFields" :key="field.key" class="flex items-center justify-between p-3 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors group">
                <div class="flex items-center space-x-3 overflow-hidden">
                  <svg class="w-5 h-5 text-gray-400 dark:text-gray-500 group-hover:text-indigo-500 transition-colors flex-shrink-0" viewBox="0 0 24 24">
                    <path :d="field.icon" fill="currentColor" />
                  </svg>
                  <span class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">{{ field.label }}</span>
                </div>
                <span class="text-sm font-semibold text-gray-900 dark:text-gray-200 text-right pl-4 truncate max-w-[60%]" :title="String(field.value)">{{ field.value }}</span>
              </div>
            </div>
            <div v-else class="flex flex-col items-center justify-center py-12 text-gray-400 dark:text-gray-500">
              <DocumentTextIcon class="w-12 h-12 mb-3 opacity-20" />
              <p class="text-sm font-medium">{{ $t('remote.noMetadata') }}</p>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* Custom scrollbar for metadata panel */
.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: rgba(156, 163, 175, 0.5);
  border-radius: 20px;
}
.dark .custom-scrollbar::-webkit-scrollbar-thumb {
  background-color: rgba(75, 85, 99, 0.5);
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background-color: rgba(107, 114, 128, 0.8);
}

/* Hide scrollbar for tags container */
.hide-scrollbar::-webkit-scrollbar {
  display: none;
}
.hide-scrollbar {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

/* Custom range slider styling for WebKit */
input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #4f46e5;
  cursor: pointer;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  transition: all 0.2s ease;
  border: 2px solid white;
}

.dark input[type=range]::-webkit-slider-thumb {
  border-color: #1f2937;
}

input[type=range]::-webkit-slider-thumb:hover {
  transform: scale(1.15);
  background: #4338ca;
}

/* Custom range slider styling for Firefox */
input[type=range]::-moz-range-thumb {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #4f46e5;
  cursor: pointer;
  border: 2px solid white;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
  transition: all 0.2s ease;
}

.dark input[type=range]::-moz-range-thumb {
  border-color: #1f2937;
}

input[type=range]::-moz-range-thumb:hover {
  transform: scale(1.15);
  background: #4338ca;
}

</style>
