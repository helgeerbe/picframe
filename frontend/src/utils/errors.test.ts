import { describe, it, expect } from 'vitest'
import { getErrorMessage, getApiErrorMessage } from './errors'

describe('getErrorMessage', () => {
  it('returns the .message of an Error', () => {
    expect(getErrorMessage(new Error('boom'), 'fallback')).toBe('boom')
  })

  it('falls back when the Error has an empty message', () => {
    expect(getErrorMessage(new Error(''), 'fallback')).toBe('fallback')
  })

  it('extracts .message from a plain object with a string message', () => {
    const obj = { message: 'something broke' }
    expect(getErrorMessage(obj, 'fallback')).toBe('something broke')
  })

  it('falls back when the plain object has an empty message', () => {
    expect(getErrorMessage({ message: '' }, 'fallback')).toBe('fallback')
  })

  it('falls back when the plain object has a non-string message', () => {
    expect(getErrorMessage({ message: 42 }, 'fallback')).toBe('fallback')
  })

  it('falls back for null', () => {
    expect(getErrorMessage(null, 'fallback')).toBe('fallback')
  })

  it('falls back for undefined', () => {
    expect(getErrorMessage(undefined, 'fallback')).toBe('fallback')
  })

  it('falls back for a primitive string', () => {
    expect(getErrorMessage('oops', 'fallback')).toBe('fallback')
  })

  it('falls back for a primitive number', () => {
    expect(getErrorMessage(42, 'fallback')).toBe('fallback')
  })
})

describe('getApiErrorMessage', () => {
  it('prefers response.data.detail (Axios-style)', () => {
    const err = { response: { data: { detail: 'Not found' } }, message: 'Request failed' }
    expect(getApiErrorMessage(err, 'fallback')).toBe('Not found')
  })

  it('uses .message when no response.data.detail', () => {
    const err = { message: 'Network error' }
    expect(getApiErrorMessage(err, 'fallback')).toBe('Network error')
  })

  it('uses .message when response.data.detail is empty', () => {
    const err = { response: { data: { detail: '' } }, message: 'Fallback msg' }
    expect(getApiErrorMessage(err, 'fallback')).toBe('Fallback msg')
  })

  it('returns the thrown string', () => {
    expect(getApiErrorMessage('something went wrong', 'fallback')).toBe('something went wrong')
  })

  it('falls back for null', () => {
    expect(getApiErrorMessage(null, 'fallback')).toBe('fallback')
  })

  it('falls back for undefined', () => {
    expect(getApiErrorMessage(undefined, 'fallback')).toBe('fallback')
  })

  it('falls back for a number', () => {
    expect(getApiErrorMessage(42, 'fallback')).toBe('fallback')
  })
})
