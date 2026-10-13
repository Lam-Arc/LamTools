export async function waitForBackendApiBase(
  request: () => Promise<unknown>,
  options: { signal?: AbortSignal; attempts?: number; delayMs?: number } = {},
): Promise<string> {
  const attempts = options.attempts ?? 400
  const delayMs = options.delayMs ?? 250
  for (let attempt = 0; attempt < attempts; attempt++) {
    options.signal?.throwIfAborted()
    try {
      const value = await request()
      options.signal?.throwIfAborted()
      if (typeof value !== 'string' || !/^http:\/\/127\.0\.0\.1:\d+$/.test(value)) {
        throw new Error('Core API 地址无效')
      }
      return value
    } catch (error) {
      options.signal?.throwIfAborted()
      // Only this explicit readiness state is transient. Startup failures,
      // invalid addresses and invocation failures must remain visible.
      if (String(error) !== 'backend not yet started') throw error
      if (attempt + 1 === attempts) throw new Error('Sunday 启动超时，请重新启动应用')
      await new Promise<void>((resolve, reject) => {
        const signal = options.signal
        const abort = () => {
          clearTimeout(timer)
          reject(signal?.reason ?? new DOMException('Aborted', 'AbortError'))
        }
        const timer = setTimeout(() => {
          signal?.removeEventListener('abort', abort)
          resolve()
        }, delayMs)
        signal?.addEventListener('abort', abort, { once: true })
      })
    }
  }
  throw new Error('Sunday 启动超时，请重新启动应用')
}
