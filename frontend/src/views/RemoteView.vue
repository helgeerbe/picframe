<script setup lang="ts">
import { onBeforeUnmount, onMounted, computed, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import type { MediaItem } from '../stores/player'
import { useConfigStore } from '../stores/config'
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
  mdiSpeedometer,
  mdiShuffleVariant
} from '@mdi/js'
import {
  ForwardIcon,
  BackwardIcon,
  SunIcon,
  PhotoIcon,
  InformationCircleIcon,
  DocumentTextIcon,
  FunnelIcon,
  CalendarDaysIcon,
  TagIcon,
  MapPinIcon,
  ClockIcon,
  CheckIcon,
  XMarkIcon
} from '@heroicons/vue/24/outline'
import {
  PlayIcon as PlayIconSolid,
  PauseIcon as PauseIconSolid,
  PowerIcon,
  TrashIcon as TrashIconSolid
} from '@heroicons/vue/24/solid'
import MapComponent from '../components/MapComponent.vue'
import HelperText from '../components/HelperText.vue'

const { t } = useI18n()
const playerStore = usePlayerStore()
const configStore = useConfigStore()
const { currentMedia, isPlaying, brightness, isDisplayOn, isConnected } = storeToRefs(playerStore)
const {
  config: appConfig,
  filterOptions,
  selectionCount,
  isLoading: isConfigLoading,
  isSelectionCountLoading,
  error: configError,
  selectionCountError
} = storeToRefs(configStore)

const mediaSelection = reactive({
  subdirectory: '',
  date_from: '',
  date_to: '',
  location_filter: '',
  tags_filter: '',
  time_delay: 200,
  fade_time: 10
})

const selectionMessage = ref('')
const isApplyingSelection = ref(false)
const isSavingShuffle = ref(false)
const selectedPairIndex = ref(0)
const showPairDeleteDialog = ref(false)
let selectionCountTimer: number | undefined

// Initialize WebSocket connection if not already connected
onMounted(() => {
  if (!isConnected.value) {
    playerStore.connect()
  }
  void configStore.fetchConfig()
  void configStore.fetchFilterOptions()
})

watch(
  [
    () => appConfig.value?.model?.subdirectory || '',
    () => appConfig.value?.model?.date_from || '',
    () => appConfig.value?.model?.date_to || '',
    () => appConfig.value?.model?.location_filter || '',
    () => appConfig.value?.model?.tags_filter || '',
    () => Number(appConfig.value?.model?.time_delay ?? 200),
    () => Number(appConfig.value?.model?.fade_time ?? 10)
  ],
  ([
    subdirectory,
    dateFrom,
    dateTo,
    locationFilter,
    tagsFilter,
    timeDelay,
    fadeTime
  ]) => {
    mediaSelection.subdirectory = subdirectory
    mediaSelection.date_from = dateFrom
    mediaSelection.date_to = dateTo
    mediaSelection.location_filter = locationFilter
    mediaSelection.tags_filter = tagsFilter
    mediaSelection.time_delay = timeDelay
    mediaSelection.fade_time = fadeTime
  },
  { immediate: true }
)

const selectionCountPayload = () => ({
  subdirectory: mediaSelection.subdirectory,
  date_from: mediaSelection.date_from,
  date_to: mediaSelection.date_to,
  location_filter: mediaSelection.location_filter,
  tags_filter: mediaSelection.tags_filter
})

const refreshSelectionCount = async () => {
  await configStore.fetchSelectionCount(selectionCountPayload())
}

const scheduleSelectionCountRefresh = () => {
  if (selectionCountTimer !== undefined) {
    window.clearTimeout(selectionCountTimer)
  }
  selectionCountTimer = window.setTimeout(() => {
    void refreshSelectionCount()
  }, 300)
}

watch(
  () => [
    mediaSelection.subdirectory,
    mediaSelection.date_from,
    mediaSelection.date_to,
    mediaSelection.location_filter,
    mediaSelection.tags_filter
  ],
  scheduleSelectionCountRefresh,
  { immediate: true }
)

onBeforeUnmount(() => {
  if (selectionCountTimer !== undefined) {
    window.clearTimeout(selectionCountTimer)
  }
})

watch(
  () => currentMedia.value,
  (media) => {
    selectedPairIndex.value = media?.primary_index ?? 0
    showPairDeleteDialog.value = false
  }
)

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

const isShuffleEnabled = computed(() => appConfig.value?.model?.shuffle ?? true)

