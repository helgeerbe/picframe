/**
 * Pointer + keyboard input routing for the overlay shell (#739, item 11).
 *
 * The shell installs a transparent full-screen "input veil" that captures
 * `pointerdown` (unified mouse/touch/pen) and `keydown`. A pointer tap only
 * wakes the shell (resets the idle timers and re-reveals content); navigation
 * is provided by the dock transport buttons and keyboard actions (#763).
 * Keys map: ArrowLeft/ArrowRight = prev/next, Enter/Space = toggle,
 * Escape = hide. Only the input device classes enabled in
 * `overlay.enabled_input_types` are honoured; a pen is treated as touch.
 *
 * An idle timer fades the *content* (dock + visible plugin) to opacity 0 after
 * `idle_hide_seconds` (auto_hide mode only); any enabled event resets the timer
 * and re-reveals the content. The veil itself never fades, so a wake tap always
 * lands. The GTK surface opacity (driven by the worker for video reveal) is a
 * separate layer and is not touched here.
 */

import type { InputAction, InputType } from './types'

export interface InputRouterOptions {
  /** Element that captures the events (the transparent veil). */
  root: HTMLElement
  enabledTypes: InputType[]
  onAction: (action: InputAction) => void
  /** Called for every enabled event, to reset the idle timer / wake content. */
  onActivity: () => void
}

const POINTER_TYPE_MAP: Record<string, InputType> = {
  mouse: 'mouse',
  touch: 'touch',
  pen: 'touch'
}

export class InputRouter {
  private readonly root: HTMLElement
  private enabledTypes: InputType[]
  private readonly onAction: (action: InputAction) => void
  private readonly onActivity: () => void
  private boundPointer: (e: PointerEvent) => void
  private boundKey: (e: KeyboardEvent) => void
  private boundContext: (e: Event) => void

  constructor(opts: InputRouterOptions) {
    this.root = opts.root
    this.enabledTypes = [...opts.enabledTypes]
    this.onAction = opts.onAction
    this.onActivity = opts.onActivity
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

  private isPointerEnabled(pointerType: string): boolean {
    const mapped = POINTER_TYPE_MAP[pointerType] ?? 'touch'
    return this.enabledTypes.includes(mapped)
  }

  private handlePointer(e: PointerEvent): void {
    if (!this.isPointerEnabled(e.pointerType)) return
    // Tap-zones removed (#763): navigation now lives in the dock transport
    // buttons (prev/toggle/next/hide). A tap on the veil only wakes the shell
    // — it resets the idle timers and re-reveals the content but no longer
    // fires prev/next/toggle, so a stray tap never skips a photo.
    this.onActivity()
  }

  private handleKey(e: KeyboardEvent): void {
    if (!this.enabledTypes.includes('keyboard')) return
    switch (e.key) {
      case 'ArrowLeft':
        this.onActivity()
        this.onAction('prev')
        break
      case 'ArrowRight':
        this.onActivity()
        this.onAction('next')
        break
      case 'Enter':
      case ' ':
        this.onActivity()
        this.onAction('toggle')
        break
      case 'Escape':
        this.onActivity()
        this.onAction('hide')
        break
      default:
        return
    }
    e.preventDefault()
  }
}
