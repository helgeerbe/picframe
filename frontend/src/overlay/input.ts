/**
 * Pointer + keyboard input routing for the overlay shell (#739, item 11; #777).
 *
 * The shell installs a transparent full-screen "input veil" that captures
 * `pointerdown` (unified mouse/touch/pen) and `keydown`. A pointer tap only
 * wakes the shell (resets the idle timers and re-reveals content); navigation
 * is provided by the dock transport buttons and keyboard actions (#763).
 *
 * Keyboard routing (#777):
 * - `Escape` is **fixed**: it hides the dock (closing an open dropdown first).
 *   It is not user-assignable and fires regardless of `key_bindings`.
 * - `Tab`/`Shift+Tab`, `Enter`, `Space` are **reserved**: the router returns
 *   immediately and never calls `preventDefault`, so the browser handles native
 *   focus movement and `<button>` activation. This removes the old
 *   `Enter`/`Space` → `toggle` collision that shadowed focused dock buttons.
 * - Everything else is looked up in the configurable `key_bindings` map
 *   (`prev`/`next`/`toggle`, each a list of `KeyboardEvent.key` strings).
 *
 * Only the input device classes enabled in `overlay.enabled_input_types` are
 * honoured; a pen is treated as touch.
 *
 * An idle timer fades the *content* (dock + visible plugin) to opacity 0 after
 * `idle_hide_seconds` (auto_hide mode only); any enabled event resets the timer
 * and re-reveals the content. The veil itself never fades, so a wake tap always
 * lands. The GTK surface opacity (driven by the worker for video reveal) is a
 * separate layer and is not touched here.
 */

import type { InputAction, InputType, KeyBindings } from './types'

export interface InputRouterOptions {
  /** Element that captures the events (the transparent veil). */
  root: HTMLElement
  enabledTypes: InputType[]
  onAction: (action: InputAction) => void
  /** Hide the dock: close an open dropdown first, else hide the dock content
   * (#777). Wired by the shell; `Escape` always fires this regardless of
   * `key_bindings`. */
  onHide: () => void
  /** Called for every enabled event, to reset the idle timer / wake content.
   * Carries the originating `InputType` so the shell can wake dock-only for
   * mouse (matching `onMouseMove`) but fully for touch/keyboard (#766). */
  onActivity: (source: InputType) => void
}

const POINTER_TYPE_MAP: Record<string, InputType> = {
  mouse: 'mouse',
  touch: 'touch',
  pen: 'touch'
}

/** Default key bindings when the shell config omits `key_bindings` (#777).
 * Matches `default_config.yaml`. `toggle` defaults to `p` (moved off
 * `Enter`/`Space` so native `<button>` activation always wins). */
const DEFAULT_KEY_BINDINGS: Required<KeyBindings> = {
  prev: ['ArrowLeft'],
  next: ['ArrowRight'],
  toggle: ['p']
}

/** Reserved keys the router never rebinds (#777): navigation, activation, and
 * dismiss. `Escape` is handled as a fixed hide; the others are passed straight
 * to the browser. Kept as a set so a hand-edited `config.db3` that lists them in
 * `key_bindings` is still ignored (defense in depth). */
const RESERVED_KEYS = new Set(['Tab', 'Enter', ' ', 'Escape'])

/** Normalize a `KeyboardEvent.key` for matching: single letters lowercased so
 * `P`/`p` match; named keys (ArrowLeft, F5, ...) returned verbatim. */
function normalizeKey(key: string): string {
  return key.length === 1 ? key.toLowerCase() : key
}

export class InputRouter {
  private readonly root: HTMLElement
  private enabledTypes: InputType[]
  private readonly onAction: (action: InputAction) => void
  private readonly onHide: () => void
  private readonly onActivity: (source: InputType) => void
  /** Reverse lookup: normalized key -> action. Rebuilt on `setKeyBindings`. */
  private keyToAction = new Map<string, InputAction>()
  private boundPointer: (e: PointerEvent) => void
  private boundKey: (e: KeyboardEvent) => void
  private boundContext: (e: Event) => void

