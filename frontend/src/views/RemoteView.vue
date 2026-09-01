<script setup lang="ts">
import { onBeforeUnmount, onMounted, computed, reactive, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { usePlayerStore } from '../stores/player'
import type { MediaItem } from '../stores/player'
import { useConfigStore } from '../stores/config'
import type { LocationOption } from '../stores/config'
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
  FunnelIcon,
  CalendarDaysIcon,
  TagIcon,
  MapPinIcon,
  CheckIcon,
  XMarkIcon,
  ChevronDownIcon,
  ArrowsPointingOutIcon,
  MagnifyingGlassIcon
} from '@heroicons/vue/24/outline'
import {
  PlayIcon as PlayIconSolid,
  PauseIcon as PauseIconSolid,
  PowerIcon,
  TrashIcon as TrashIconSolid
} from '@heroicons/vue/24/solid'
import MapComponent from '../components/MapComponent.vue'
import HelperText from '../components/HelperText.vue'
import MediaInfoSheet from '../components/remote/MediaInfoSheet.vue'
import InfoButton from '../components/ui/InfoButton.vue'
import AppDialog from '../components/ui/AppDialog.vue'
import StatusBanner from '../components/ui/StatusBanner.vue'

const { t } = useI18n()
const playerStore = usePlayerStore()
const configStore = useConfigStore()
const { currentMedia, isPlaying, brightness, isDisplayOn } = storeToRefs(playerStore)
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
  tags_filter: ''
})

const selectionMessage = ref('')
const isApplyingSelection = ref(false)
const isSavingShuffle = ref(false)
const isShuffleModeMenuOpen = ref(false)
const shuffleModeMenuRef = ref<HTMLElement | null>(null)
const selectedPairIndex = ref(0)
const showPairDeleteDialog = ref(false)
const expandedPanel = ref<'media' | 'map' | null>(null)
const expandedVideoAutoplay = ref(false)
const isMediaOverlayPinned = ref(false)
const isMediaInfoOpen = ref(false)
const imageLoadFailures = ref<Record<string, number>>({})
const videoPosterFailures = ref<Record<string, boolean>>({})
const locationSearch = ref('')
const locationSearchResults = ref<LocationOption[]>([])
const isLocationSearchLoading = ref(false)
const tagSearch = ref('')
let selectionCountTimer: number | undefined
let locationSearchTimer: number | undefined
const TAG_SEARCH_THRESHOLD = 100
const MAX_IMAGE_AUTO_RETRIES = 2

const shuffleModes = [
  { value: 'random', labelKey: 'remote.controls.shuffleModeStandard' },
  { value: 'fewer_repeats', labelKey: 'remote.controls.shuffleModeFewerRepeats' },
  { value: 'age_weighted', labelKey: 'remote.controls.shuffleModeAgeWeighted' }
] as const
type ShuffleMode = typeof shuffleModes[number]['value']

const normalizeShuffleMode = (value: unknown): ShuffleMode => {
  if (value === 'fewer_repeats' || value === 'age_weighted') return value
  return 'random'
}

const closeShuffleModeMenu = () => {
  isShuffleModeMenuOpen.value = false
}

const handleDocumentClick = (event: MouseEvent) => {
  if (!isShuffleModeMenuOpen.value) return
  const target = event.target
  if (!(target instanceof Node)) return
  if (!shuffleModeMenuRef.value?.contains(target)) {
    closeShuffleModeMenu()
  }
}

const handleDocumentKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') {
    if (expandedPanel.value) {
      closeExpandedPanel()
      return
    }
    closeShuffleModeMenu()
  }
}

onMounted(() => {
  void configStore.fetchWorkflowConfig()
  void configStore.fetchFilterOptions()
  document.addEventListener('click', handleDocumentClick)
  document.addEventListener('keydown', handleDocumentKeydown)
})

watch(
  [
    () => appConfig.value?.model?.subdirectory || '',
    () => appConfig.value?.model?.date_from || '',
    () => appConfig.value?.model?.date_to || '',
    () => appConfig.value?.model?.location_filter || '',
    () => appConfig.value?.model?.tags_filter || ''
  ],
  ([
    subdirectory,
    dateFrom,
    dateTo,
    locationFilter,
    tagsFilter
  ]) => {
    mediaSelection.subdirectory = subdirectory
    mediaSelection.date_from = dateFrom
    mediaSelection.date_to = dateTo
    mediaSelection.location_filter = locationFilter
    mediaSelection.tags_filter = tagsFilter
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
  if (locationSearchTimer !== undefined) {
    window.clearTimeout(locationSearchTimer)
  }
  document.removeEventListener('click', handleDocumentClick)
  document.removeEventListener('keydown', handleDocumentKeydown)
})

