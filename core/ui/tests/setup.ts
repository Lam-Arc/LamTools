// jsdom does not implement window.matchMedia; the text flow directive
// (v-beam) consults it on mount. Without a mock every test mounting
// MessageView fails with "window.matchMedia is not a function".
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })
}

// jsdom has no document.fonts; SundaySegmented waits for font metrics before
// laying out, which otherwise fails while mounting the plugin manager in tests.
if (typeof document !== 'undefined' && !document.fonts) {
  Object.defineProperty(document, 'fonts', { value: { ready: Promise.resolve() } })
}

// jsdom has no requestIdleCallback either; without a stub the idle-mount
// scheduler falls back to a timer that really fires mid-test, which makes any
// test mounting the app shell flaky. The stub queues callbacks without ever
// running them, so production paths that schedule idle work are deterministic
// in tests: they stay pending unless a test flushes the queue on purpose.
const idleCallbackQueue = new Map<number, IdleRequestCallback>()
let idleCallbackSeq = 0
if (typeof globalThis.requestIdleCallback !== 'function') {
  globalThis.requestIdleCallback = (callback: IdleRequestCallback): number => {
    idleCallbackSeq += 1
    idleCallbackQueue.set(idleCallbackSeq, callback)
    return idleCallbackSeq
  }
  globalThis.cancelIdleCallback = (id: number): void => {
    idleCallbackQueue.delete(id)
  }
}

/** 测试手动驱动空闲回调（按需导入使用；setup 不自动导出）。 */
export function __flushIdleCallbacksForTests(): void {
  const deadline: IdleDeadline = { didTimeout: false, timeRemaining: () => 50 }
  for (const callback of [...idleCallbackQueue.values()]) callback(deadline)
  idleCallbackQueue.clear()
}