  constructor(opts: InputRouterOptions) {
    this.root = opts.root
    this.enabledTypes = [...opts.enabledTypes]
    this.onAction = opts.onAction
    this.onHide = opts.onHide
    this.onActivity = opts.onActivity
    this.setKeyBindings({})
    this.boundPointer = this.handlePointer.bind(this)
    this.boundKey = this.handleKey.bind(this)
    this.boundContext = (e: Event) => e.preventDefault()
  }

  attach(): void {
    this.root.addEventListener('pointerdown', this.boundPointer)
    window.addEventListener('keydown', this.boundKey)
    // Suppress the long-press context menu on touch kiosks.
    this.root.addEventListener('contextmenu', this.boundContext)
  }

  detach(): void {
    this.root.removeEventListener('pointerdown', this.boundPointer)
    window.removeEventListener('keydown', this.boundKey)
    this.root.removeEventListener('contextmenu', this.boundContext)
  }

  setEnabledTypes(types: InputType[]): void {
    this.enabledTypes = [...types]
  }

  /** Rebuild the key→action lookup from a `KeyBindings` map (#777). Reserved
   * keys are never added even if present in the config, so a hand-edited
   * `config.db3` cannot rebind Tab/Enter/Space/Escape. */
  setKeyBindings(bindings: KeyBindings): void {
    const map = new Map<string, InputAction>()
    const add = (action: InputAction, keys: string[] | undefined) => {
      for (const raw of keys ?? []) {
        const key = normalizeKey(raw)
        if (RESERVED_KEYS.has(key)) continue
        map.set(key, action)
      }
    }
    add('prev', bindings.prev ?? DEFAULT_KEY_BINDINGS.prev)
    add('next', bindings.next ?? DEFAULT_KEY_BINDINGS.next)
    add('toggle', bindings.toggle ?? DEFAULT_KEY_BINDINGS.toggle)
    this.keyToAction = map
  }

  private isPointerEnabled(pointerType: string): boolean {
    const mapped = POINTER_TYPE_MAP[pointerType] ?? 'touch'
    return this.enabledTypes.includes(mapped)
  }

  private handlePointer(e: PointerEvent): void {
    if (!this.isPointerEnabled(e.pointerType)) return
    // Tap-zones removed (#763): navigation now lives in the dock transport
    // buttons (prev/toggle/next). A tap on the veil only wakes the shell
    // — it resets the idle timers and re-reveals the content but no longer
    // fires prev/next/toggle, so a stray tap never skips a photo.
    // #766: pass the mapped InputType so the shell can wake dock-only for
    // mouse (ambient activity, like pointermove) but fully for touch.
    this.onActivity(POINTER_TYPE_MAP[e.pointerType] ?? 'touch')
  }

  private handleKey(e: KeyboardEvent): void {
    if (!this.enabledTypes.includes('keyboard')) return
    // #777: Escape is a fixed, non-configurable "hide" — close an open
    // dropdown first, else hide the dock. It fires regardless of key_bindings
    // and is intentionally NOT counted as wake activity (pressing Escape to
    // dismiss should not reset the idle timers or re-reveal content). When a
    // confirm modal is open, its own capture-phase Escape handler stops
    // propagation, so this only runs once the modal is dismissed.
    if (e.key === 'Escape') {
      this.onHide()
      e.preventDefault()
      return
    }
    // #777: Tab/Shift+Tab, Enter, Space are reserved for native focus movement
    // and <button> activation. Return without preventDefault so the browser
    // handles them — this is what lets a keyboard-only user Tab to a dock
    // control and press Enter/Space to activate it (previously the Enter/Space
    // → toggle binding canceled the click). They can never appear in the
    // keymap (setKeyBindings skips reserved keys), so this guard is also the
    // defense-in-depth against a hand-edited config.db3.
    if (e.key === 'Tab' || e.key === 'Enter' || e.key === ' ') return
    const action = this.keyToAction.get(normalizeKey(e.key))
    if (!action) return
    this.onActivity('keyboard')
    this.onAction(action)
    e.preventDefault()
  }
}
