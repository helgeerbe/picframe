/**
 * Error-message extraction helpers for `catch` handlers.
 *
 * These keep caught values `unknown`-typed (per `@typescript-eslint/no-explicit-any`)
 * without ad-hoc `any` casts when all we need is a human-readable message.
 */

/**
 * Extract `.message` from an `Error`-like value, falling back to a literal.
 * Mirrors the previous `e.message || fallback` pattern used across the config
 * store, but safe for `catch (e: unknown)`: reads `.message` from Error
 * instances *and* plain objects that carry a string `message` property, so
 * non-Error rejections keep their text.
 */
export function getErrorMessage(e: unknown, fallback: string): string {
  if (e instanceof Error) return e.message || fallback
  if (e && typeof e === 'object') {
    const message = (e as { message?: unknown }).message
    if (typeof message === 'string') return message || fallback
  }
  return fallback
}

/**
 * Extract a human-readable message from a thrown value, preferring an Axios
 * error's server-side `detail` (`error.response.data.detail`), then the error
 * `.message`, then the literal fallback. Mirrors the
 * `error?.response?.data?.detail || error?.message || fallback` pattern used
 * by the path/shader pickers.
 */
export function getApiErrorMessage(e: unknown, fallback: string): string {
  if (e && typeof e === 'object') {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    if (err.response?.data?.detail) return err.response.data.detail
    if (err.message) return err.message
  }
  if (typeof e === 'string') return e
  return fallback
}