const displayPowerTitle = computed(() => {
  return isDisplayOn.value ? t('remote.controls.turnDisplayOff') : t('remote.controls.turnDisplayOn')
})

const playPauseTitle = computed(() => {
  return isPlaying.value ? t('remote.controls.pause') : t('remote.controls.play')
})

const shuffleTitle = computed(() => {
  return isShuffleEnabled.value ? t('remote.controls.shuffleOn') : t('remote.controls.shuffleOff')
})

const toggleShuffle = async () => {
  if (isSavingShuffle.value || isConfigLoading.value) return
  isSavingShuffle.value = true
  try {
    await configStore.savePartialConfig({
      model: {
        shuffle: !isShuffleEnabled.value
      }
    })
    playerStore.sendCommand('REQUEST_STATE')
  } catch (error) {
    console.error(error)
  } finally {
    isSavingShuffle.value = false
  }
}

const currentMediaItems = computed(() => {
  if (currentMedia.value?.items?.length) return currentMedia.value.items
  return currentMedia.value ? [currentMedia.value] : []
})

const isPortraitPair = computed(() => {
  return currentMedia.value?.layout === 'portrait_pair' && currentMediaItems.value.length >= 2
})

const selectedMediaItem = computed(() => {
  const items = currentMediaItems.value
  if (!items.length) return null
  const index = Math.min(Math.max(selectedPairIndex.value, 0), items.length - 1)
  return items[index]
})

const pairSideLabel = (index: number) => index === 0 ? t('remote.pair.left') : t('remote.pair.right')

const handleDeleteClick = () => {
  if (isPortraitPair.value) {
    showPairDeleteDialog.value = true
    return
  }
  playerStore.sendCommand('DELETE')
}

const pairDeleteIds = (target: 'left' | 'right' | 'both') => {
  const items = currentMediaItems.value
  if (target === 'left') return items[0]?.id != null ? [items[0].id] : []
  if (target === 'right') return items[1]?.id != null ? [items[1].id] : []
  return items.map((item) => item.id).filter((id): id is number => id != null)
}

const deletePair = (target: 'left' | 'right' | 'both') => {
  playerStore.sendCommand('DELETE', {
    target,
    media_ids: pairDeleteIds(target)
  })
  showPairDeleteDialog.value = false
}

const cloneConfig = () => JSON.parse(JSON.stringify(appConfig.value || {}))

const applyMediaSelection = async () => {
  isApplyingSelection.value = true
  selectionMessage.value = ''
  try {
    const nextConfig = cloneConfig()
    nextConfig.model = {
      ...(nextConfig.model || {}),
      subdirectory: mediaSelection.subdirectory,
      date_from: mediaSelection.date_from,
      date_to: mediaSelection.date_to,
      location_filter: mediaSelection.location_filter,
      tags_filter: mediaSelection.tags_filter,
      time_delay: Number(mediaSelection.time_delay),
      fade_time: Number(mediaSelection.fade_time)
    }
    await configStore.saveConfig(nextConfig)
    await configStore.fetchFilterOptions()
    await refreshSelectionCount()
    playerStore.sendCommand('REQUEST_STATE')
    selectionMessage.value = t('remote.mediaSelection.applied')
  } catch (error) {
    console.error(error)
    selectionMessage.value = t('remote.mediaSelection.failed')
  } finally {
    isApplyingSelection.value = false
    window.setTimeout(() => {
      selectionMessage.value = ''
    }, 3000)
  }
}

const clearMediaSelection = () => {
  mediaSelection.subdirectory = ''
  mediaSelection.date_from = ''
  mediaSelection.date_to = ''
  mediaSelection.location_filter = ''
  mediaSelection.tags_filter = ''
}

