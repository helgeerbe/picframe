<script setup lang="ts">
import { onMounted, computed, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import { 
   
   
  ForwardIcon, 
  BackwardIcon,
  SunIcon,
  PhotoIcon,
  MapPinIcon,
  InformationCircleIcon,
  CameraIcon,
  CalendarIcon,
  DocumentTextIcon,
  TagIcon
} from '@heroicons/vue/24/outline'
import {
  PlayIcon as PlayIconSolid,
  PauseIcon as PauseIconSolid,
  PowerIcon
} from '@heroicons/vue/24/solid'
import 'leaflet/dist/leaflet.css'
import { LMap, LTileLayer, LMarker } from '@vue-leaflet/vue-leaflet'
import L from 'leaflet'

// Fix Leaflet icon issue with Vite
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'

L.Icon.Default.mergeOptions({
  iconRetinaUrl,
  iconUrl,
  shadowUrl,
})

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
const hasLocation = computed(() => {
  return currentMedia.value?.location?.lat != null && currentMedia.value?.location?.lon != null
})

const mapCenter = computed(() => {
  if (hasLocation.value) {
    return [currentMedia.value!.location!.lat, currentMedia.value!.location!.lon] as [number, number]
  }
  return [0, 0] as [number, number]
})

const exifData = computed(() => currentMedia.value?.exif || {})

const formatExifKey = (key: string) => {
  return key.replace(/([A-Z])/g, ' $1').replace(/^./, str => str.toUpperCase())
}

const getExifIcon = (key: string) => {
  const lowerKey = key.toLowerCase()
  if (lowerKey.includes('make') || lowerKey.includes('model')) return CameraIcon
  if (lowerKey.includes('date') || lowerKey.includes('time')) return CalendarIcon
  if (lowerKey.includes('file')) return DocumentTextIcon
  if (lowerKey.includes('tag') || lowerKey.includes('caption')) return TagIcon
  return InformationCircleIcon
}

// Map zoom level
const zoom = ref(13)
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

    <div class="grid grid-cols-1 xl:grid-cols-12 gap-8">
      
      <!-- Left Column: Media & Controls -->
      <div class="xl:col-span-7 flex flex-col space-y-6">
        
        <!-- Media Player Card -->
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-2xl overflow-hidden border border-gray-200/50 dark:border-gray-700/50 flex-grow flex flex-col">
          
          <!-- Image Preview Area -->
          <div class="relative w-full bg-black/5 dark:bg-black/40 flex items-center justify-center overflow-hidden group" style="min-height: 400px; flex-grow: 1;">
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
            
            <!-- Elegant Gradient Overlay -->
            <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
            
            <!-- Hover Info -->
            <div class="absolute bottom-0 left-0 right-0 p-6 translate-y-4 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 transition-all duration-500 pointer-events-none">
              <h2 class="text-2xl font-bold text-white truncate drop-shadow-md">
                {{ currentMedia?.file_path?.split('/').pop() || 'Unknown File' }}
              </h2>
              <p v-if="exifData.caption" class="text-sm text-gray-200 mt-2 line-clamp-2 drop-shadow">
                {{ exifData.caption }}
              </p>
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
      </div>

      <!-- Right Column: Metadata & Map -->
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
          
          <div class="p-6">
            <div v-if="Object.keys(exifData).length > 0" class="space-y-4">
              <div v-for="(value, key) in exifData" :key="key" class="flex items-center justify-between p-3 rounded-xl hover:bg-gray-50 dark:hover:bg-gray-700/30 transition-colors group">
                <div class="flex items-center space-x-3 overflow-hidden">
                  <component :is="getExifIcon(key.toString())" class="w-5 h-5 text-gray-400 dark:text-gray-500 group-hover:text-indigo-500 transition-colors flex-shrink-0" />
                  <span class="text-sm font-medium text-gray-500 dark:text-gray-400 truncate">{{ formatExifKey(key.toString()) }}</span>
                </div>
                <span class="text-sm font-semibold text-gray-900 dark:text-gray-200 text-right pl-4 truncate max-w-[60%]" :title="String(value)">{{ value }}</span>
              </div>
            </div>
            <div v-else class="flex flex-col items-center justify-center py-12 text-gray-400 dark:text-gray-500">
              <DocumentTextIcon class="w-12 h-12 mb-3 opacity-20" />
              <p class="text-sm font-medium">No metadata available</p>
            </div>
          </div>
        </div>

        <!-- Map Card -->
        <div v-if="hasLocation" class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-xl border border-gray-200/50 dark:border-gray-700/50 overflow-hidden flex flex-col h-[350px]">
          <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between z-10 bg-white dark:bg-gray-800/90">
            <div class="flex items-center space-x-3 overflow-hidden">
              <div class="p-2 bg-emerald-50 dark:bg-emerald-500/10 rounded-lg flex-shrink-0">
                <MapPinIcon class="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
              </div>
              <h3 class="text-lg font-bold text-gray-900 dark:text-white tracking-tight truncate">
                {{ exifData.location_name || 'Location' }}
              </h3>
            </div>
          </div>
          
          <div class="flex-grow w-full relative z-0">
            <l-map ref="map" v-model:zoom="zoom" :center="mapCenter" :use-global-leaflet="false" class="z-0">
              <l-tile-layer
                url="https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png"
                layer-type="base"
                name="CartoDB Voyager"
                attribution="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors &copy; <a href='https://carto.com/attributions'>CARTO</a>"
              ></l-tile-layer>
              <l-marker :lat-lng="mapCenter"></l-marker>
            </l-map>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
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

/* Leaflet Map Tweaks for Dark Mode */
.dark .leaflet-layer,
.dark .leaflet-control-zoom-in,
.dark .leaflet-control-zoom-out,
.dark .leaflet-control-attribution {
  filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%);
}
</style>
