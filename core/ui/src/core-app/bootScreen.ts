/**
 * The boot layer: the screen between the launcher icon and the first workspace paint.
 *
 * Why it is a module of its own, and why it is not inside `#app`:
 *
 * user:“启动层独立于 #app，Vue 挂载不会清掉它。只有确认首屏已经渲染出内容后才淡出移除”
 * +(冷启动时那段文字以前写在 #app 里，Vue 一挂载就把它清空，而真正的首屏还要等几秒到
 * 几十秒，用户看到的就是一片纯白或纯黑)。
 *
 * So the markup lives in `index-android.html`, beside `#app`, together with its styles:
 * the first painted frame has to be branded, and a module's CSS arrives later than that
 * frame. This file owns only the behaviour — the phase text, the progress bar, the error
 * state, and the decision about when the layer has done its job.
 *
 * The layer is removed for exactly two reasons:
 *
 * 1. `#app` has visible content (the first real paint), or
 * 2. nothing appeared within `FIRST_PAINT_DEADLINE_MS`.
 *
 * The second rule exists so a bug elsewhere can never leave an opaque black rectangle
 * covering a working app. A blank screen is bad; a screen that cannot be dismissed is
 * worse.
 */

/** What `runtime-progress` carries. Every field is `unknown` until it is checked: the
 *  payload crosses a language boundary and a wrong shape must not throw during boot. */
export interface BootProgressPayload {
  phase?: unknown
  done?: unknown
  total?: unknown
  message?: unknown
}

/** Phase names the host emits, and the Chinese line the user reads for each.
 *
 *  `waiting` shares 「启动核心」 on purpose: from the user's side proot spawning and the
 *  guest importing Python are one step, and the note underneath says which one it is. */
const PHASE_LABEL: Record<string, string> = {
  staging: '准备运行时',
  unpacking: '解压运行时',
  starting: '启动核心',
  waiting: '启动核心',
  ready: '正在加载界面',
  failed: '启动失败',
}

/** How long the layer waits for `#app` to paint content before removing itself anyway. */
const FIRST_PAINT_DEADLINE_MS = 45_000

/** Matches the `opacity` transition in `index-android.html`, plus a frame of slack. */
const FADE_MS = 380

interface BootNodes {
  root: HTMLElement
  phase: HTMLElement
  note: HTMLElement
  fill: HTMLElement | null
  retry: HTMLButtonElement | null
}

/** True once `#app` holds an element with a real box.
 *
 *  Counting children alone is not enough: the shared app renders its shell immediately and
 *  then fills it, so "a child exists" can be true while the screen is still empty. A box
 *  with width and height means the browser has something to paint. */
function interfacePainted(): boolean {
  const node = document.getElementById('app')
  if (!node || node.childElementCount === 0) return false
  // The shell is positioned `fixed`, so `#app` itself can have zero height while the
  // interface is fully painted. A child with a real box is the honest signal.
  for (const child of Array.from(node.children)) {
    const box = child.getBoundingClientRect()
    if (box.width > 1 && box.height > 1) return true
  }
  return false
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

/** Two frames: the first one requests the paint that follows the DOM change, the second
 *  runs after it. One frame is not enough to call a screen "painted". */
function afterPaint(): Promise<void> {
  return new Promise((resolve) => {
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => resolve())
    })
  })
}

function percentOf(done: number, total: number): number | null {
  if (!Number.isFinite(done) || !Number.isFinite(total) || total <= 0) return null
  const ratio = done / total
  if (!Number.isFinite(ratio)) return null
  return Math.max(0, Math.min(100, Math.round(ratio * 100)))
}

class BootScreen {
  private nodes: BootNodes | null = null
  private bound = false
  /** True once the layer has been hidden or has shown a failure: after that, later calls
   *  must not resurrect it or dismiss the error screen. */
  private settled = false
  /** True while waiting for the first paint: progress must not repaint, but a failure
   *  must still be able to take the layer over. */
  private revealing = false
  /** True once `fail()` has claimed the layer, so `reveal()` stops waiting. */
  private failed = false

  /** Looks the elements up once. The markup ships in the HTML, so this is normally a
   *  plain `getElementById`; a missing node means the page is not the one we ship. */
  private ensure(): BootNodes | null {
    if (this.bound) return this.nodes
    const root = document.getElementById('boot-screen')
    if (!root) {
      this.bound = true
      this.nodes = null
      return null
    }
    const retry = document.getElementById('boot-retry') as HTMLButtonElement | null
    if (retry && !retry.dataset.bound) {
      retry.dataset.bound = '1'
      // A retry that reloads the webview is honest: the guest process state is the host's
      // business, and the host survives a page reload.
      retry.addEventListener('click', () => window.location.reload())
    }
    this.bound = true
    this.nodes = {
      root,
      phase: document.getElementById('boot-phase') ?? root,
      note: document.getElementById('boot-note') ?? root,
      fill: document.getElementById('boot-fill'),
      retry,
    }
    return this.nodes
  }