const quoteFilterTerm = (term: string) => {
  const trimmed = term.trim()
  const sanitized = trimmed.replace(/"/g, '')
  return /\s|[()]/.test(sanitized) || /^(AND|OR|NOT)$/i.test(sanitized)
    ? `"${sanitized}"`
    : sanitized
}

type FilterJoiner = 'AND' | 'OR'

type FilterPart = {
  joiner: FilterJoiner | null
  term: string
}

const parseSimpleFilterExpression = (expression: string) => {
  const text = expression.trim()
  const parts: FilterPart[] = []
  let pendingJoiner: FilterJoiner | null = null
  let phraseParts: string[] = []
  let simple = true
  let index = 0

  const flushPhrase = () => {
    if (!phraseParts.length) return
    parts.push({
      joiner: parts.length === 0 ? null : pendingJoiner,
      term: phraseParts.join(' ').trim()
    })
    pendingJoiner = null
    phraseParts = []
  }

  while (index < text.length && simple) {
    while (index < text.length && /\s/.test(text[index])) index += 1
    if (index >= text.length) break

    if (text[index] === '(' || text[index] === ')') {
      simple = false
      break
    }

    let token = ''
    let wasQuoted = false
    if (text[index] === '"') {
      wasQuoted = true
      index += 1
      const start = index
      while (index < text.length && text[index] !== '"') index += 1
      if (index >= text.length) {
        simple = false
        break
      }
      token = text.slice(start, index)
      index += 1
    } else {
      const start = index
      while (index < text.length && !/\s|[()]/.test(text[index])) index += 1
      token = text.slice(start, index)
    }

    const upperToken = token.toUpperCase()
    if (!wasQuoted && upperToken === 'NOT') {
      simple = false
      break
    }

    if (!wasQuoted && (upperToken === 'AND' || upperToken === 'OR')) {
      if (!phraseParts.length) {
        simple = false
        break
      }
      flushPhrase()
      pendingJoiner = upperToken as FilterJoiner
      continue
    }

    phraseParts.push(token)
  }

  flushPhrase()

  if (pendingJoiner !== null) {
    simple = false
  }

  return { parts, simple }
}

const normalizeFilterTerm = (term: string) => term.trim().replace(/^"([^"]*)"$/, '$1')

const serializeFilterParts = (parts: FilterPart[]) => {
  return parts.map((part, partIndex) => {
    const prefix = partIndex === 0 ? '' : `${part.joiner || 'OR'} `
    return `${prefix}${quoteFilterTerm(part.term)}`
  }).join(' ')
}

const appendFilterTerm = (expression: string, term: string, joiner: FilterJoiner) => {
  const current = expression.trim()
  return current ? `${current} ${joiner} ${term}` : term
}

const filterContainsTerm = (expression: string, term: string) => {
  const parsed = parseSimpleFilterExpression(expression)
  const normalizedTerm = normalizeFilterTerm(term)
  return parsed.simple && parsed.parts.some((part) => part.term === normalizedTerm)
}

const toggleFilterTerm = (expression: string, term: string, joiner: FilterJoiner) => {
  const parsed = parseSimpleFilterExpression(expression)
  const normalizedTerm = normalizeFilterTerm(term)

  if (!parsed.simple) {
    return appendFilterTerm(expression, term, joiner)
  }

  if (!parsed.parts.some((part) => part.term === normalizedTerm)) {
    return appendFilterTerm(expression, term, joiner)
  }

  const nextParts = parsed.parts.filter((part) => part.term !== normalizedTerm)
  if (nextParts.length) {
    nextParts[0].joiner = null
  }
  return serializeFilterParts(nextParts)
}

const setLocationFilter = (location: string, event?: MouseEvent) => {
  const value = quoteFilterTerm(location)
  const joiner = event?.shiftKey ? 'AND' : 'OR'
  mediaSelection.location_filter = toggleFilterTerm(mediaSelection.location_filter, value, joiner)
}

const setTagFilter = (tag: string, event?: MouseEvent) => {
  const value = quoteFilterTerm(tag)
  const joiner = event?.shiftKey ? 'AND' : 'OR'
  mediaSelection.tags_filter = toggleFilterTerm(mediaSelection.tags_filter, value, joiner)
}

const formatCount = (value: number) => Number(value || 0).toLocaleString()

const selectionCountLabel = computed(() => {
  if (isSelectionCountLoading.value) return t('remote.mediaSelection.countLoading')
  if (selectionCountError.value) return t('remote.mediaSelection.countError')
  return t('remote.mediaSelection.countBadge', {
    selected: formatCount(selectionCount.value.selected_count),
    total: formatCount(selectionCount.value.total_count)
  })
})

const selectionCountTitle = computed(() => {
  const scope = selectionCount.value.scope_label || t('remote.mediaSelection.allFolders')
  return t('remote.mediaSelection.countTitle', { scope })
})

const filterHelpText = computed(() => {
  return `${t('remote.mediaSelection.filterHelp')} ${t('remote.mediaSelection.filterExamples')}`
})

