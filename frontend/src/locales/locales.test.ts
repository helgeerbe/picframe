import { describe, it, expect } from 'vitest'
import en from './en.json'
import de from './de.json'

type JsonDict = Record<string, unknown>

function isDict(value: unknown): value is JsonDict {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

/** Collect every leaf key path (e.g. "common.ok") from a nested JSON object. */
function collectKeys(obj: JsonDict, prefix = ''): string[] {
  const keys: string[] = []
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key
    if (isDict(value)) {
      keys.push(...collectKeys(value, fullKey))
    } else {
      keys.push(fullKey)
    }
  }
  return keys.sort()
}

/** Collect key paths that have a null/undefined value (missing translations). */
function collectNulls(obj: JsonDict, prefix = ''): string[] {
  const nulls: string[] = []
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key
    if (isDict(value)) {
      nulls.push(...collectNulls(value, fullKey))
    } else if (value === null || value === undefined) {
      nulls.push(fullKey)
    }
  }
  return nulls.sort()
}

describe('locale parity (en.json ↔ de.json)', () => {
  it('has the same top-level keys', () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(de).sort())
  })

  it('has the same recursive key set', () => {
    const enKeys = collectKeys(en as JsonDict)
    const deKeys = collectKeys(de as JsonDict)
    expect(deKeys).toEqual(enKeys)
  })

  it('en.json has no null/undefined values', () => {
    expect(collectNulls(en as JsonDict)).toEqual([])
  })

  it('de.json has no null/undefined values', () => {
    expect(collectNulls(de as JsonDict)).toEqual([])
  })
})
