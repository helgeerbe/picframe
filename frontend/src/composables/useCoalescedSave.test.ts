import { describe, it, expect, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useCoalescedSave } from './useCoalescedSave'

/** A controllable save: each invocation gets its own deferred controller in
 *  `defs`, so a test can hold one save in flight, resolve/reject it, then drive
 *  a trailing re-send — mirroring a network round-trip without unhandled
 *  rejections. */
function controlledSave() {
  const defs: Array<{ resolve: () => void; reject: (e: unknown) => void }> = []
  const spy = vi.fn(
    () =>
      new Promise<void>((resolve, reject) => {
        defs.push({ resolve, reject })
      })
  )
  return { spy, defs }
}

function makeHarness(spy: ReturnType<typeof vi.fn>) {
  const isSaving = ref(false)
  const { run } = useCoalescedSave(spy as () => Promise<void>, isSaving)
  return { isSaving, run }
}

describe('useCoalescedSave', () => {
  it('runs the save once and toggles the shared isSaving', async () => {
    const { spy, defs } = controlledSave()
    const { isSaving, run } = makeHarness(spy)

    expect(isSaving.value).toBe(false)
    const p = run()
    expect(spy).toHaveBeenCalledTimes(1)
    expect(isSaving.value).toBe(true)

    defs[0]!.resolve()
    await p
    expect(isSaving.value).toBe(false)
  })

  it('coalesces a trailing call: the second save re-sends with the latest snapshot', async () => {
    const { spy, defs } = controlledSave()
    const { isSaving, run } = makeHarness(spy)

    const first = run() // in flight
    expect(spy).toHaveBeenCalledTimes(1)
    expect(isSaving.value).toBe(true)

    // Second call during flight — must NOT call save yet; it is deferred.
    const second = run()
    expect(spy).toHaveBeenCalledTimes(1)

    defs[0]!.resolve() // first save resolves → trailing re-send fires
    await first
    expect(spy).toHaveBeenCalledTimes(2)

    defs[1]!.resolve() // trailing save resolves
    await second
    expect(isSaving.value).toBe(false)
  })

  it('collapses many rapid calls into a single trailing re-send', async () => {
    const { spy, defs } = controlledSave()
    const { run } = makeHarness(spy)

    const first = run()
    run()
    run()
    run() // three more while in flight
    expect(spy).toHaveBeenCalledTimes(1)

    defs[0]!.resolve()
    await first
    await nextTick()
    // Exactly one trailing re-send, not three.
    expect(spy).toHaveBeenCalledTimes(2)

    defs[1]!.resolve()
    await nextTick()
  })

  it('resets isSaving and still re-sends after a save rejects', async () => {
    const { spy, defs } = controlledSave()
    const { isSaving, run } = makeHarness(spy)

    const first = run()
    run() // trailing, queued while first is in flight
    expect(isSaving.value).toBe(true)
    expect(spy).toHaveBeenCalledTimes(1)

    defs[0]!.reject(new Error('boom')) // first rejects
    await expect(first).rejects.toThrow('boom')
    // isSaving flips false, then the trailing run starts and flips it true again.
    await nextTick()
    expect(isSaving.value).toBe(true)
    expect(spy).toHaveBeenCalledTimes(2)

    defs[1]!.resolve() // trailing succeeds
    await nextTick()
    expect(isSaving.value).toBe(false)
  })

  it('does not re-send when no trailing call arrived', async () => {
    const { spy, defs } = controlledSave()
    const { run } = makeHarness(spy)

    const first = run()
    expect(spy).toHaveBeenCalledTimes(1)
    defs[0]!.resolve()
    await first
    await nextTick()
    expect(spy).toHaveBeenCalledTimes(1)
  })
})
