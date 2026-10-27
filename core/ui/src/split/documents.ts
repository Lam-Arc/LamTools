import { computed, effectScope, getCurrentScope, onScopeDispose, reactive, watch, type ComputedRef, type EffectScope } from 'vue'
import { splitNative } from './native'
// user:“审查分屏代码，并优化”+(草稿按一次编辑节奏合并写入，长文件连续输入时不再每个按键同步写本机存储)。
const DRAFT_WRITE_DELAY = 300
export interface SplitDocumentState { root: string; path: string; content: string; baseline: string; loaded: boolean; loading: boolean; saving: boolean; error: string; recovered: boolean }
export interface SplitDocumentHandle { doc: SplitDocumentState; dirty: ComputedRef<boolean>; load: () => Promise<void>; save: (path?: string) => Promise<boolean>; flushDraft: () => void; release: () => void }
interface SplitDocumentView extends SplitDocumentHandle { views: number; scope: EffectScope }
export function createSplitDocuments() {
  const scope = effectScope(true)
  const pending = new Set<() => void>()
  let flushBound = false
  const flushPending = () => { for (const flush of [...pending]) flush() }
  const attachFlush = () => { if (!flushBound && typeof window !== 'undefined') { window.addEventListener('pagehide', flushPending); flushBound = true } }
  const detachFlush = () => { if (flushBound && typeof window !== 'undefined') { window.removeEventListener('pagehide', flushPending); flushBound = false } }
  const dispose = () => { flushPending(); scope.stop(); detachFlush() }
  if (getCurrentScope()) onScopeDispose(dispose)
  // user:“审查分屏代码，并优化”+(最后一个编辑器标签关闭后释放整篇文件内容和它的监听，长会话不再无限累积内存)。
  const documents = new Map<string, SplitDocumentView>()
  // user:“路径无法访问：文件名、目录名或卷标语法不正确”+(先统一分隔符，再识别盘符、UNC 和 Windows 长路径，避免重复拼接项目目录)。
  const absolute = (root: string, path: string) => {
    const value = path.replace(/\\/g, '/')
    return !value || /^[A-Za-z]:\/|^\//.test(value) ? value : `${root.replace(/\\/g, '/').replace(/\/$/, '')}/${value}`
  }
  const identity = (root: string, path: string, id: string) => `${root.toLowerCase()}\0${path ? absolute(root, path).toLowerCase() : id}`
  function createDocument(root: string, path: string, id: string, holder: { view?: SplitDocumentView }) {
    let key = `lamtools:split-draft:${root}:${path || id}`
    const doc = reactive({ root, path, content: '', baseline: '', loaded: false, loading: false, saving: false, error: '', recovered: false })
    const dirty = computed(() => doc.content !== doc.baseline)
    try {
      const cached = JSON.parse(localStorage.getItem(key) || 'null')
      if (cached && typeof cached.content === 'string' && typeof cached.baseline === 'string') { doc.content = cached.content; doc.baseline = cached.baseline; doc.recovered = true }
    } catch { /* A malformed draft must not prevent opening the file. */ }
    let timer: ReturnType<typeof setTimeout> | undefined
    const writeDraft = () => {
      if (timer) { clearTimeout(timer); timer = undefined }
      pending.delete(writeDraft)
      try {
        if (dirty.value) localStorage.setItem(key, JSON.stringify({ content: doc.content, baseline: doc.baseline }))
        else localStorage.removeItem(key)
      } catch { doc.error = '草稿暂时无法备份到本机，请及时保存文件' }
      if (!pending.size) detachFlush()
    }
    const cancelDraft = () => {
      if (timer) clearTimeout(timer)
      timer = undefined
      pending.delete(writeDraft)
      if (!pending.size) detachFlush()
    }
    const scheduleDraft = () => {
      if (!dirty.value) {
        cancelDraft()
        try { localStorage.removeItem(key) } catch { /* The edited content stays in memory even when cleanup fails. */ }
        return
      }
      pending.add(writeDraft)
      attachFlush()
      if (timer) clearTimeout(timer)
      timer = setTimeout(writeDraft, DRAFT_WRITE_DELAY)
    }
    watch(() => [doc.content, doc.baseline], scheduleDraft)
    async function load() {
      // user:“修”+(重新打开时刷新已保存文件；共享的未保存草稿不被磁盘内容覆盖)。
      if (doc.loading || doc.saving || (doc.loaded && dirty.value)) return
      doc.loading = true; doc.loaded = false; doc.error = ''
      try {
        const text = doc.path ? await splitNative<string>('split_file_read', { root: doc.root, path: doc.path }) : ''
        if (!dirty.value) { doc.content = text; doc.baseline = text; doc.recovered = false }
        else if (doc.baseline !== text) doc.error = '文件在上次编辑后发生变化。已恢复草稿；请核对后保存到新文件'
        doc.loaded = true
      } catch (error) { doc.error = String(error); if (doc.recovered || dirty.value) doc.loaded = true }
      finally { doc.loading = false }
    }
    async function save(path = doc.path): Promise<boolean> {
      if (doc.saving) return false
      if (!path) { doc.error = '请填写文件保存路径'; return false }
      if (!doc.root) { doc.error = '此编辑器尚未绑定项目，请先选择项目并在该项目中打开编辑器；当前草稿已保留'; return false }
      if (!doc.loaded) { doc.error = '文件尚未读取完成，不能覆盖保存'; return false }
      path = absolute(doc.root, path)
      // user:“审查分屏代码，并优化”+(另存为不能接管另一个已打开标签的文件：否则两份内容共用一个草稿键，互相覆盖)。
      const collision = documents.get(identity(root, path, id))
      if (collision && collision !== self()) { doc.error = '这个文件已在另一个标签中打开，请先关闭那个标签再另存为；当前内容已保留'; return false }
      doc.saving = true; doc.error = ''
      const content = doc.content
      try {
        await splitNative('split_file_write', { root: doc.root, path, content, original: path === doc.path && doc.path ? doc.baseline : null })
        const previousKey = key
        // user:“修”+(另存为成功后移除旧路径映射，重新打开原文件必须独立读取)。
        const previousIdentity = identity(root, doc.path, id)
        if (documents.get(previousIdentity) === self()) documents.delete(previousIdentity)
        doc.path = path; doc.baseline = content; doc.recovered = false
        key = `lamtools:split-draft:${root}:${path}`
        documents.set(identity(root, path, id), self())
        // A saved file is its own baseline: drop the pending and persisted draft before another view can recover it.
        cancelDraft()
        try {
          if (previousKey !== key) localStorage.removeItem(previousKey)
          localStorage.removeItem(key)
        } catch { /* Keep the saved file even if draft cleanup fails. */ }
        return true
      } catch (error) { doc.error = String(error); return false }
      finally { doc.saving = false }
    }
    const flushDraft = () => { cancelDraft(); writeDraft() }
    const document: Omit<SplitDocumentHandle, 'release'> = { doc, dirty, load, save, flushDraft }
    const self = (): SplitDocumentView => (holder.view ?? document) as SplitDocumentView
    return document
  }
  function releaseDocument(target: SplitDocumentView) {
    target.views = Math.max(0, target.views - 1)
    if (target.views > 0) return
    target.flushDraft()
    target.scope.stop()
    for (const [key, value] of documents) if (value === target) documents.delete(key)
  }
  return {
    get(root: string, path: string, id: string): SplitDocumentHandle {
      path = absolute(root, path)
      const key = identity(root, path, id)
      let document = documents.get(key)
      if (!document) {
        let created!: SplitDocumentView
        created = scope.run(() => {
          const documentScope = effectScope(), holder: { view?: SplitDocumentView } = {}
          const base = documentScope.run(() => createDocument(root, path, id, holder))!
          const view: SplitDocumentView = { ...base, views: 0, scope: documentScope, release: () => releaseDocument(created) }
          holder.view = view
          return view
        })!
        document = created
        documents.set(key, created)
      }
      document.views += 1
      return document
    },
    flush: flushPending,
    dispose,
  }
}