watch(
  () => currentMedia.value,
  (media) => {
    selectedPairIndex.value = media?.primary_index ?? 0
    showPairDeleteDialog.value = false
    isMediaInfoOpen.value = false
    expandedVideoAutoplay.value = false
    isMediaOverlayPinned.value = false
    imageLoadFailures.value = {}
    videoPosterFailures.value = {}
  }
)

const togglePlayPause = () => {
  if (isPlaying.value) {
    playerStore.pause()
  } else {
    playerStore.play()
  }
}

const readBrightnessEventValue = (event: Event) => {
  const target = event.target as HTMLInputElement
  return parseFloat(target.value)
}

const handleBrightnessPreview = (event: Event) => {
  playerStore.previewBrightness(readBrightnessEventValue(event))
}

const handleBrightnessCommit = (event: Event) => {
  playerStore.setBrightness(readBrightnessEventValue(event))
}

const isShuffleEnabled = computed(() => appConfig.value?.model?.shuffle ?? true)
const shuffleMode = computed(() => normalizeShuffleMode(appConfig.value?.model?.shuffle_mode))

const displayPowerTitle = computed(() => {
  return isDisplayOn.value ? t('remote.controls.turnDisplayOff') : t('remote.controls.turnDisplayOn')
})

const playPauseTitle = computed(() => {
  return isPlaying.value ? t('remote.controls.pause') : t('remote.controls.play')
})

const shuffleTitle = computed(() => {
  return isShuffleEnabled.value ? t('remote.controls.shuffleOn') : t('remote.controls.shuffleOff')
})

const selectedShuffleModeLabel = computed(() => {
  const mode = shuffleModes.find((item) => item.value === shuffleMode.value) ?? shuffleModes[0]
  return t(mode.labelKey)
})

const shuffleModeTitle = computed(() => {
  return `${t('remote.controls.shuffleMode')}: ${selectedShuffleModeLabel.value}`
})

