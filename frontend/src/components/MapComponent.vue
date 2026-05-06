<script setup lang="ts">
import { computed, ref } from 'vue'
import { MapPinIcon } from '@heroicons/vue/24/outline'
import 'leaflet/dist/leaflet.css'
import { LMap, LTileLayer, LMarker } from '@vue-leaflet/vue-leaflet'
import L from 'leaflet'
import { useI18n } from 'vue-i18n'

// Fix Leaflet icon issue with Vite
import iconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import iconUrl from 'leaflet/dist/images/marker-icon.png'
import shadowUrl from 'leaflet/dist/images/marker-shadow.png'

L.Icon.Default.mergeOptions({
  iconRetinaUrl,
  iconUrl,
  shadowUrl,
})

const props = defineProps<{
  latitude?: number | null
  longitude?: number | null
  locationName?: string | null
}>()

const { t } = useI18n()

const formatCoordinates = (lat?: number | null, lon?: number | null) => {
  if (lat == null || lon == null) return null
  return `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`
}

const hasLocation = computed(() => {
  return props.latitude != null && props.longitude != null
})

const mapCenter = computed(() => {
  if (hasLocation.value) {
    return [props.latitude!, props.longitude!] as [number, number]
  }
  return [0, 0] as [number, number]
})

const zoom = ref(13)
</script>

<template>
  <div v-if="hasLocation" class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-xl border border-gray-200/50 dark:border-gray-700/50 overflow-hidden flex flex-col h-[350px]">
    <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between z-10 bg-white dark:bg-gray-800/90">
      <div class="flex items-center space-x-3 overflow-hidden">
        <div class="p-2 bg-emerald-50 dark:bg-emerald-500/10 rounded-lg flex-shrink-0">
          <MapPinIcon class="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <h3 class="text-lg font-bold text-gray-900 dark:text-white tracking-tight truncate">
          {{ locationName || formatCoordinates(props.latitude, props.longitude) || t('remote.location') }}
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
</template>

<style scoped>
/* Leaflet Map Tweaks for Dark Mode */
.dark .leaflet-layer,
.dark .leaflet-control-zoom-in,
.dark .leaflet-control-zoom-out,
.dark .leaflet-control-attribution {
  filter: invert(100%) hue-rotate(180deg) brightness(95%) contrast(90%);
}
</style>