// Computed properties for safe access
const fileNameFor = (media: MediaItem | null) => {
  if (!media?.file_path) return t('remote.unknownFile')
  try {
    const url = new URL(media.file_path, window.location.origin)
    const pathParam = url.searchParams.get('path')
    const pathToUse = pathParam || url.pathname
    const decoded = decodeURIComponent(pathToUse)
    return decoded.split('/').pop() || t('remote.unknownFile')
  } catch (e) {
    return media.file_path.split('/').pop() || t('remote.unknownFile')
  }
}

const displayFileName = computed(() => {
  return fileNameFor(selectedMediaItem.value)
})

const currentMediaTags = computed(() => {
  const tags = selectedMediaItem.value?.exif?.tags
  return String(tags || '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean)
})

const metadataFields = computed(() => {
  const data = selectedMediaItem.value?.exif || {}
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

  if (data.displayed_count !== undefined && data.displayed_count !== null) {
    fields.push({
      key: 'displayedCount',
      label: t('remote.metadata.displayedCount'),
      icon: mdiSpeedometer,
      value: Number(data.displayed_count).toLocaleString()
    })
  }

  if (data.last_displayed) {
    fields.push({
      key: 'lastDisplayed',
      label: t('remote.metadata.lastDisplayed'),
      icon: mdiClockOutline,
      value: new Date(Number(data.last_displayed) * 1000).toLocaleString()
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
        <p class="font-bold text-sm">{{ t('remote.connecting') }}</p>
        <p class="text-xs opacity-80">{{ t('remote.establishing') }}</p>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-12 gap-8 items-start">
      
      <!-- Left Column: Media & Controls -->
      <div class="xl:col-span-7 flex flex-col space-y-6">
        
        <!-- Media Player Card -->
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-2xl overflow-hidden border border-gray-200/50 dark:border-gray-700/50 flex-grow flex flex-col">
          
          <!-- Image Preview Area -->
          <div class="relative w-full bg-black/5 dark:bg-black/40 flex items-center justify-center overflow-hidden group aspect-video">
            <div
              v-if="isPortraitPair"
              class="absolute inset-0 grid grid-cols-2 gap-2 p-2"
            >
              <button
                v-for="(item, index) in currentMediaItems.slice(0, 2)"
                :key="item.id ?? item.file_path"
                type="button"
                @click="selectedPairIndex = index"
                :aria-pressed="selectedPairIndex === index"
                class="relative min-w-0 overflow-hidden rounded-lg bg-black/40 focus:outline-none focus:ring-2 focus:ring-white/80"
                :class="selectedPairIndex === index ? 'ring-2 ring-sky-300' : 'ring-1 ring-white/10'"
              >
                <img
                  :src="item.file_path"
                  :alt="pairSideLabel(index)"
                  class="h-full w-full object-contain"
                  @error="console.error('Failed to load image:', item.file_path)"
                />
                <span class="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-xs font-semibold text-white backdrop-blur-sm">
                  {{ pairSideLabel(index) }}
                </span>
              </button>
            </div>
            <img
              v-else-if="selectedMediaItem?.file_path"
              :src="selectedMediaItem.file_path"
              :alt="t('remote.controls.currentMedia')"
              class="absolute inset-0 w-full h-full object-contain transition-transform duration-1000 ease-out group-hover:scale-[1.02]"
              @error="console.error('Failed to load image:', selectedMediaItem?.file_path)"
            />
            <div v-else class="flex flex-col items-center text-gray-400 dark:text-gray-500">
              <PhotoIcon class="w-24 h-24 mb-4 opacity-20" />
              <p class="text-sm font-medium uppercase tracking-wide opacity-60">{{ t('remote.noMedia') }}</p>
            </div>
            
            <!-- Adaptive Cinematic Gradient Overlay -->
            <div class="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent opacity-40 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"></div>
            
            <!-- Narrative Metadata Overlay (Progressive Disclosure) -->
            <div class="absolute bottom-0 left-0 right-0 p-6 transition-all duration-500 flex justify-between items-end group-hover:backdrop-blur-sm">
              <div class="flex-1 min-w-0 pr-4 pointer-events-none">
                <!-- Title (Always visible) -->
                <h2 class="text-2xl font-bold text-white truncate drop-shadow-md transition-transform duration-500 group-hover:-translate-y-1">
                  {{ selectedMediaItem?.exif?.title || displayFileName }}
                </h2>
                
                <!-- Progressive Disclosure: Caption & Tags (Visible on hover) -->
                <div class="grid grid-rows-[0fr] group-hover:grid-rows-[1fr] transition-all duration-500 ease-in-out opacity-0 group-hover:opacity-100">
                  <div class="overflow-hidden">
                    <p v-if="selectedMediaItem?.exif?.caption" class="text-sm text-gray-200 mt-2 line-clamp-3 drop-shadow">
                      {{ selectedMediaItem.exif.caption }}
                    </p>
                    
                    <div v-if="currentMediaTags.length" class="flex overflow-x-auto hide-scrollbar space-x-2 mt-3 pb-1 pointer-events-auto">
                      <button
                        v-for="tag in currentMediaTags"
                        :key="tag"
                        type="button"
                        :aria-pressed="filterContainsTerm(mediaSelection.tags_filter, quoteFilterTerm(tag))"
                        :title="t('remote.mediaSelection.chipTitle')"
                        @click.stop="setTagFilter(tag, $event)"
                        :class="[
                          'whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold text-white backdrop-blur-md transition-colors focus:outline-none focus:ring-2 focus:ring-white/70',
                          filterContainsTerm(mediaSelection.tags_filter, quoteFilterTerm(tag))
                            ? 'border-sky-300 bg-sky-500/90'
                            : 'border-white/15 bg-white/20 hover:bg-white/30'
                        ]"
                      >
                        {{ tag }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
              
              <button
                type="button"
                @click="handleDeleteClick"
                class="pointer-events-auto inline-flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-red-600/85 text-white opacity-90 shadow-lg backdrop-blur-sm transition-all hover:scale-105 hover:bg-red-500 focus:scale-105 focus:opacity-100 focus:outline-none focus:ring-2 focus:ring-red-500/50 active:scale-95 lg:opacity-0 lg:group-hover:opacity-100"
                :aria-label="t('remote.controls.delete')"
                :title="t('remote.controls.delete')"
              >
                <TrashIconSolid class="w-6 h-6" />
                <span class="sr-only">{{ t('remote.controls.delete') }}</span>
              </button>
            </div>
          </div>

          <!-- Controls Area -->
          <div class="bg-white p-4 dark:bg-gray-800/90 sm:p-6 lg:p-8 border-t border-gray-100 dark:border-gray-700/50">
            
            <!-- Transport Controls -->
            <div class="mx-auto grid max-w-md grid-cols-5 items-center justify-items-center gap-2 sm:max-w-lg sm:gap-4">
              <button
                type="button"
                @click="playerStore.toggleDisplayPower()"
                :aria-label="displayPowerTitle"
                :title="displayPowerTitle"
                :class="[
                  'inline-flex h-12 w-12 items-center justify-center rounded-full border transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95',
                  isDisplayOn
                    ? 'border-emerald-100 bg-emerald-50 text-emerald-600 hover:bg-emerald-100 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300'
                    : 'border-red-100 bg-red-50 text-red-600 hover:bg-red-100 dark:border-red-500/20 dark:bg-red-500/10 dark:text-red-300'
                ]"
              >
                <PowerIcon class="w-6 h-6" />
                <span class="sr-only">{{ displayPowerTitle }}</span>
              </button>

              <button
                type="button"
                @click="playerStore.previous()"
                class="inline-flex h-14 w-14 items-center justify-center rounded-full text-gray-500 transition-all hover:bg-gray-100 hover:text-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95 dark:text-gray-400 dark:hover:bg-gray-700/50 dark:hover:text-indigo-400"
                :aria-label="t('remote.controls.previous')"
                :title="t('remote.controls.previous')"
              >
                <BackwardIcon class="w-7 h-7" />
                <span class="sr-only">{{ t('remote.controls.previous') }}</span>
              </button>
              
              <button
                type="button"
                @click="togglePlayPause"
                class="inline-flex h-16 w-16 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg shadow-indigo-600/30 transition-all hover:-translate-y-0.5 hover:bg-indigo-500 hover:shadow-indigo-600/50 focus:outline-none focus:ring-4 focus:ring-indigo-500/50 active:scale-95 sm:h-[72px] sm:w-[72px]"
                :aria-label="playPauseTitle"
                :title="playPauseTitle"
              >
                <PauseIconSolid v-if="isPlaying" class="w-8 h-8 sm:w-9 sm:h-9" />
                <PlayIconSolid v-else class="ml-1 w-8 h-8 sm:w-9 sm:h-9" />
                <span class="sr-only">{{ playPauseTitle }}</span>
              </button>
              
              <button
                type="button"
                @click="playerStore.next()"
                class="inline-flex h-14 w-14 items-center justify-center rounded-full text-gray-500 transition-all hover:bg-gray-100 hover:text-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95 dark:text-gray-400 dark:hover:bg-gray-700/50 dark:hover:text-indigo-400"
                :aria-label="t('remote.controls.next')"
                :title="t('remote.controls.next')"
              >
                <ForwardIcon class="w-7 h-7" />
                <span class="sr-only">{{ t('remote.controls.next') }}</span>
              </button>

              <button
                type="button"
                @click="toggleShuffle"
                :disabled="isSavingShuffle || isConfigLoading"
                :aria-pressed="isShuffleEnabled"
                :aria-label="shuffleTitle"
                :title="shuffleTitle"
                :class="[
                  'inline-flex h-12 w-12 items-center justify-center rounded-full border transition-all focus:outline-none focus:ring-2 focus:ring-indigo-500/50 active:scale-95',
                  isShuffleEnabled
                    ? 'border-indigo-100 bg-indigo-50 text-indigo-600 hover:bg-indigo-100 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-300'
                    : 'border-transparent text-gray-500 hover:bg-gray-100 hover:text-indigo-600 dark:text-gray-400 dark:hover:bg-gray-700/50 dark:hover:text-indigo-400',
                  isSavingShuffle || isConfigLoading ? 'opacity-60 cursor-wait' : ''
                ]"
              >
                <svg class="w-6 h-6" viewBox="0 0 24 24" aria-hidden="true">
                  <path :d="mdiShuffleVariant" fill="currentColor" />
                </svg>
                <span class="sr-only">{{ shuffleTitle }}</span>
              </button>
            </div>

            <!-- Brightness Control -->
            <div class="mt-5 border-t border-gray-100 pt-5 dark:border-gray-700/50">
              <label for="remote-brightness" class="sr-only">{{ t('remote.controls.brightness') }}</label>
              <div class="flex items-center gap-3 sm:gap-4">
                <SunIcon class="h-6 w-6 flex-shrink-0 text-gray-400 dark:text-gray-500" />
                <input
                  id="remote-brightness"
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  :value="brightness"
                  :aria-label="t('remote.controls.brightness')"
                  @input="handleBrightnessChange"
                  class="h-6 w-full cursor-pointer accent-indigo-600 transition-all hover:accent-indigo-500"
                >
                <span class="w-14 flex-shrink-0 text-right text-sm font-bold tabular-nums text-gray-600 dark:text-gray-300">{{ Math.round(brightness * 100) }}%</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Map Card -->
        <MapComponent
          :latitude="selectedMediaItem?.location?.lat"
          :longitude="selectedMediaItem?.location?.lon"
          :location-name="selectedMediaItem?.exif?.location_name"
        />
      </div>

      <!-- Right Column: Metadata & Controls -->
      <div class="xl:col-span-5 flex flex-col space-y-6">

        <!-- Media Selection Card -->
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-2xl shadow-xl border border-gray-200/50 dark:border-gray-700/50 overflow-hidden">
          <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between">
            <div class="flex items-center space-x-3 min-w-0">
              <div class="p-2 bg-sky-50 dark:bg-sky-500/10 rounded-lg">
                <FunnelIcon class="w-5 h-5 text-sky-600 dark:text-sky-400" />
              </div>
              <div class="min-w-0">
                <h3 class="text-lg font-bold text-gray-900 dark:text-white tracking-tight truncate">{{ t('remote.mediaSelection.title') }}</h3>
                <div class="mt-1 flex items-center gap-1">
                  <span
                    class="inline-flex items-center rounded-full border border-sky-100 bg-sky-50 px-2 py-0.5 text-xs font-semibold text-sky-700 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300"
                    :title="selectionCountTitle"
                  >
                    {{ selectionCountLabel }}
                  </span>
                  <HelperText :text="selectionCountTitle" />
                </div>
              </div>
            </div>
            <button
              type="button"
              @click="clearMediaSelection"
              class="p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 dark:hover:text-gray-200 dark:hover:bg-gray-700/50 transition-colors focus:outline-none focus:ring-2 focus:ring-sky-500/50"
              :title="t('remote.mediaSelection.clear')"
            >
              <XMarkIcon class="w-5 h-5" />
            </button>
          </div>

          <div class="p-6 space-y-6">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label class="space-y-2 sm:col-span-2">
                <span class="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">{{ t('remote.mediaSelection.subdirectory') }}</span>
                <select
                  v-model="mediaSelection.subdirectory"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
                  <option value="">{{ t('remote.mediaSelection.allFolders') }}</option>
                  <option v-for="folder in filterOptions.subdirectories" :key="folder" :value="folder">{{ folder }}</option>
                </select>
              </label>

              <label class="space-y-2">
                <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <CalendarDaysIcon class="w-4 h-4" />
                  {{ t('remote.mediaSelection.dateFrom') }}
                </span>
                <input
                  v-model="mediaSelection.date_from"
                  type="date"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
              </label>

              <label class="space-y-2">
                <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <CalendarDaysIcon class="w-4 h-4" />
                  {{ t('remote.mediaSelection.dateTo') }}
                </span>
                <input
                  v-model="mediaSelection.date_to"
                  type="date"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
              </label>
            </div>

            <div class="space-y-4">
              <label class="space-y-2 block">
                <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <MapPinIcon class="w-4 h-4" />
                  {{ t('remote.mediaSelection.location') }}
                  <HelperText :text="filterHelpText" mode="dialog" />
                </span>
                <input
                  v-model="mediaSelection.location_filter"
                  list="location-filter-options"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
                <datalist id="location-filter-options">
                  <option v-for="location in filterOptions.locations" :key="location" :value="location" />
                </datalist>
              </label>
              <div v-if="filterOptions.locations.length" class="flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1 custom-scrollbar">
                <button
                  v-for="location in filterOptions.locations"
                  :key="location"
                  type="button"
                  :aria-pressed="filterContainsTerm(mediaSelection.location_filter, quoteFilterTerm(location))"
                  :title="t('remote.mediaSelection.chipTitle')"
                  @click="setLocationFilter(location, $event)"
                  :class="[
                    'px-2.5 py-1 rounded-full text-xs font-semibold transition-colors border',
                    filterContainsTerm(mediaSelection.location_filter, quoteFilterTerm(location))
                      ? 'bg-sky-600 text-white border-sky-600'
                      : 'bg-white dark:bg-gray-900/50 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-700 hover:border-sky-400'
                  ]"
                >
                  {{ location }}
                </button>
              </div>

              <label class="space-y-2 block">
                <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <TagIcon class="w-4 h-4" />
                  {{ t('remote.mediaSelection.tags') }}
                  <HelperText :text="filterHelpText" mode="dialog" />
                </span>
                <input
                  v-model="mediaSelection.tags_filter"
                  list="tag-filter-options"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
                <datalist id="tag-filter-options">
                  <option v-for="tag in filterOptions.tags" :key="tag" :value="tag" />
                </datalist>
              </label>
              <div v-if="filterOptions.tags.length" class="flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1 custom-scrollbar">
                <button
                  v-for="tag in filterOptions.tags"
                  :key="tag"
                  type="button"
                  :aria-pressed="filterContainsTerm(mediaSelection.tags_filter, quoteFilterTerm(tag))"
                  :title="t('remote.mediaSelection.chipTitle')"
                  @click="setTagFilter(tag, $event)"
                  :class="[
                    'px-2.5 py-1 rounded-full text-xs font-semibold transition-colors border',
                    filterContainsTerm(mediaSelection.tags_filter, quoteFilterTerm(tag))
                      ? 'bg-sky-600 text-white border-sky-600'
                      : 'bg-white dark:bg-gray-900/50 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-700 hover:border-sky-400'
                  ]"
                >
                  {{ tag }}
                </button>
              </div>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <label class="space-y-2">
                <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <ClockIcon class="w-4 h-4" />
                  {{ t('remote.mediaSelection.delay') }}
                </span>
                <input
                  v-model.number="mediaSelection.time_delay"
                  type="number"
                  min="1"
                  step="1"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
              </label>

              <label class="space-y-2">
                <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <ClockIcon class="w-4 h-4" />
                  {{ t('remote.mediaSelection.fade') }}
                </span>
                <input
                  v-model.number="mediaSelection.fade_time"
                  type="number"
                  min="0"
                  step="0.5"
                  class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                >
              </label>
            </div>

            <div class="flex flex-col sm:flex-row sm:items-center gap-3">
              <button
                type="button"
                @click="applyMediaSelection"
                :disabled="isApplyingSelection || isConfigLoading"
                class="inline-flex items-center justify-center px-4 py-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 text-white text-sm font-bold transition-colors focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
              >
                <CheckIcon class="w-4 h-4 mr-2" />
                {{ isApplyingSelection ? t('remote.mediaSelection.applying') : t('remote.mediaSelection.apply') }}
              </button>
            </div>

            <p v-if="selectionMessage || configError" class="text-sm font-medium" :class="configError ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'">
              {{ configError || selectionMessage }}
            </p>
          </div>
        </div>

        <!-- Metadata Card -->
        <div class="bg-white dark:bg-gray-800/90 backdrop-blur-xl rounded-3xl shadow-xl border border-gray-200/50 dark:border-gray-700/50 overflow-hidden flex-grow">
          <div class="px-6 py-5 border-b border-gray-100 dark:border-gray-700/50 flex items-center justify-between">
            <div class="flex items-center space-x-3">
              <div class="p-2 bg-indigo-50 dark:bg-indigo-500/10 rounded-lg">
                <InformationCircleIcon class="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <h3 class="text-lg font-bold text-gray-900 dark:text-white tracking-tight">{{ t('remote.mediaDetails') }}</h3>
            </div>
            <div
              v-if="isPortraitPair"
              class="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-1 dark:border-gray-700 dark:bg-gray-900/50"
            >
              <button
                v-for="(_, index) in currentMediaItems.slice(0, 2)"
                :key="index"
                type="button"
                @click="selectedPairIndex = index"
                :aria-pressed="selectedPairIndex === index"
                :class="[
                  'rounded-md px-3 py-1.5 text-xs font-bold transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-500/50',
                  selectedPairIndex === index
                    ? 'bg-white text-indigo-700 shadow-sm dark:bg-gray-700 dark:text-indigo-200'
                    : 'text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-100'
                ]"
              >
                {{ pairSideLabel(index) }}
              </button>
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

    <div
      v-if="showPairDeleteDialog"
      class="fixed inset-0 z-50 flex items-center justify-center bg-gray-950/70 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      :aria-label="t('remote.pair.deleteTitle')"
    >
      <div class="w-full max-w-xl rounded-2xl bg-white p-6 shadow-2xl dark:bg-gray-800">
        <div class="flex items-start justify-between gap-4">
          <div>
            <h3 class="text-lg font-bold text-gray-900 dark:text-white">{{ t('remote.pair.deleteTitle') }}</h3>
            <p class="mt-1 text-sm text-gray-500 dark:text-gray-400">{{ t('remote.pair.deletePrompt') }}</p>
          </div>
          <button
            type="button"
            @click="showPairDeleteDialog = false"
            class="rounded-lg p-2 text-gray-400 hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus:ring-2 focus:ring-red-500/50 dark:hover:bg-gray-700 dark:hover:text-gray-100"
            :aria-label="t('settings.cancel')"
          >
            <XMarkIcon class="h-5 w-5" />
          </button>
        </div>

        <div class="mt-5 grid grid-cols-2 gap-3">
          <div
            v-for="(item, index) in currentMediaItems.slice(0, 2)"
            :key="item.id ?? item.file_path"
            class="overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/50"
          >
            <div class="aspect-video bg-black/80">
              <img :src="item.file_path" :alt="pairSideLabel(index)" class="h-full w-full object-contain" />
            </div>
            <div class="p-3">
              <p class="text-xs font-bold uppercase tracking-wide text-gray-500 dark:text-gray-400">{{ pairSideLabel(index) }}</p>
              <p class="mt-1 truncate text-sm font-semibold text-gray-900 dark:text-gray-100" :title="fileNameFor(item)">
                {{ fileNameFor(item) }}
              </p>
            </div>
          </div>
        </div>

        <div class="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <button
            type="button"
            @click="deletePair('left')"
            class="inline-flex items-center justify-center rounded-xl bg-red-100 px-4 py-2.5 text-sm font-bold text-red-700 transition-colors hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-red-500/50 dark:bg-red-600 dark:text-white dark:hover:bg-red-500"
          >
            {{ t('remote.pair.deleteLeft') }}
          </button>
          <button
            type="button"
            @click="deletePair('right')"
            class="inline-flex items-center justify-center rounded-xl bg-red-100 px-4 py-2.5 text-sm font-bold text-red-700 transition-colors hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-red-500/50 dark:bg-red-600 dark:text-white dark:hover:bg-red-500"
          >
            {{ t('remote.pair.deleteRight') }}
          </button>
          <button
            type="button"
            @click="deletePair('both')"
            class="inline-flex items-center justify-center rounded-xl bg-red-600 px-4 py-2.5 text-sm font-bold text-white transition-colors hover:bg-red-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
          >
            {{ t('remote.pair.deleteBoth') }}
          </button>
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
