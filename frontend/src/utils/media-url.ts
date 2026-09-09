/**
 * Rewrite backend file paths into browser-loadable media URLs.
 *
 * Extracted from `stores/player.ts` (#769) so the DEV/PROD URL-rewriting logic
 * is unit-testable without activating a Pinia store or mocking a WebSocket.
 * The store imports `normalizeMediaUrls` for its `MediaChangedEvent` handler.
 */

import type { MediaItem } from '../stores/player'

/**
 * Rewrite a single file path into a URL the browser can `<img>`/`<video>` load.
 *
 * - Absolute HTTP(S) URLs and already-normalized `/media?path=` URLs pass
 *   through unchanged.
 * - Bare backend paths are rewritten to `/media?path=<encoded>` served by the
 *   FastAPI backend. In development the backend runs on port 9000; in
 *   production the request goes to the same host/port as the SPA.
 */
export function normalizeMediaUrl(path: string): string {
  if (!path || path.startsWith('http') || path.startsWith('/media?path=')) {
    return path
  }

  const port = import.meta.env.DEV
    ? '9000'
    : window.location.port || (window.location.protocol === 'https:' ? '443' : '80')
  const host = window.location.hostname
  const protocol = window.location.protocol
  const mediaUrl = `/media?path=${encodeURIComponent(path)}`

  if (import.meta.env.DEV) {
    return `http://${host}:9000${mediaUrl}`
  }
  return `${protocol}//${host}${port ? ':' + port : ''}${mediaUrl}`
}

/**
 * Recursively normalize `file_path` on a media item and its nested `items[]`
 * (e.g. portrait-pair layouts). Returns a shallow-copied object so the
 * original WebSocket payload is not mutated.
 */
export function normalizeMediaUrls(media: MediaItem): MediaItem {
  const normalized = { ...media }
  normalized.file_path = normalizeMediaUrl(normalized.file_path)
  if (Array.isArray(normalized.items)) {
    normalized.items = normalized.items.map(item => normalizeMediaUrls(item))
  }
  return normalized
}
