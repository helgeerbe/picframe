import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])'
].join(',')

export function useFocusTrap(
  isOpen: Ref<boolean>,
  container: Ref<HTMLElement | null>,
  onClose: () => void
) {
  let previousFocus: HTMLElement | null = null

  const focusFirst = async () => {
    await nextTick()
    const element = container.value
    if (!element) return
    const focusable = Array.from(element.querySelectorAll<HTMLElement>(focusableSelector))
      .filter((item) => item.offsetParent !== null || item === document.activeElement)
    ;(focusable[0] || element).focus()
  }

  const handleKeydown = (event: KeyboardEvent) => {
    if (!isOpen.value) return
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab') return

    const element = container.value
    if (!element) return
    const focusable = Array.from(element.querySelectorAll<HTMLElement>(focusableSelector))
      .filter((item) => item.offsetParent !== null || item === document.activeElement)
    if (!focusable.length) {
      event.preventDefault()
      element.focus()
      return
    }

    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  watch(isOpen, (open) => {
    if (open) {
      previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
      document.addEventListener('keydown', handleKeydown)
      document.body.style.overflow = 'hidden'
      void focusFirst()
    } else {
      document.removeEventListener('keydown', handleKeydown)
      document.body.style.overflow = ''
      previousFocus?.focus()
      previousFocus = null
    }
  })

  onBeforeUnmount(() => {
    document.removeEventListener('keydown', handleKeydown)
    document.body.style.overflow = ''
  })
}
