import { type Ref } from 'vue'

/**
 * Coalesces trailing invocations of an async save so a second call made while
 * the first is in flight is not dropped — it is re-sent once the first settles.
 *
 * Used by overlay auto-save controls (#777) to keep the UI working copy and the
 * persisted config consistent: without coalescing, a rapid add/remove during a
 * single network round-trip would drop the trailing edit, leaving the local
 * snapshot ahead of the backend until the next refresh silently reverted it.
 *
 * Accepts an external `isSaving` ref so a component that guards several saves
 * with one shared flag (mutual exclusion + a shared "saving" button state) can
 * coalesce each independently while still serializing them against each other.
 *
 * @param save The async save function. It MUST read its inputs at call time
 *   (e.g. from a reactive) so the trailing re-send observes the latest snapshot
 *   rather than a stale closure capture.
 * @param isSaving Shared busy flag — set true while a save is in flight.
 * @returns `{ run }` — kicks off (or defers) a save.
 */
export function useCoalescedSave(save: () => Promise<void>, isSaving: Ref<boolean>) {
  let pending = false

  async function run(): Promise<void> {
    if (isSaving.value) {
      pending = true
      return
    }
    isSaving.value = true
    try {
      await save()
    } finally {
      isSaving.value = false
      if (pending) {
        pending = false
        void run()
      }
    }
  }

  return { run }
}
