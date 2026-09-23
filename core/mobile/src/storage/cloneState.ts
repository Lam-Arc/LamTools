/**
 * Clone persisted state across the standalone stores.
 *
 * The persisted state is JSON by contract, so a JSON round-trip is always
 * correct.  `structuredClone` is preferred because it preserves more value
 * shapes, but it rejects Vue reactive proxies, and settings panels legitimately
 * hand reactive objects back to these stores.  Falling back instead of throwing
 * keeps a UI round-trip from breaking a later read.
 */
export function cloneState<T>(value: T): T {
  if (typeof structuredClone === 'function') {
    try {
      return structuredClone(value)
    } catch {
      // Vue refs expose reactive proxies that structuredClone cannot accept.
    }
  }
  return JSON.parse(JSON.stringify(value)) as T
}