  /** Paints one phase. `note` is the line under the phase; `percent` null means "no
   *  honest number", which switches the bar to its indeterminate animation. */
  phase(phase: string, note: string, percent: number | null = null): void {
    if (this.settled || this.revealing) return
    const nodes = this.ensure()
    if (!nodes) return
    const label = PHASE_LABEL[phase] ?? PHASE_LABEL.staging
    nodes.root.classList.remove('is-error')
    nodes.root.classList.toggle('is-indeterminate', percent === null)
    nodes.phase.textContent = percent === null ? label : `${label} ${percent}%`
    if (note) nodes.note.textContent = note
    if (nodes.fill) nodes.fill.style.width = percent === null ? '' : `${percent}%`
    if (nodes.retry) nodes.retry.hidden = true
  }

  /** Applies a `runtime-progress` event. Unknown phases are ignored rather than shown:
   *  a phase the host invents later must not blank out a line that is already correct. */
  apply(payload: BootProgressPayload | null | undefined): void {
    if (this.settled || this.revealing || !payload) return
    const phase = typeof payload.phase === 'string' ? payload.phase : ''
    if (!phase || !PHASE_LABEL[phase]) return
    const message = typeof payload.message === 'string' ? payload.message : ''
    if (phase === 'failed') {
      this.fail(message || '核心启动失败')
      return
    }
    // `ready` means the guest answered; from here the only remaining wait is the
    // interface itself, so the bar goes indeterminate rather than staying at 100%.
    if (phase === 'ready') {
      this.phase(phase, message || '正在加载界面…')
      return
    }
    const done = Number(payload.done ?? 0)
    const total = Number(payload.total ?? 0)
    this.phase(phase, message, percentOf(done, total))
  }

  /** The failure path: the error text and a retry button, never a blank screen.
   *
   *  user:“失败路径保留：core_start 抛错时启动层显示错误与「重试」按钮，不要落在空白”
   *  +(所以这里把启动层留在原地，而不是先移除再让界面自己解释)。 */
  fail(message: string): void {
    if (this.failed) return
    const nodes = this.ensure()
    if (!nodes) return
    this.failed = true
    this.settled = true
    this.revealing = false
    nodes.root.classList.add('is-error')
    nodes.root.classList.remove('is-leaving', 'is-indeterminate')
    nodes.phase.textContent = PHASE_LABEL.failed
    nodes.note.textContent = message
    if (nodes.retry) nodes.retry.hidden = false
  }

  /** Removes the layer once the workspace has painted, or after the deadline.
   *
   *  user:“只有确认首屏已经渲染出内容后才淡出移除；如果 45 秒内仍无内容，也要移除，
   *  不能让启动层永久盖住界面”+(两个条件都在这里：先等内容，等不到就按时让路)。 */
  async reveal(): Promise<void> {
    if (this.settled) return
    const nodes = this.ensure()
    if (!nodes) return
    this.revealing = true

    const deadline = performance.now() + FIRST_PAINT_DEADLINE_MS
    while (performance.now() < deadline) {
      // A render error during the wait has already turned this layer into the error
      // screen; fading it away would hide the only explanation the user has.
      if (this.failed) return
      if (interfacePainted()) break
      await delay(100)
    }
    if (this.failed) return
    this.revealing = false
    this.settled = true
    if (!interfacePainted()) {
      console.warn('[sunday] boot: 45 秒内没有首屏内容，仍然移除启动层')
    }
    // Two frames so the paint that ended the wait is on screen before the layer fades.
    await afterPaint()
    nodes.root.classList.add('is-leaving')
    await delay(FADE_MS)
    nodes.root.remove()
    this.nodes = null
  }

  /** Whether the layer is still on screen. Used by the error handler to decide between
   *  "explain on the boot layer" and "the app is running, leave it alone". */
  get visible(): boolean {
    return this.nodes !== null && this.nodes.root.isConnected && !this.settled
  }
}

let instance: BootScreen | null = null

/** The one boot layer this page has. */
export function bootScreen(): BootScreen {
  instance ??= new BootScreen()
  return instance
}

export type { BootScreen }
