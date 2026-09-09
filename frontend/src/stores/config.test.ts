import { describe, it, expect } from 'vitest'
import { mergeConfig } from './config'

describe('mergeConfig', () => {
  it('deep-merges nested plain objects', () => {
    const base = { a: { b: 1, c: 2 } }
    const patch = { a: { c: 3, d: 4 } }
    expect(mergeConfig(base, patch)).toEqual({ a: { b: 1, c: 3, d: 4 } })
  })

  it('deep-merges three levels deep', () => {
    const base = { a: { b: { c: 1 } } }
    const patch = { a: { b: { d: 2 } } }
    expect(mergeConfig(base, patch)).toEqual({ a: { b: { c: 1, d: 2 } } })
  })

  it('replaces arrays instead of merging them', () => {
    const base = { list: [1, 2, 3] }
    const patch = { list: [4] }
    expect(mergeConfig(base, patch)).toEqual({ list: [4] })
  })

  it('replaces a primitive with null', () => {
    expect(mergeConfig({ x: 1 }, { x: null })).toEqual({ x: null })
  })

  it('replaces a primitive with another primitive', () => {
    expect(mergeConfig({ x: 1 }, { x: 42 })).toEqual({ x: 42 })
  })

  it('replaces a nested plain object with a primitive', () => {
    expect(mergeConfig({ a: { b: 1 } }, { a: 42 })).toEqual({ a: 42 })
  })

  it('adds new keys from the patch', () => {
    expect(mergeConfig({ a: 1 }, { b: 2 })).toEqual({ a: 1, b: 2 })
  })

  it('does not mutate the base object', () => {
    const base = { a: { b: 1 } }
    mergeConfig(base, { a: { c: 2 } })
    expect(base).toEqual({ a: { b: 1 } })
  })

  it('empty patch returns a shallow copy of base', () => {
    const base = { a: 1, b: 2 }
    const result = mergeConfig(base, {})
    expect(result).toEqual({ a: 1, b: 2 })
    expect(result).not.toBe(base)
  })

  it('null patch value replaces a nested plain object', () => {
    expect(mergeConfig({ a: { b: 1 } }, { a: null })).toEqual({ a: null })
  })

  it('treats Date as a plain object (no own enumerable keys, base preserved)', () => {
    // isPlainObject(Date) is true, so mergeConfig recurses, but
    // Object.entries(new Date()) is [], so the base value is kept.
    const base = { date: { old: true } }
    const date = new Date(2024, 0, 1)
    const result = mergeConfig(base, { date })
    expect(result.date).toEqual({ old: true })
  })

  it('replaces undefined base with a Date (base not a plain object)', () => {
    const date = new Date(2024, 0, 1)
    const result = mergeConfig({}, { date })
    expect(result.date).toBe(date)
  })
})
