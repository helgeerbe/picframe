/**
 * Pointer + keyboard input routing for the overlay shell (#739, item 11; #777).
 *
 * The shell installs a transparent full-screen "input veil" that captures
 * `pointerdown` (unified mouse/touch/pen) and `keydown`. A pointer tap only
 * wakes the shell (resets the idle timers and re-reveals content); navigation
 * is provided by the dock transport buttons and keyboard actions (#763).
 *
 * Keyboard routing (#777; #780 unified wake-then-navigate):
 * - `Escape` routes to the shell's `onHide`, which **toggles** the dock: it
 *   wakes (reveals + re-arms) when the dock is idle, and dismisses it when
 *   shown (closing an open dropdown first). It is not user-assignable and
 *   fires regardless of `key_bindings`.
 * - **Any other key wakes the dock** (resets the idle timer + re-reveals the
 *   dock chrome, dock-only like every other input), so an unbound key is no
 *   longer a silent no-op — the dock appears and the user can learn the
 *   shortcuts.
 * - `Tab`/`Shift+Tab`, `Enter`, `Space` are **reserved**: after waking they
 *   return without `preventDefault`, so the browser handles native focus
 *   movement and `<button>` activation. This removes the old `Enter`/`Space`
 *   → `toggle` collision that shadowed focused dock buttons.
 * - Bound keys (`prev`/`next`/`toggle`, from the configurable `key_bindings`
 *   map) follow a **two-step** wake-then-navigate model (#780): when the dock
 *   is idle (hidden), the first press only wakes it (reveals + re-arms) and
 *   does NOT fire the action, so a single arrow no longer both reveals the
 *   dock and skips a photo. The action fires on the next press once the dock
 *   is visible. `dockIdle` defaults to "never idle" so callers/tests that omit
 *   it keep the one-press behaviour.
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
   * Carries the originating `InputType` for diagnostics; the shell wakes
   * dock-only for every input (mouse, keyboard, touch), matching
   * `onMouseMove` — auto-hide panels stay in their current state (#766, #780). */
  onActivity: (source: InputType) => void
  /** Predicate reporting whether the dock is currently idle/hidden, so a bound
   * key's first press on a hidden dock only wakes (two-step wake-then-navigate,
   * #780) instead of also firing its action. Defaults to "never idle" so the
   * action fires in one press when the caller doesn't care about dock state
   * (and so existing InputRouter tests stay green). */
  dockIdle?: () => boolean
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
  /** Reports whether the dock is currently idle/hidden (#780), so a bound key
   * only wakes (no action) on the first press while hidden. */
  private readonly dockIdle: () => boolean
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
    // #780: default "never idle" keeps the one-press action behaviour for
    // callers/tests that don't supply a dock-state predicate.
    this.dockIdle = opts.dockIdle ?? (() => false)
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
    // #766/#780: pass the mapped InputType; the shell wakes dock-only for
    // every pointer type (ambient activity, like pointermove) — touch no
    // longer does a full wake.
    this.onActivity(POINTER_TYPE_MAP[e.pointerType] ?? 'touch')
  }

  private handleKey(e: KeyboardEvent): void {
    if (!this.enabledTypes.includes('keyboard')) return
    // #780: Escape routes to the shell's onHide, which toggles the dock —
    // wake-when-hidden, dismiss-when-shown (closing an open dropdown first).
    // It is intentionally NOT counted as onActivity here: the shell owns the
    // wake-vs-dismiss decision based on the current dock-idle state. When a
    // confirm modal is open, its own capture-phase Escape handler stops
    // propagation, so this only runs once the modal is dismissed.
    if (e.key === 'Escape') {
      this.onHide()
      e.preventDefault()
      return
    }
    // #780: any other key wakes the dock + extends visibility (dock-only,
    // matching every other input), so an unbound key reveals the dock instead
    // of being a silent no-op — the user sees the transport controls and can
    // learn the shortcuts. Bound keys additionally fire their action below —
    // but only once the dock is already visible (#780 two-step wake-then-
    // navigate): capture the idle state BEFORE the wake (the wake removes the
    // dock-idle class), so the first press on a hidden dock reveals it without
    // also skipping the photo; the action then fires on the next press.
    const dockWasIdle = this.dockIdle()
    this.onActivity('keyboard')
    // Tab/Shift+Tab, Enter, Space are reserved for native focus movement and
    // <button> activation: return without preventDefault so the browser
    // handles them (a keyboard-only user can Tab to a dock control and press
    // Enter/Space to activate it). They can never appear in the keymap
    // (setKeyBindings skips reserved keys), so this guard is also the
    // defense-in-depth against a hand-edited config.db3. The wake above still
    // fires, so Tabbing toward the dock also reveals it.
    if (e.key === 'Tab' || e.key === 'Enter' || e.key === ' ') return
    const action = this.keyToAction.get(normalizeKey(e.key))
    if (action) {
      // #780: while the dock was hidden, this first press only wakes it —
      // don't fire the action yet. The next press (dock now visible) navigates.
      if (dockWasIdle) return
      this.onAction(action)
      e.preventDefault()
    }
  }
}