const toggleShuffle = async () => {
  if (isSavingShuffle.value || isConfigLoading.value) return
  closeShuffleModeMenu()
  isSavingShuffle.value = true
  try {
    await configStore.saveWorkflowConfig({
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

const toggleShuffleModeMenu = () => {
  if (isSavingShuffle.value || isConfigLoading.value) return
  isShuffleModeMenuOpen.value = !isShuffleModeMenuOpen.value
}

const setShuffleMode = async (mode: ShuffleMode) => {
  closeShuffleModeMenu()
  if (isSavingShuffle.value || isConfigLoading.value) return
  if (mode === shuffleMode.value) return
  isSavingShuffle.value = true
  try {
    await configStore.saveWorkflowConfig({
      model: {
        shuffle_mode: mode
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

const isVideoMedia = (media: MediaItem | null | undefined) => {
  if (!media) return false
  if (String(media.media_type || '').toLowerCase() === 'video') return true
  return /\.(mp4|mov|mkv|avi|webm|flv|hevc)(?:$|[?#])/i.test(media.file_path || '')
}

const mediaImageKey = (media: MediaItem | null | undefined) => media?.file_path || ''

const mediaImageSrc = (media: MediaItem | null | undefined) => {
  const source = mediaImageKey(media)
  if (!source) return ''
  const retryCount = imageLoadFailures.value[source] || 0
  if (retryCount <= 0) return source
  try {
    const url = new URL(source, window.location.origin)
    url.searchParams.set('_picframe_preview_retry', String(retryCount))
    return url.toString()
  } catch (error) {
    const separator = source.includes('?') ? '&' : '?'
    return `${source}${separator}_picframe_preview_retry=${retryCount}`
  }
}

const mediaPosterSrc = (media: MediaItem | null | undefined) => {
  const source = mediaImageKey(media)
  if (!source) return ''
  try {
    const url = new URL(source, window.location.origin)
    url.pathname = '/media/poster'
    url.searchParams.delete('_picframe_preview_retry')
    return url.toString()
  } catch (error) {
    return ''
  }
}

const mediaVideoSrc = (media: MediaItem | null | undefined) => media?.file_path || ''

const hasMediaImageFailed = (media: MediaItem | null | undefined) => {
  const key = mediaImageKey(media)
  return key ? (imageLoadFailures.value[key] || 0) >= MAX_IMAGE_AUTO_RETRIES : false
}

const hasVideoPosterFailed = (media: MediaItem | null | undefined) => {
  const key = mediaImageKey(media)
  return key ? Boolean(videoPosterFailures.value[key]) : false
}

const handleVideoPosterError = (media: MediaItem | null | undefined) => {
  const key = mediaImageKey(media)
  if (!key) return
  videoPosterFailures.value = {
    ...videoPosterFailures.value,
    [key]: true
  }
}

const handleMediaImageError = (media: MediaItem | null | undefined) => {
  const key = mediaImageKey(media)
  if (!key) return
  const currentFailures = imageLoadFailures.value[key] || 0
  if (currentFailures >= MAX_IMAGE_AUTO_RETRIES) return
  const nextFailures = currentFailures + 1
  imageLoadFailures.value = {
    ...imageLoadFailures.value,
    [key]: nextFailures
  }
  if (nextFailures >= MAX_IMAGE_AUTO_RETRIES) {
    playerStore.connect()
    playerStore.sendCommand('REQUEST_STATE')
  }
}

const retryMediaImage = (media: MediaItem | null | undefined) => {
  const key = mediaImageKey(media)
  if (!key) return
  imageLoadFailures.value = {
    ...imageLoadFailures.value,
    [key]: (imageLoadFailures.value[key] || 0) + 1
  }
  playerStore.connect()
  playerStore.sendCommand('REQUEST_STATE')
}

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

const applyMediaSelection = async () => {
  isApplyingSelection.value = true
  selectionMessage.value = ''
  try {
    const nextModelConfig = {
      subdirectory: mediaSelection.subdirectory,
      date_from: mediaSelection.date_from,
      date_to: mediaSelection.date_to,
      location_filter: mediaSelection.location_filter,
      tags_filter: mediaSelection.tags_filter
    }
    await configStore.saveWorkflowConfig({
      model: nextModelConfig
    })
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

const removeSimpleFilterTerm = (expression: string, term: string) => {
  const parsed = parseSimpleFilterExpression(expression)
  if (!parsed.simple) return expression
  const nextParts = parsed.parts.filter((part) => part.term !== term)
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

const selectedLocationTerms = computed(() => {
  const parsed = parseSimpleFilterExpression(mediaSelection.location_filter)
  return parsed.simple ? parsed.parts.map((part) => part.term) : []
})

const selectedTagTerms = computed(() => {
  const parsed = parseSimpleFilterExpression(mediaSelection.tags_filter)
  return parsed.simple ? parsed.parts.map((part) => part.term) : []
})

const useTagSearch = computed(() => filterOptions.value.tags.length > TAG_SEARCH_THRESHOLD)

const visibleTagOptions = computed(() => {
  const tags = filterOptions.value.tags || []
  if (!useTagSearch.value) return tags
  const query = tagSearch.value.trim().toLowerCase()
  if (query.length < 2) return []
  return tags.filter((tag) => tag.toLowerCase().includes(query)).slice(0, 25)
})

const selectedMediaLocation = computed(() => {
  return selectedMediaItem.value?.location
})

const openExpandedPanel = (panel: 'media' | 'map', autoplayVideo = false) => {
  if (panel === 'map' && !selectedMediaLocation.value) return
  expandedVideoAutoplay.value = panel === 'media' && autoplayVideo
  expandedPanel.value = panel
}

const openExpandedVideo = () => {
  openExpandedPanel('media', true)
}

const closeExpandedPanel = () => {
  expandedPanel.value = null
  expandedVideoAutoplay.value = false
}

const toggleMediaOverlay = () => {
  isMediaOverlayPinned.value = !isMediaOverlayPinned.value
}

const updateLocationSearch = async () => {
  const query = locationSearch.value.trim()
  if (query.length < 2) {
    locationSearchResults.value = []
    return
  }
  isLocationSearchLoading.value = true
  try {
    locationSearchResults.value = await configStore.searchLocationOptions(query, 25)
  } catch (error) {
    console.error(error)
    locationSearchResults.value = []
  } finally {
    isLocationSearchLoading.value = false
  }
}

watch(locationSearch, () => {
  if (locationSearchTimer !== undefined) {
    window.clearTimeout(locationSearchTimer)
  }
  locationSearchTimer = window.setTimeout(() => {
    void updateLocationSearch()
  }, 250)
})

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

const mediaInfoTitle = computed(() => {
  return selectedMediaItem.value?.exif?.title || displayFileName.value
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
  <div class="space-y-6">
    <div class="grid grid-cols-1 gap-6 xl:grid-cols-12 xl:items-start">
      
      <!-- Left Column: Media & Controls -->
      <div class="xl:col-span-7 flex flex-col space-y-6">
        
        <!-- Media Player Card -->
        <div class="flex flex-grow flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
          
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
                <template v-if="isVideoMedia(item)">
                  <img
                    v-if="mediaPosterSrc(item) && !hasVideoPosterFailed(item)"
                    :src="mediaPosterSrc(item)"
                    :alt="t('remote.videoPreview')"
                    class="h-full w-full object-contain"
                    @error="handleVideoPosterError(item)"
                  />
                  <div
                    v-else
                    class="flex h-full w-full flex-col items-center justify-center px-4 text-center text-gray-200"
                  >
                    <svg class="mb-2 h-8 w-8 opacity-70" viewBox="0 0 24 24" aria-hidden="true">
                      <path :d="mdiVideo" fill="currentColor" />
                    </svg>
                    <span class="text-xs font-semibold">{{ t('remote.videoPreviewUnavailable') }}</span>
                  </div>
                </template>
                <img
                  v-else
                  :src="mediaImageSrc(item)"
                  :alt="pairSideLabel(index)"
                  class="h-full w-full object-contain"
                  @error="handleMediaImageError(item)"
                />
                <div
                  v-if="!isVideoMedia(item) && hasMediaImageFailed(item)"
                  class="absolute inset-0 flex flex-col items-center justify-center bg-black/70 px-4 text-center text-white"
                >
                  <PhotoIcon class="mb-2 h-8 w-8 opacity-70" />
                  <span class="text-xs font-semibold">{{ t('remote.previewLoadFailed') }}</span>
                </div>
                <span class="absolute left-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-xs font-semibold text-white backdrop-blur-sm">
                  {{ pairSideLabel(index) }}
                </span>
              </button>
            </div>
            <div
              v-else-if="selectedMediaItem?.file_path && isVideoMedia(selectedMediaItem)"
              class="absolute inset-0 flex items-center justify-center bg-black"
            >
              <img
                v-if="mediaPosterSrc(selectedMediaItem) && !hasVideoPosterFailed(selectedMediaItem)"
                :src="mediaPosterSrc(selectedMediaItem)"
                :alt="t('remote.videoPreview')"
                class="absolute inset-0 h-full w-full object-contain transition-transform duration-1000 ease-out group-hover:scale-[1.02]"
                @error="handleVideoPosterError(selectedMediaItem)"
              />
              <div
                v-if="!mediaPosterSrc(selectedMediaItem) || hasVideoPosterFailed(selectedMediaItem)"
                class="flex flex-col items-center justify-center px-6 text-center text-gray-200"
              >
                <svg class="mb-3 h-16 w-16 opacity-70" viewBox="0 0 24 24" aria-hidden="true">
                  <path :d="mdiVideo" fill="currentColor" />
                </svg>
                <p class="text-sm font-semibold">{{ t('remote.videoPreviewUnavailable') }}</p>
              </div>
              <div class="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
                <button
                  type="button"
                  class="pointer-events-auto inline-flex h-20 w-20 items-center justify-center rounded-full border border-white/30 bg-white/90 text-gray-950 shadow-2xl shadow-black/40 transition-transform hover:scale-105 hover:bg-white focus:outline-none focus:ring-4 focus:ring-white/70 active:scale-95"
                  :aria-label="t('remote.playVideo')"
                  :title="t('remote.playVideo')"
                  @click.stop="openExpandedVideo"
                >
                  <PlayIconSolid class="ml-1 h-10 w-10" />
                  <span class="sr-only">{{ t('remote.playVideo') }}</span>
                </button>
              </div>
            </div>
            <img
              v-else-if="selectedMediaItem?.file_path"
              :src="mediaImageSrc(selectedMediaItem)"
              :alt="t('remote.controls.currentMedia')"
              class="absolute inset-0 w-full h-full object-contain transition-transform duration-1000 ease-out group-hover:scale-[1.02]"
              @error="handleMediaImageError(selectedMediaItem)"
            />
            <div v-else class="flex flex-col items-center text-gray-400 dark:text-gray-500">
              <PhotoIcon class="w-24 h-24 mb-4 opacity-20" />
              <p class="text-sm font-medium uppercase tracking-wide opacity-60">{{ t('remote.noMedia') }}</p>
            </div>
            <div
              v-if="selectedMediaItem?.file_path && !isVideoMedia(selectedMediaItem) && hasMediaImageFailed(selectedMediaItem)"
              class="absolute inset-0 z-10 flex flex-col items-center justify-center bg-black/70 px-6 text-center text-white"
            >
              <PhotoIcon class="mb-3 h-12 w-12 opacity-70" />
              <p class="text-sm font-semibold">{{ t('remote.previewLoadFailed') }}</p>
              <button
                type="button"
                class="mt-4 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-gray-900 shadow-sm transition-colors hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-white"
                @click.stop="retryMediaImage(selectedMediaItem)"
              >
                {{ t('remote.retryPreview') }}
              </button>
            </div>
            <div v-if="selectedMediaItem" class="absolute right-4 top-4 z-10 flex items-center gap-2">
              <button
                v-if="currentMediaTags.length"
                type="button"
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg border text-white shadow-sm backdrop-blur-sm transition-colors focus:outline-none focus:ring-2 focus:ring-white/80"
                :class="isMediaOverlayPinned ? 'border-sky-300 bg-sky-600/85' : 'border-white/20 bg-black/55 hover:bg-black/75'"
                :aria-label="isMediaOverlayPinned ? t('remote.hideTags') : t('remote.showTags')"
                :title="isMediaOverlayPinned ? t('remote.hideTags') : t('remote.showTags')"
                :aria-expanded="isMediaOverlayPinned"
                aria-controls="remote-current-media-tags"
                @click.stop="toggleMediaOverlay"
              >
                <TagIcon class="h-5 w-5" />
              </button>
              <InfoButton :label="t('remote.mediaInfo.open')" @click="isMediaInfoOpen = true" />
              <button
                v-if="selectedMediaItem?.file_path"
                type="button"
                class="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-white/20 bg-black/55 text-white shadow-sm backdrop-blur-sm transition-colors hover:bg-black/75 focus:outline-none focus:ring-2 focus:ring-white/80"
                :aria-label="t('remote.expand')"
                :title="t('remote.expand')"
                @click="openExpandedPanel('media')"
              >
                <ArrowsPointingOutIcon class="h-5 w-5" />
              </button>
            </div>
            
            <!-- Adaptive Cinematic Gradient Overlay -->
            <div
              v-if="selectedMediaItem?.file_path"
              class="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent transition-opacity duration-500 pointer-events-none"
              :class="isMediaOverlayPinned ? 'opacity-100' : 'opacity-40 group-hover:opacity-100'"
            ></div>
            
            <!-- Narrative Metadata Overlay (Progressive Disclosure) -->
            <div
              v-if="selectedMediaItem?.file_path"
              class="absolute bottom-0 left-0 right-0 p-6 transition-all duration-500 flex justify-between items-end group-hover:backdrop-blur-sm"
              :class="isMediaOverlayPinned ? 'backdrop-blur-sm' : ''"
            >
              <div class="flex-1 min-w-0 pr-4 pointer-events-none">
                <!-- Title (Always visible) -->
                <h2
                  class="text-2xl font-bold text-white truncate drop-shadow-md transition-transform duration-500 group-hover:-translate-y-1"
                  :class="isMediaOverlayPinned ? '-translate-y-1' : ''"
                >
                  {{ selectedMediaItem?.exif?.title || displayFileName }}
                </h2>
                
                <!-- Progressive Disclosure: Caption & Tags (Visible on hover) -->
                <div
                  id="remote-current-media-tags"
                  class="grid transition-all duration-500 ease-in-out"
                  :class="isMediaOverlayPinned ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0 group-hover:grid-rows-[1fr] group-hover:opacity-100'"
                >
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
                v-if="selectedMediaItem?.file_path"
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

              <div ref="shuffleModeMenuRef" class="relative inline-flex justify-self-center">
                <div
                  :class="[
                    'inline-flex h-12 items-stretch overflow-hidden rounded-full border transition-all focus-within:ring-2 focus-within:ring-indigo-500/50',
                    isShuffleEnabled
                      ? 'border-indigo-100 bg-indigo-50 text-indigo-600 dark:border-indigo-500/20 dark:bg-indigo-500/10 dark:text-indigo-300'
                      : 'border-transparent text-gray-500 dark:text-gray-400',
                    isSavingShuffle || isConfigLoading ? 'opacity-60 cursor-wait' : ''
                  ]"
                >
                  <button
                    type="button"
                    @click="toggleShuffle"
                    :disabled="isSavingShuffle || isConfigLoading"
                    :aria-pressed="isShuffleEnabled"
                    :aria-label="shuffleTitle"
                    :title="shuffleTitle"
                    :class="[
                      'inline-flex h-12 w-12 items-center justify-center transition-all focus:outline-none active:scale-95',
                      isShuffleEnabled
                        ? 'hover:bg-indigo-100 dark:hover:bg-indigo-500/20'
                        : 'hover:bg-gray-100 hover:text-indigo-600 dark:hover:bg-gray-700/50 dark:hover:text-indigo-400'
                    ]"
                  >
                    <svg class="w-6 h-6" viewBox="0 0 24 24" aria-hidden="true">
                      <path :d="mdiShuffleVariant" fill="currentColor" />
                    </svg>
                    <span class="sr-only">{{ shuffleTitle }}</span>
                  </button>
                  <button
                    type="button"
                    @click.stop="toggleShuffleModeMenu"
                    :disabled="isSavingShuffle || isConfigLoading"
                    :aria-label="shuffleModeTitle"
                    :title="shuffleModeTitle"
                    aria-haspopup="menu"
                    :aria-expanded="isShuffleModeMenuOpen"
                    :class="[
                      'inline-flex h-12 w-8 items-center justify-center border-l transition-all focus:outline-none active:scale-95',
                      isShuffleEnabled
                        ? 'border-indigo-200/70 hover:bg-indigo-100 dark:border-indigo-500/20 dark:hover:bg-indigo-500/20'
                        : 'border-gray-200 hover:bg-gray-100 hover:text-indigo-600 dark:border-gray-700 dark:hover:bg-gray-700/50 dark:hover:text-indigo-400'
                    ]"
                  >
                    <ChevronDownIcon :class="['h-4 w-4 transition-transform', isShuffleModeMenuOpen ? 'rotate-180' : '']" />
                    <span class="sr-only">{{ shuffleModeTitle }}</span>
                  </button>
                </div>
                <div
                  v-if="isShuffleModeMenuOpen"
                  class="absolute bottom-full right-0 mb-2 z-30 w-44 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-xl dark:border-gray-700 dark:bg-gray-800"
                  role="menu"
                  :aria-label="t('remote.controls.shuffleMode')"
                >
                  <button
                    v-for="mode in shuffleModes"
                    :key="mode.value"
                    type="button"
                    role="menuitemradio"
                    :aria-checked="shuffleMode === mode.value"
                    @click="setShuffleMode(mode.value)"
                    class="flex h-10 w-full items-center gap-2 px-3 text-left text-sm font-medium text-gray-700 transition-colors hover:bg-indigo-50 hover:text-indigo-700 focus:bg-indigo-50 focus:text-indigo-700 focus:outline-none dark:text-gray-200 dark:hover:bg-indigo-500/10 dark:hover:text-indigo-200 dark:focus:bg-indigo-500/10 dark:focus:text-indigo-200"
                  >
                    <CheckIcon :class="['h-4 w-4 flex-shrink-0', shuffleMode === mode.value ? 'opacity-100' : 'opacity-0']" />
                    <span class="truncate">{{ t(mode.labelKey) }}</span>
                  </button>
                </div>
              </div>
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
                  @input="handleBrightnessPreview"
                  @change="handleBrightnessCommit"
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
          show-expand
          @expand="openExpandedPanel('map')"
        />
      </div>

      <!-- Right Column: Metadata & Controls -->
      <div class="xl:col-span-5 flex flex-col space-y-6">

        <!-- Media Selection Card -->
        <div class="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800">
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
              <div class="space-y-3">
                <label class="space-y-2 block">
                  <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    <MapPinIcon class="w-4 h-4" />
                    {{ t('remote.mediaSelection.location') }}
                    <HelperText :text="filterHelpText" mode="dialog" />
                  </span>
                  <textarea
                    v-model="mediaSelection.location_filter"
                    rows="2"
                    class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                  ></textarea>
                </label>
                <div v-if="selectedLocationTerms.length" class="flex flex-wrap gap-2">
                  <button
                    v-for="location in selectedLocationTerms"
                    :key="location"
                    type="button"
                    class="inline-flex items-center gap-1 rounded-full border border-sky-600 bg-sky-600 px-2.5 py-1 text-xs font-semibold text-white transition-colors hover:bg-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                    :title="t('remote.mediaSelection.removeLocation')"
                    @click="mediaSelection.location_filter = removeSimpleFilterTerm(mediaSelection.location_filter, location)"
                  >
                    {{ location }}
                    <XMarkIcon class="h-3.5 w-3.5" />
                  </button>
                </div>
                <label class="relative block">
                  <MagnifyingGlassIcon class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    v-model="locationSearch"
                    type="search"
                    :placeholder="t('remote.mediaSelection.searchLocations')"
                    class="w-full rounded-xl border border-gray-200 bg-white py-2.5 pl-9 pr-3 text-sm font-medium text-gray-900 focus:outline-none focus:ring-2 focus:ring-sky-500/50 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-100"
                  >
                </label>
                <div class="min-h-8">
                  <p v-if="locationSearch.trim().length > 0 && locationSearch.trim().length < 2" class="text-xs text-gray-500 dark:text-gray-400">
                    {{ t('remote.mediaSelection.searchMore') }}
                  </p>
                  <p v-else-if="isLocationSearchLoading" class="text-xs text-gray-500 dark:text-gray-400">
                    {{ t('remote.mediaSelection.searching') }}
                  </p>
                  <div v-else-if="locationSearchResults.length" class="flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1 custom-scrollbar">
                    <button
                      v-for="location in locationSearchResults"
                      :key="location.value"
                      type="button"
                      :aria-pressed="filterContainsTerm(mediaSelection.location_filter, quoteFilterTerm(location.value))"
                      :title="t('remote.mediaSelection.chipTitle')"
                      @click="setLocationFilter(location.value, $event)"
                      :class="[
                        'px-2.5 py-1 rounded-full text-xs font-semibold transition-colors border',
                        filterContainsTerm(mediaSelection.location_filter, quoteFilterTerm(location.value))
                          ? 'bg-sky-600 text-white border-sky-600'
                          : 'bg-white dark:bg-gray-900/50 text-gray-600 dark:text-gray-300 border-gray-200 dark:border-gray-700 hover:border-sky-400'
                      ]"
                    >
                      {{ location.value }}
                      <span class="ml-1 opacity-70">{{ formatCount(location.count) }}</span>
                    </button>
                  </div>
                </div>
              </div>

              <div class="space-y-3">
                <label class="space-y-2 block">
                  <span class="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    <TagIcon class="w-4 h-4" />
                    {{ t('remote.mediaSelection.tags') }}
                    <HelperText :text="filterHelpText" mode="dialog" />
                  </span>
                  <textarea
                    v-model="mediaSelection.tags_filter"
                    rows="2"
                    class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 px-3 py-2.5 text-sm font-medium text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                  ></textarea>
                </label>
                <div v-if="selectedTagTerms.length" class="flex flex-wrap gap-2">
                  <button
                    v-for="tag in selectedTagTerms"
                    :key="tag"
                    type="button"
                    class="inline-flex items-center gap-1 rounded-full border border-sky-600 bg-sky-600 px-2.5 py-1 text-xs font-semibold text-white transition-colors hover:bg-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                    :title="t('remote.mediaSelection.removeTag')"
                    @click="mediaSelection.tags_filter = removeSimpleFilterTerm(mediaSelection.tags_filter, tag)"
                  >
                    {{ tag }}
                    <XMarkIcon class="h-3.5 w-3.5" />
                  </button>
                </div>
                <label v-if="useTagSearch" class="relative block">
                  <MagnifyingGlassIcon class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                  <input
                    v-model="tagSearch"
                    type="search"
                    :placeholder="t('remote.mediaSelection.searchTags')"
                    class="w-full rounded-xl border border-gray-200 bg-white py-2.5 pl-9 pr-3 text-sm font-medium text-gray-900 focus:outline-none focus:ring-2 focus:ring-sky-500/50 dark:border-gray-700 dark:bg-gray-900/50 dark:text-gray-100"
                  >
                </label>
                <div v-if="visibleTagOptions.length" class="flex max-h-32 flex-wrap gap-2 overflow-y-auto pr-1 custom-scrollbar">
                  <button
                    v-for="tag in visibleTagOptions"
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

            <StatusBanner
              v-if="configError"
              tone="danger"
              :title="t('remote.mediaSelection.unavailableTitle')"
              :message="t('remote.mediaSelection.unavailable')"
            />
            <StatusBanner
              v-else-if="selectionMessage"
              :tone="selectionMessage === t('remote.mediaSelection.failed') ? 'danger' : 'success'"
              :message="selectionMessage"
            />
          </div>
        </div>

      </div>
    </div>

    <MediaInfoSheet
      :open="isMediaInfoOpen"
      :title="mediaInfoTitle"
      :file-name="displayFileName"
      :caption="selectedMediaItem?.exif?.caption"
      :location-name="selectedMediaItem?.exif?.location_name"
      :tags="currentMediaTags"
      :fields="metadataFields"
      @close="isMediaInfoOpen = false"
    />

    <div
      v-if="expandedPanel"
      class="fixed inset-0 z-50 flex flex-col bg-gray-950/90 p-3 backdrop-blur-sm sm:p-4"
      role="dialog"
      aria-modal="true"
      :aria-label="expandedPanel === 'map' ? t('remote.location') : t('remote.controls.currentMedia')"
      @click.self="closeExpandedPanel"
    >
      <div class="relative z-[10000] mb-3 flex h-12 shrink-0 justify-end">
        <button
          type="button"
          class="inline-flex h-12 min-w-12 items-center justify-center gap-2 rounded-full border-2 border-white bg-red-600 px-4 text-white shadow-2xl ring-4 ring-black/30 transition-colors hover:bg-red-500 focus:outline-none focus:ring-4 focus:ring-red-300"
          :aria-label="t('common.close')"
          :title="t('common.close')"
          @click.stop="closeExpandedPanel"
        >
          <XMarkIcon class="h-6 w-6" />
          <span class="pr-1 text-sm font-bold">{{ t('common.close') }}</span>
        </button>
      </div>

      <div v-if="expandedPanel === 'media'" class="min-h-0 flex-1 w-full">
        <div v-if="isPortraitPair" class="grid h-full w-full grid-cols-1 gap-3 md:grid-cols-2">
          <figure
            v-for="(item, index) in currentMediaItems.slice(0, 2)"
            :key="item.id ?? item.file_path"
            class="relative flex min-h-0 items-center justify-center overflow-hidden rounded-xl bg-black/50"
          >
            <template v-if="isVideoMedia(item)">
              <img
                v-if="mediaPosterSrc(item) && !hasVideoPosterFailed(item)"
                :src="mediaPosterSrc(item)"
                :alt="t('remote.videoPreview')"
                class="max-h-full max-w-full object-contain"
                @error="handleVideoPosterError(item)"
              />
              <div
                v-else
                class="flex h-full w-full flex-col items-center justify-center px-4 text-center text-gray-200"
              >
                <svg class="mb-2 h-10 w-10 opacity-70" viewBox="0 0 24 24" aria-hidden="true">
                  <path :d="mdiVideo" fill="currentColor" />
                </svg>
                <span class="text-xs font-semibold">{{ t('remote.videoPreviewUnavailable') }}</span>
              </div>
            </template>
            <img
              v-else
              :src="mediaImageSrc(item)"
              :alt="pairSideLabel(index)"
              class="max-h-full max-w-full object-contain"
              @error="handleMediaImageError(item)"
            />
            <div
              v-if="!isVideoMedia(item) && hasMediaImageFailed(item)"
              class="absolute inset-0 flex flex-col items-center justify-center bg-black/70 px-4 text-center text-white"
            >
              <PhotoIcon class="mb-2 h-8 w-8 opacity-70" />
              <span class="text-xs font-semibold">{{ t('remote.previewLoadFailed') }}</span>
              <button
                type="button"
                class="mt-3 rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-gray-900 shadow-sm transition-colors hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-white"
                @click.stop="retryMediaImage(item)"
              >
                {{ t('remote.retryPreview') }}
              </button>
            </div>
            <figcaption class="absolute left-4 top-4 rounded-full bg-black/60 px-3 py-1 text-sm font-semibold text-white backdrop-blur-sm">
              {{ pairSideLabel(index) }}
            </figcaption>
          </figure>
        </div>
        <div v-else class="relative flex h-full w-full items-center justify-center">
          <video
            v-if="selectedMediaItem?.file_path && isVideoMedia(selectedMediaItem)"
            :src="mediaVideoSrc(selectedMediaItem)"
            :poster="mediaPosterSrc(selectedMediaItem)"
            :aria-label="displayFileName"
            :autoplay="expandedVideoAutoplay"
            class="max-h-full max-w-full"
            controls
            playsinline
            preload="metadata"
          />
          <img
            v-else-if="selectedMediaItem?.file_path"
            :src="mediaImageSrc(selectedMediaItem)"
            :alt="displayFileName"
            class="max-h-full max-w-full object-contain"
            @error="handleMediaImageError(selectedMediaItem)"
          />
          <div
            v-if="selectedMediaItem?.file_path && !isVideoMedia(selectedMediaItem) && hasMediaImageFailed(selectedMediaItem)"
            class="absolute inset-0 flex flex-col items-center justify-center bg-black/70 px-6 text-center text-white"
          >
            <PhotoIcon class="mb-3 h-12 w-12 opacity-70" />
            <p class="text-sm font-semibold">{{ t('remote.previewLoadFailed') }}</p>
            <button
              type="button"
              class="mt-4 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-gray-900 shadow-sm transition-colors hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-white"
              @click.stop="retryMediaImage(selectedMediaItem)"
            >
              {{ t('remote.retryPreview') }}
            </button>
          </div>
        </div>
      </div>

      <div v-else-if="expandedPanel === 'map'" class="min-h-0 flex-1 w-full overflow-hidden rounded-xl bg-white dark:bg-gray-800">
        <MapComponent
          :latitude="selectedMediaItem?.location?.lat"
          :longitude="selectedMediaItem?.location?.lon"
          :location-name="selectedMediaItem?.exif?.location_name"
          expanded
        />
      </div>
    </div>

    <AppDialog
      :open="showPairDeleteDialog"
      :title="t('remote.pair.deleteTitle')"
      :description="t('remote.pair.deletePrompt')"
      max-width="lg"
      @close="showPairDeleteDialog = false"
    >
        <div class="mt-5 grid grid-cols-2 gap-3">
          <div
            v-for="(item, index) in currentMediaItems.slice(0, 2)"
            :key="item.id ?? item.file_path"
            class="overflow-hidden rounded-xl border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900/50"
          >
            <div class="aspect-video bg-black/80">
              <template v-if="isVideoMedia(item)">
                <img
                  v-if="mediaPosterSrc(item) && !hasVideoPosterFailed(item)"
                  :src="mediaPosterSrc(item)"
                  :alt="t('remote.videoPreview')"
                  class="h-full w-full object-contain"
                  @error="handleVideoPosterError(item)"
                />
                <div
                  v-else
                  class="flex h-full w-full flex-col items-center justify-center px-3 text-center text-gray-200"
                >
                  <svg class="mb-2 h-8 w-8 opacity-70" viewBox="0 0 24 24" aria-hidden="true">
                    <path :d="mdiVideo" fill="currentColor" />
                  </svg>
                  <span class="text-xs font-semibold">{{ t('remote.videoPreviewUnavailable') }}</span>
                </div>
              </template>
              <img
                v-else
                :src="mediaImageSrc(item)"
                :alt="pairSideLabel(index)"
                class="h-full w-full object-contain"
                @error="handleMediaImageError(item)"
              />
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
    </AppDialog>
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
