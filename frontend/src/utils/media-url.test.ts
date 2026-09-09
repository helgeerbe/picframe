import { describe, it, expect, vi, afterEach } from 'vitest'
import { normalizeMediaUrl, normalizeMediaUrls } from './media-url'
import type { MediaItem } from '../stores/player'

const originalDev = import.meta.env.DEV

afterEach(() => {
  // Restore DEV flag between tests
  ;(import.meta.env as Record<string, unknown>).DEV = originalDev
})

describe('normalizeMediaUrl — passthrough', () => {
  it('passes through http URLs unchanged', () => {
    expect(normalizeMediaUrl('http://example.com/img.jpg')).toBe('http://example.com/img.jpg')
  })

  it('passes through https URLs unchanged', () => {
    expect(normalizeMediaUrl('https://cdn.example.com/video.mp4')).toBe(
      'https://cdn.example.com/video.mp4'
    )
  })

  it('passes through already-normalized /media?path= URLs', () => {
    expect(normalizeMediaUrl('/media?path=foo%2Fbar.jpg')).toBe('/media?path=foo%2Fbar.jpg')
  })

  it('passes through empty string', () => {
    expect(normalizeMediaUrl('')).toBe('')
  })
})

describe('normalizeMediaUrl — DEV mode', () => {
  // import.meta.env.DEV is true by default in Vitest

  it('rewrites a bare path to http://hostname:9000/media?path=<encoded>', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = true
    const result = normalizeMediaUrl('photos/img.jpg')
    // happy-dom default hostname is 'localhost'
    expect(result).toBe('http://localhost:9000/media?path=photos%2Fimg.jpg')
  })

  it('applies encodeURIComponent to the path', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = true
    const result = normalizeMediaUrl('my photos/special file.jpg')
    expect(result).toContain('my%20photos%2Fspecial%20file.jpg')
  })
})

describe('normalizeMediaUrl — PROD mode', () => {
  it('rewrites a bare path using window.location host/port/protocol', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = false
    const mockLocation = {
      hostname: 'picframe.local',
      port: '8080',
      protocol: 'http:',
      host: 'picframe.local:8080'
    }
    vi.stubGlobal('location', mockLocation)
    try {
      const result = normalizeMediaUrl('photos/img.jpg')
      expect(result).toBe('http://picframe.local:8080/media?path=photos%2Fimg.jpg')
    } finally {
      vi.unstubAllGlobals()
    }
  })
})

describe('normalizeMediaUrls', () => {
  it('normalizes file_path on a flat media item', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = true
    const media: MediaItem = { file_path: 'photos/img.jpg' }
    const result = normalizeMediaUrls(media)
    expect(result.file_path).toBe('http://localhost:9000/media?path=photos%2Fimg.jpg')
  })

  it('recursively normalizes nested items[]', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = true
    const media: MediaItem = {
      file_path: 'main.jpg',
      items: [{ file_path: 'left.jpg' }, { file_path: 'right.jpg' }]
    }
    const result = normalizeMediaUrls(media)
    expect(result.file_path).toBe('http://localhost:9000/media?path=main.jpg')
    expect(result.items?.[0].file_path).toBe('http://localhost:9000/media?path=left.jpg')
    expect(result.items?.[1].file_path).toBe('http://localhost:9000/media?path=right.jpg')
  })

  it('does not mutate the original media object', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = true
    const media: MediaItem = { file_path: 'photos/img.jpg' }
    normalizeMediaUrls(media)
    expect(media.file_path).toBe('photos/img.jpg')
  })

  it('handles items with nested items (portrait-pair of portrait-pairs)', () => {
    ;(import.meta.env as Record<string, unknown>).DEV = true
    const media: MediaItem = {
      file_path: 'outer.jpg',
      items: [{ file_path: 'inner.jpg', items: [{ file_path: 'deep.jpg' }] }]
    }
    const result = normalizeMediaUrls(media)
    expect(result.items?.[0].items?.[0].file_path).toBe('http://localhost:9000/media?path=deep.jpg')
  })
})
