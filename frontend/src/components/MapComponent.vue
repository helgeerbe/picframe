<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowsPointingOutIcon, MapPinIcon } from '@heroicons/vue/24/outline'
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
  expanded?: boolean
  showExpand?: boolean
}>()

const emit = defineEmits<{
  expand: []
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
const map = ref<any | null>(null)

const containerClass = computed(() => {
  return props.expanded
    ? 'h-full rounded-none border-0 shadow-none'
    : 'h-[350px] rounded-lg border border-gray-200 shadow-sm dark:border-gray-700'
})

function invalidateMapSize() {
  nextTick(() => {
    window.setTimeout(() => {
      map.value?.leafletObject?.invalidateSize?.()
    }, 80)
  })
}

watch(() => props.expanded, invalidateMapSize)
watch(mapCenter, invalidateMapSize)
</script>

<template>
  <div v-if="hasLocation" :class="['flex flex-col overflow-hidden bg-white dark:bg-gray-800', containerClass]">
    <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between z-10 bg-white dark:bg-gray-800/90">
      <div class="flex items-center space-x-3 overflow-hidden">
        <div class="p-2 bg-emerald-50 dark:bg-emerald-500/10 rounded-lg flex-shrink-0">
          <MapPinIcon class="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
        </div>
        <h3 class="truncate text-lg font-bold tracking-normal text-gray-900 dark:text-white">
          {{ locationName || formatCoordinates(props.latitude, props.longitude) || t('remote.location') }}
        </h3>
      </div>
      <button
        v-if="showExpand"
        type="button"
        class="ml-3 inline-flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 dark:text-gray-400 dark:hover:bg-gray-700 dark:hover:text-white"
        :aria-label="t('remote.expand')"
        :title="t('remote.expand')"
        @click="emit('expand')"
      >
        <ArrowsPointingOutIcon class="h-5 w-5" />
      </button>
    </div>
    
    <div class="flex-grow w-full relative z-0">
      <l-map ref="map" v-model:zoom="zoom" :center="mapCenter" :use-global-leaflet="false" class="z-0">
        <l-tile-layer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          layer-type="base"
          name="OpenStreetMap"
          attribution="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors"
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
