/**
 * 工作区控制器（V2-C1）：把 `workspace/` 引擎接成 Vue 可用的单一控制器。
 *
 * user:“用新引擎把工作区外壳换掉，并让应用编译通过、旧功能等价；本轮不删旧文件”+
 * (引擎是纯函数（model/compute/ops/tabs/persist/hit/visibility），这里只做三件事：
 *  1) 持有唯一的 `WorkspaceModel` 与内容实例表（`SplitTab` 不复制，移动只换位置）；
 *  2) 把引擎结论翻成界面要的东西（geometry / issues / floats / panes / tabs）；
 *  3) 保留旧控制器的调用面，让 LamToolsApp、辅助对话、内容组件一行不改。
 *
 * 分层边界：本文件不测量 DOM（只有 `setBounds` 收一次外壳矩形），不画任何东西。
 */
import { computed, getCurrentScope, hasInjectionContext, onScopeDispose, provide, reactive, ref, shallowRef, watch, type ComputedRef, type Ref } from 'vue'
import type { AuxiliaryContext } from '@/auxiliary/workspace'
import type { SplitContent, SplitTab } from './types'
import type { SurfaceMode } from '@/workspace/surface'
import { WorkspaceKey } from './context'
import {
  addTab,
  areasOf,
  cloneModel,
  closeArea,
  closeTab as closeTabIn,
  computeWorkspace,
  createWorkspace,
  cycleFloatFocus,
  floatToBack,
  floatToFront,
  migrateLegacySplitState,
  moveTab as moveTabIn,
  normalizeWorkspace,
  parseWorkspace,
  pinFloat,
  placeOf,
  resizeSplit,
  serializeWorkspace,
  selectTab as selectTabIn,
  setFloatRect,
  setFloatYield,
  splitArea,
  unpinArea,
  DEFAULT_FLOAT_RECT,
  MIN_SPLIT_VIEWPORT,
  WORKSPACE_STORAGE_KEY,
  type AreaId,
  type Issue,
  type Rect,
  type SurfaceId,
  type SurfaceKind,
  type SurfaceRef,
  type WorkspaceGeometry,
  type WorkspaceModel,
  type WorkspaceLayout,
} from './index'

/** 旧内容类型 ↔ 引擎内容类型：引擎只关心六类，`page/editor/files` 都是 file。 */
const TO_ENGINE: Record<SplitContent, SurfaceKind> = {
  page: 'file',
  editor: 'file',
  files: 'file',
  browser: 'browser',
  preview: 'preview',
  agent: 'agent',
  conversation: 'conversation',
  plugin: 'plugin',
}

const TO_CONTENT: Record<SurfaceKind, SplitContent> = {
  file: 'page',
  browser: 'browser',
  preview: 'preview',
  agent: 'agent',
  conversation: 'conversation',
  plugin: 'plugin',
}

/** 交互相位：只有会重排布局的手势才让网页让位（`floating` 必须跟手）。 */
export type WorkspacePhase = 'idle' | 'draggingTab' | 'resizingDivider' | 'movingArea' | 'floating'

export interface WorkspaceBounds {
  x: number
  y: number
  width: number
  height: number
}

/** 关闭守卫：内容自己要拦一下（比如网页有未保存的表单）。 */
export type CloseGuard = (proceed: () => void) => void

export interface WorkspaceControllerOptions {
  /** 交互测试用：不读不写本地存档。 */
  persist?: boolean
  onInsufficient?: () => void
  limits?: { main: { width: number; height: number }; aux: { width: number; height: number } }
}

function surfaceRefOf(tab: SplitTab): SurfaceRef {
  const ref: SurfaceRef = { id: tab.id, kind: TO_ENGINE[tab.kind] ?? 'file', title: tab.title }
  if (tab.resource) ref.resource = tab.resource
  if (tab.kind === 'page' || tab.kind === 'editor' || tab.kind === 'files') ref.fileView = tab.kind
  for (const key of ['root', 'projectId', 'sessionId', 'profile'] as const) if (tab[key]) ref[key] = tab[key]
  if (typeof tab.zoom === 'number') ref.zoom = tab.zoom
  return ref
}

function readStored(key: string): string | null {
  try { return localStorage.getItem(key) } catch { return null }
}

function writeStored(key: string, value: string): void {
  try { localStorage.setItem(key, value) } catch { /* 隐私模式/配额满：布局存不下不该影响使用 */ }
}

/**
 * user:“新的 useWorkspace(storageKey, workRoot, projectId) 用引擎 + persist.ts（v4）替代
 * useSplitWorkspace；旧存档通过 migrateLegacySplitState 迁移一次”+
 * (读档顺序：v4 主档 → v4 备份 → 旧 split 存档迁移 → 空工作区。写档前把当前有效的一份挪到备份位，
 *  坏档只丢最后一次改动，不会把用户摆好的整桌布局一起清空。)
 */
export function useWorkspace(
  storageKey: Ref<string>,
  workRoot?: Ref<string>,
  projectId?: Ref<string | null | undefined>,
  options: WorkspaceControllerOptions = {},
) {
  const seedId = 'agent-main'
  const seedTab: SplitTab = {
    id: seedId,
    kind: 'agent',
    title: 'Agent',
    resource: '',
    ...(workRoot?.value ? { root: workRoot.value } : {}),
  }

  /** 内容实例表：同一个 `SplitTab` 对象在移动间不复制（`{...tab}` 会丢运行状态）。 */
  const content = new Map<SurfaceId, SplitTab>([[seedId, seedTab]])
  const model = shallowRef<WorkspaceModel>(createWorkspace([surfaceRefOf(seedTab)], seedId))
  const bounds = ref<WorkspaceBounds>({ x: 0, y: 0, width: 0, height: 0 })
  const hidden = ref(false)
  const activePane = ref<AreaId>('main')
  const interacting = ref(false)
  const phase = ref<WorkspacePhase>('idle')
  const parkedFloats = ref<SplitTab[]>([])
  /** 浮层落位预览（= pin 的落地结果，不是估算）。 */
  const pinPreview = ref<{ surfaceId: SurfaceId; rect: Rect; areaId: AreaId } | null>(null)
  let seq = 0

  const backupKey = () => `${storageKey.value}.prev`

  function hydrateTabs(candidate: WorkspaceModel): WorkspaceModel {
    // 引擎只存 SurfaceRef；内容实例要在这里补回同一份对象，否则重载后内容会被重建。
    for (const [id, ref] of Object.entries(candidate.surfaces)) {
      const existing = content.get(id)
      const base: SplitTab = existing ?? {
        id,
        kind: ref.kind === 'file' ? (ref.fileView ?? 'page') : TO_CONTENT[ref.kind],
        title: ref.title,
        resource: ref.resource ?? '',
      }
      base.title = ref.title
      base.resource = ref.resource ?? base.resource
      if (typeof ref.zoom === 'number') base.zoom = ref.zoom
      for (const key of ['root', 'projectId', 'sessionId', 'profile'] as const) if (ref[key]) base[key] = ref[key]
      content.set(id, base)
    }
    return candidate
  }

  function load() {
    if (options.persist === false) return
    const primary = readStored(storageKey.value)
    const backup = readStored(backupKey())
    const fallback = model.value
    const first = parseWorkspace(primary, fallback)
    const second = first.model === fallback && backup ? parseWorkspace(backup, fallback) : null
    let next = second && second.model !== fallback ? second.model : first.model
    if (next === fallback) {
      // user:“旧存档通过 migrateLegacySplitState 迁移一次”+(v1–v3 的旧 split 存档读一次就搬进 v4)。
      const legacy = readStored('lamtools.split.state')
      const migrated = legacy ? migrateLegacySplitState(safeJson(legacy)) : null
      if (migrated) next = migrated.model
    }
    model.value = hydrateTabs(normalizeWorkspace(next))
    const main = areasOf(model.value).find(area => area.role === 'main')
    activePane.value = main?.id ?? areasOf(model.value)[0]?.id ?? 'main'
  }

  function safeJson(raw: string): unknown {
    try { return JSON.parse(raw) } catch { return null }
  }

  let saveTimer: ReturnType<typeof setTimeout> | undefined
  function flushSave() {
    if (saveTimer === undefined) return
    clearTimeout(saveTimer)
    saveTimer = undefined
    const payload = serializeWorkspace(model.value)
    const previous = readStored(storageKey.value)
    if (previous === payload) return
    if (previous) writeStored(backupKey(), previous)
    writeStored(storageKey.value, payload)
  }

  function save() {
    if (options.persist === false) return
    if (saveTimer !== undefined) clearTimeout(saveTimer)
    saveTimer = setTimeout(flushSave, 160)
  }

  // user:“快速精准高效的解决”+(退出窗口时补写最后一帧，保住刚导航的地址和刚调整的布局)。
  if (options.persist !== false && typeof window !== 'undefined' && getCurrentScope()) {
    window.addEventListener('pagehide', flushSave)
    onScopeDispose(() => {
      window.removeEventListener('pagehide', flushSave)
      flushSave()
    })
  }

  load()

  function layoutOf(current: WorkspaceModel): WorkspaceLayout {
    if (current.prefs.layout) return current.prefs.layout
    const active = areasOf(current).find(area => area.role === 'main')?.active
    return active && current.surfaces[active]?.kind === 'browser' ? 'browser' : 'agent'
  }

  /** 每次变更的唯一出口：跑 normalize（去重/收拢/恰好一个 main）再落地。 */
  function commit(next: WorkspaceModel) {
    const normalized = normalizeWorkspace({ ...next, prefs: { ...next.prefs, layout: next.prefs.layout ?? layoutOf(model.value) } })
    if (normalized === model.value) return
    model.value = normalized
    const ids = new Set(areasOf(normalized).map(area => area.id))
    if (!ids.has(activePane.value)) activePane.value = areasOf(normalized)[0]?.id ?? 'main'
    save()
  }

  // ---------------------------------------------------------------------------
  // 几何：唯一来源。组件不测量 DOM，只用这里的数字。
  // ---------------------------------------------------------------------------
  const limits = options.limits

  const geometry: ComputedRef<WorkspaceGeometry> = computed(() => computeWorkspace(
    model.value,
    { x: 0, y: 0, width: Math.max(0, bounds.value.width), height: Math.max(0, bounds.value.height) },
    limits ? { limits } : {},
  ))

  const issues = computed<Issue[]>(() => geometry.value.issues)

  /**
   * user:“issues 里有 insufficient 时不隐藏区域，在折叠条/创建入口显示「需要 Npx / 当前 Mpx」并拒绝创建”+
   * (cramped 只说明“现在放不下”，不代表可以把区域藏起来——藏屏正是旧版「点了没反应」的病根)。
   */
  const cramped = computed(() => issues.value.some(issue => issue.code === 'insufficient'))

  const insufficient = computed(() => {
    const first = issues.value.find((issue): issue is Extract<Issue, { code: 'insufficient' }> => issue.code === 'insufficient')
    return first ? { need: first.need.width, have: first.have.width } : null
  })

  const foldDetails = computed(() => {
    const info = insufficient.value
    return info ? { needed: info.need, have: info.have } : null
  })

  // ---------------------------------------------------------------------------
  // 视图：panes / tabs / floats（保持旧调用面）
  // ---------------------------------------------------------------------------
  const panesView = computed<Record<AreaId, { id: AreaId; tabs: SplitTab[]; activeTab: string | null }>>(() => {
    const view: Record<AreaId, { id: AreaId; tabs: SplitTab[]; activeTab: string | null }> = {}
    for (const area of areasOf(model.value)) {
      view[area.id] = {
        tabs: area.tabs.map(id => content.get(id)).filter((tab): tab is SplitTab => Boolean(tab)),
        activeTab: area.active,
        id: area.id,
      }
    }
    return view
  })

  const tabsView = computed<Array<{ tab: SplitTab; pane: string }>>(() => {
    const list: Array<{ tab: SplitTab; pane: string }> = []
    for (const area of areasOf(model.value)) {
      for (const id of area.tabs) {
        const tab = content.get(id)
        if (tab) list.push({ tab, pane: area.id })
      }
    }
    for (const box of model.value.floats) {
      const tab = content.get(box.id)
      // user:“pane 对浮层固定为 'float'”+(辅助对话与 App 都按这个口径找浮层内容)。
      if (tab) list.push({ tab, pane: 'float' })
    }
    return list
  })

  const floats = computed(() => model.value.floats.map(box => ({
    tab: content.get(box.id),
    rect: geometry.value.floats[box.id] ?? box.rect,
    yieldEnabled: box.yieldEnabled,
  })).filter(entry => Boolean(entry.tab)) as Array<{ tab: SplitTab; rect: Rect; yieldEnabled: boolean }>)

  const floatOrder = computed(() => model.value.floats.map(box => box.id))
  const floatFocus = computed(() => model.value.floatFocus)

  // Compatibility accessors keep the shared app and content hosts on the same layout model.
  const state = reactive({
    get hidden(): boolean { return hidden.value },
    set hidden(value: boolean) { hidden.value = Boolean(value) },
    get panes() { return panesView.value },
    get activePane(): string { return activePane.value },
    set activePane(value: string) { activePane.value = value },
    get prefs() { return { compact: model.value.prefs.compact } },
    get layout() { return layoutOf(model.value) },
    // user:“统一根入口：名称随主内容变化”+(内容层要读“主区现在显示什么”，这里给唯一出口；Agent 本体作为主区时返回 null)。
    get mainTab(): SplitTab | null {
      const main = areasOf(model.value).find(area => area.role === 'main')
      const tab = main?.active ? content.get(main.active) ?? null : null
      return tab && tab.kind !== 'agent' ? tab : null
    },
  })

  // ---------------------------------------------------------------------------
  // 标签 / 区域
  // ---------------------------------------------------------------------------
  function newTab(kind: SplitContent, resource: string, title?: string, extra?: Partial<SplitTab>): SplitTab {
    let id = ''
    do { seq += 1; id = `${kind}-${seq}` } while (content.has(id))
    const tab: SplitTab = {
      id,
      kind,
      title: title || resource || kind,
      resource,
      ...(workRoot?.value ? { root: workRoot.value } : {}),
      ...(projectId?.value ? { projectId: projectId.value } : {}),
      ...extra,
    }
    content.set(id, tab)
    return tab
  }

  /** user:“add(kind, resource, title?, pane?)”+(辅助对话还会补 sessionId/root，所以签名要留出后两位)。 */
  function add(
    kind: SplitContent,
    resource = '',
    title?: string,
    pane?: string,
    sessionId?: string,
    root?: string,
    projectId?: string,
  ): SplitTab | null {
    return addWithMetadata(kind, resource, title, pane, {
      ...(sessionId ? { sessionId } : {}),
      ...(root ? { root } : {}),
      ...(projectId ? { projectId } : {}),
    })
  }

  function addWithMetadata(kind: SplitContent, resource: string, title: string | undefined, pane: string | undefined, extra: Partial<SplitTab>): SplitTab | null {
    const target = pane && areasOf(model.value).some(area => area.id === pane) ? pane : activePane.value
    if (!areasOf(model.value).some(area => area.id === target)) return null
    const tab = newTab(kind, resource, title, extra)
    commit(addTab(model.value, target, surfaceRefOf(tab)))
    commit(selectTabIn(model.value, target, tab.id))
    activePane.value = target
    return tab
  }

  // user:“如果实在*过小*，可以在操作时弹一个错误提示”+(只在用户的分屏命令无法执行时通知宿主)。
  function canCommitSplit(): boolean {
    const { width, height } = currentViewport()
    if (width >= MIN_SPLIT_VIEWPORT && height >= MIN_SPLIT_VIEWPORT) return true
    options.onInsufficient?.()
    return false
  }

  function split(pane: string, edge: 'left' | 'right' | 'top' | 'bottom'): string | null {
    if (!canCommitSplit()) return null
    const before = new Set(areasOf(model.value).map(area => area.id))
    const result = splitArea(model.value, pane, edge)
    if (!result.ok) return null
    const created = areasOf(result.model).map(area => area.id).find(id => !before.has(id)) ?? null
    commit(result.model)
    return created
  }

  /** user:“splitAt(pane, ratio, edge)”+(先按引擎切分，再把这条切分线的比例改成 ratio)。 */
  function splitAt(pane: string, ratio: number, edge: 'left' | 'right' | 'top' | 'bottom'): string | null {
    if (!canCommitSplit()) return null
    const before = new Set(areasOf(model.value).map(area => area.id))
    const result = splitArea(model.value, pane, edge)
    if (!result.ok) return null
    const created = areasOf(result.model).map(area => area.id).find(id => !before.has(id)) ?? null
    const path = pathToArea(result.model.tree, created ?? pane)
    const parent = path.slice(0, -1)
    const final = parent.length ? resizeSplit(result.model, parent, ratio) : result.model
    commit(final)
    return created
  }

  // user:“第一次搜索建 agent-browser 分屏，之后 Agent 的标签都进这块”+
  // (只记在控制器里：Rust 标签不跨重启，重启后这块屏退回普通浏览器屏，不需要新的持久化字段)。
  const agentBrowserAreaId = ref<string | null>(null)

  function ensureAgentBrowserArea(): string | null {
    const areas = areasOf(model.value)
    const known = agentBrowserAreaId.value
      ? areas.find(area => area.id === agentBrowserAreaId.value)
      : undefined
    if (known) return known.id
    const created = split(activePane.value, 'right')
    if (!created) return null
    agentBrowserAreaId.value = created
    return created
  }

  /**
   * user:“开一个分屏，加一个标签页，由 agent 开的标签页打一个 tag：agent”+
   * (放不下时退回当前屏：宁可窄一点，也不要让 Agent 的页面“开了但看不见”)。
   */
  function addAgentBrowserTab(url = '', title = '', opener?: string): SplitTab | null {
    // user:“点 e26 其实**成功开了新标签页**”+(沿用来源标签的分屏和会话设置)。
    const source = opener ? tabsView.value.find(({ tab }) => tab.id === opener) : undefined
    const areaId = source?.pane ?? ensureAgentBrowserArea()
    return addWithMetadata('browser', url, title || url || 'Agent 浏览', areaId ?? activePane.value, {
      tag: 'agent',
      ...(source?.tab.profile ? { profile: source.tab.profile } : {}),
    })
  }

  function pathToArea(node: WorkspaceModel['tree'], areaId: AreaId): number[] {
    const walk = (current: WorkspaceModel['tree'], trail: number[]): number[] | null => {
      if (current.kind === 'leaf') return current.area.id === areaId ? trail : null
      return walk(current.a, [...trail, 0]) ?? walk(current.b, [...trail, 1])
    }
    return walk(node, []) ?? []
  }

  function activate(pane: string, tabId: string) {
    commit(selectTabIn(model.value, pane, tabId))
    activePane.value = pane
  }

  /** user:“快速精准高效的解决”+(导航后的实际标签值与存档走同一个更新入口)。 */
  function updateTabMetadata(id: string, patch: Partial<Pick<SplitTab, 'resource' | 'title' | 'zoom'>>) {
    const tab = content.get(id)
    if (!tab || Object.entries(patch).every(([key, value]) => tab[key as keyof typeof patch] === value)) return
    Object.assign(tab, patch)
    const next = cloneModel(model.value)
    next.surfaces[id] = surfaceRefOf(tab)
    commit(next)
  }

  function forgetSurface(next: WorkspaceModel, id: string) {
    next.floats = next.floats.filter(box => box.id !== id)
    delete next.surfaces[id]
    delete next.lastFloatRect[id]
    content.delete(id)
    parkedFloats.value = parkedFloats.value.filter(tab => tab.id !== id)
  }

  /** user:“快速精准高效的解决”+(保护通过后才移除标签；浮层关闭与收起分开，关闭会清理存档)。 */
  function closeTab(pane: string, tab: SplitTab, afterClose?: () => void) {
    const ownsTab = () => {
      const location = placeOf(model.value, tab.id)
      if (!location) return pane === 'parked' && parkedFloats.value.some(item => item.id === tab.id)
      return location.kind === 'area' ? location.areaId === pane : pane === 'float'
    }
    if (!ownsTab()) return
    runCloseGuards([tab.id], () => {
      if (!ownsTab()) return
      const next = pane === 'float' || pane === 'parked' ? cloneModel(model.value) : closeTabIn(model.value, pane, tab.id)
      forgetSurface(next, tab.id)
      commit(next)
      afterClose?.()
    })
  }

  /**
   * user:“更好的方式是折叠就等于关闭，这样可以通过右上角标签页抽屉直接再次将其显示出来”+
   * (关掉一块分屏时，标签先进「已收起」再收拢区域：抽屉里随时唤得回来，内容不销毁)。
   */
  function closePane(pane: string) {
    const area = areasOf(model.value).find(item => item.id === pane && item.role !== 'main')
    if (!area) return
    const ids = [...area.tabs]
    runCloseGuards(ids, () => {
      const current = areasOf(model.value).find(item => item.id === pane)
      if (!current || current.tabs.length !== ids.length || !ids.every(id => current.tabs.includes(id))) return
      collapseArea(pane)
    })
  }

  function show(pane?: string) {
    hidden.value = false
    if (pane && areasOf(model.value).some(area => area.id === pane)) activePane.value = pane
  }

  function toggle() { hidden.value = !hidden.value }

  function setCompact(value: boolean) {
    const next = cloneModel(model.value)
    next.prefs.compact = Boolean(value)
    commit(next)
  }


  // ---------------------------------------------------------------------------
  // 形态（split / float）与固定
  // ---------------------------------------------------------------------------
  function setSurfaceMode(surfaceId: string, mode: SurfaceMode, scope?: { sessionId?: string; root?: string }): { ok: boolean; reason?: string } {
    void scope
    if (mode === 'focus') return { ok: false, reason: 'unsupported-mode' }
    if (mode === 'split') {
      const place = placeOf(model.value, surfaceId)
      if (!place || place.kind === 'area') return { ok: true }
      const target = activePane.value
      const tab = content.get(surfaceId)
      if (!tab) return { ok: false, reason: 'surface-not-found' }
      commit(addTab(model.value, target, surfaceRefOf(tab)))
      return { ok: true }
    }
    // float：从区域摘掉、进浮层集合末尾并置顶聚焦。
    const place = placeOf(model.value, surfaceId)
    if (!place || place.kind === 'float') return place ? { ok: true } : { ok: false, reason: 'surface-not-found' }
    const tab = content.get(surfaceId)
    if (!tab) return { ok: false, reason: 'surface-not-found' }
    let next = cloneModel(model.value)
    const emptiedAuxIds: AreaId[] = []
    for (const area of areasOf(next)) {
      const index = area.tabs.indexOf(surfaceId)
      if (index < 0) continue
      area.tabs.splice(index, 1)
      if (area.active === surfaceId) area.active = area.tabs[Math.min(index, area.tabs.length - 1)] ?? null
      if (area.tabs.length === 0) {
        if (area.role === 'main') {
          if (!next.surfaces[seedId]) next.surfaces[seedId] = surfaceRefOf(seedTab)
          if (!content.has(seedId)) content.set(seedId, seedTab)
          area.tabs.push(seedId)
          area.active = seedId
        } else {
          emptiedAuxIds.push(area.id)
        }
      }
    }
    // user:“重写判定，满足随时固定的需求”+(辅区最后一个标签脱离为浮层后立即收拢空辅区，避免留下空白僵尸分屏占用固定判定预算)。
    for (const emptiedId of emptiedAuxIds) {
      if (areasOf(next).length <= 1) break
      const closed = closeArea(next, emptiedId)
      if (closed.ok) next = closed.model
    }
    const rect = geometry.value.areas[place.areaId]?.rect ?? DEFAULT_FLOAT_RECT
    const viewport = currentViewport()
    const maxW = Math.max(240, Math.round(viewport.width * 0.65))
    const maxH = Math.max(180, Math.round(viewport.height * 0.78))
    const width = Math.min(maxW, Math.max(460, Math.round(rect.width * 0.9)))
    const height = Math.min(maxH, Math.max(360, Math.round(rect.height * 0.72)))
    next.floats = [...next.floats, {
      id: surfaceId,
      rect: { x: rect.x + 24, y: rect.y + 24, width, height },
      yieldEnabled: false,
    }]
    next.floatFocus = surfaceId
    commit(next)
    return { ok: true }
  }

  function setMain(surfaceId: string | null) {
    const main = areasOf(model.value).find(area => area.role === 'main')
    if (!main) return
    // user:“依旧不可见，你来完成新布局系统的开发工作：# Sunday UI 与统一工作区布局系统”+
    // (切回 Agent 本体时必须把 main.active 清回 null；辅区提升为主区时把原主区内容换回辅区，实现真正主辅互换)。
    if (!surfaceId) {
      const next = cloneModel(model.value)
      next.floatFocus = null
      const nextMain = areasOf(next).find(area => area.role === 'main')
      if (nextMain) {
        // user:“从 Agent 可以切到 browser，但从 browser 切不回 Agent”+(即使 agent-main 曾被移出标签列表，切回 Agent 时也要补回并激活它，避免 normalizeWorkspace 又回退到 browser)。
        if (!next.surfaces[seedId]) next.surfaces[seedId] = surfaceRefOf(seedTab)
        if (!content.has(seedId)) content.set(seedId, seedTab)
        if (!nextMain.tabs.includes(seedId)) nextMain.tabs = [seedId, ...nextMain.tabs]
        nextMain.active = seedId
      }
      commit(next)
      return
    }
    const place = placeOf(model.value, surfaceId)
    const tab = content.get(surfaceId)
    if (!tab) return
    if (!place) { commit(selectTabIn(addTab(model.value, main.id, surfaceRefOf(tab)), main.id, surfaceId)); return }
    if (place.kind === 'float') {
      const next = cloneModel(model.value)
      next.floats = next.floats.filter(box => box.id !== surfaceId)
      if (next.floatFocus === surfaceId) next.floatFocus = null
      commit(selectTabIn(addTab(next, main.id, surfaceRefOf(tab)), main.id, surfaceId))
      return
    }
    if (place.areaId !== main.id) {
      // 主辅互换：内容集合整体换位，实例不变。
      const next = cloneModel(model.value)
      const nextMain = areasOf(next).find(area => area.role === 'main')!
      const prevMainId = nextMain.active
      const from = areasOf(next).find(area => area.id === place.areaId)!
      from.tabs = from.tabs.filter(id => id !== surfaceId)
      if (prevMainId && prevMainId !== surfaceId) {
        nextMain.tabs = nextMain.tabs.filter(id => id !== prevMainId)
        from.tabs = [...from.tabs, prevMainId]
        from.active = prevMainId
      } else if (from.active === surfaceId) {
        from.active = from.tabs[0] ?? null
      }
      let nextModel = selectTabIn(addTab(next, main.id, surfaceRefOf(tab)), main.id, surfaceId)
      if (from.tabs.length === 0 && areasOf(nextModel).length > 1) {
        const closed = closeArea(nextModel, from.id)
        if (closed.ok) nextModel = closed.model
      }
      commit(nextModel)
      return
    }
    commit(selectTabIn(model.value, main.id, surfaceId))
  }

  /** 还能不能再开一块屏（给根入口的菜单做可用性判断）。 */
  function canSplit(..._args: unknown[]): boolean { return areasOf(model.value).length < 4 }

  function mainAreaId(): string {
    return areasOf(model.value).find(area => area.role === 'main')?.id ?? 'main'
  }

  // user:“这里也只需要保留agent/browser”+(布局记在工作区，普通标签切换不改变布局和已打开内容的位置)。
  function setLayout(layout: WorkspaceLayout) {
    if (model.value.prefs.layout !== layout) {
      commit({ ...model.value, prefs: { ...model.value.prefs, layout } })
    }
    const pane = mainAreaId()
    show(pane)
    if (layout === 'agent') {
      setMain(null)
      return
    }
    const area = panesView.value[pane]
    const browser = area?.tabs.find(tab => tab.id === area.activeTab && tab.kind === 'browser')
      ?? area?.tabs.find(tab => tab.kind === 'browser')
    if (browser) activate(pane, browser.id)
    else add('browser', '', '新标签', pane)
  }

  /** user:“菜单分两部分：内容类型 / 打开方式（设为主区 / 打开为浮层 / 固定到工作区）”+(设为主区) */
  function openInMain(kind: SplitContent, resource = '', title?: string): void {
    const existing = tabsView.value.find(entry => entry.tab.kind === kind && entry.tab.resource === resource)
    if (existing) { setMain(existing.tab.id); return }
    const tab = add(kind, resource, title, mainAreaId())
    if (tab) setMain(tab.id)
  }

  /** 打开为浮层：先登记内容，再切到 float 形态。 */
  function openFloat(kind: SplitContent, resource = '', title?: string): void {
    const existing = tabsView.value.find(entry => entry.tab.kind === kind && entry.tab.resource === resource)
    const tab = existing ? existing.tab : add(kind, resource, title, activePane.value)
    if (tab) setSurfaceMode(tab.id, 'float')
  }

  /** 置顶某个浮层（旧入口 frontFloat 的同义实现）。 */
  function frontFloat(surfaceId: string): void { focusFloat(surfaceId) }

  function openPluginPage(page: unknown, pane?: string, scope?: { sessionId?: string; root?: string; filePath?: string; workRoot?: string; projectId?: string }) {
    const record = (page ?? {}) as { id?: string; label?: string; title?: string }
    const title = record.label || record.title || record.id || 'plugin'
    const resource = record.id || title
    const target = pane && areasOf(model.value).some(area => area.id === pane) ? pane : activePane.value
    add('plugin', resource, title, target, scope?.sessionId, scope?.root)
  }

  function currentViewport(): Rect {
    const winW = typeof window !== 'undefined' && window.innerWidth > 0 ? window.innerWidth : 1200
    const winH = typeof window !== 'undefined' && window.innerHeight > 0 ? window.innerHeight : 760
    return {
      x: 0,
      y: 0,
      width: Math.max(1, bounds.value.width > 0 ? bounds.value.width : winW),
      height: Math.max(1, bounds.value.height > 0 ? bounds.value.height : winH),
    }
  }

  /** user:“pin/unpin 接 ops.pinFloat/unpinArea 并显示预览条（预览 = 落地结果）”+ */
  function pinPlan(surfaceId: string): { ok: boolean; rect?: Rect; areaId?: AreaId; reason?: string } {
    const viewport = currentViewport()
    const result = pinFloat(model.value, surfaceId, viewport, limits)
    if (!result.ok) return { ok: false, reason: result.reason }
    const areaId = placeOf(result.model, surfaceId)
    return { ok: true, rect: result.preview, areaId: areaId?.kind === 'area' ? areaId.areaId : undefined }
  }

  function pinCommit(surfaceId: string): { ok: boolean; reason?: string } {
    pinPreview.value = null
    const applied = pinFloat(model.value, surfaceId, currentViewport(), limits)
    if (!applied.ok) {
      if (applied.reason === 'insufficient') options.onInsufficient?.()
      return { ok: false, reason: applied.reason }
    }
    commit(applied.model)
    return { ok: true }
  }

  function unpinPlan(areaId: string): { ok: boolean; rect?: Rect; reason?: string } {
    const viewport = currentViewport()
    const area = areasOf(model.value).find(item => item.id === areaId)
    const rect = geometry.value.areas[areaId]?.rect
    if (!area) return { ok: false, reason: 'area-not-found' }
    if (!rect) return { ok: false, reason: 'no-rect' }
    return { ok: true, rect: { x: rect.x + 24, y: rect.y + 24, width: Math.max(1, rect.width * .46), height: Math.max(1, rect.height * .52) } }
  }

  function unpinCommit(areaId: string): { ok: boolean; reason?: string } {
    const viewport = currentViewport()
    const result = unpinArea(model.value, areaId, viewport)
    if (!result.ok) return { ok: false, reason: result.reason }
    commit(result.model)
    return { ok: true }
  }

  // 浮层操作
  function focusFloat(surfaceId: string) { commit(floatToFront(model.value, surfaceId)) }
  function sendFloatToBack(surfaceId: string) { commit(floatToBack(model.value, surfaceId)) }
  function cycleFloats(direction: 1 | -1 = 1) { commit(cycleFloatFocus(model.value, direction)) }
  function moveFloat(surfaceId: string, rect: Rect) { commit(setFloatRect(model.value, surfaceId, rect)) }
  function setFloatYieldEnabled(surfaceId: string, enabled: boolean) { commit(setFloatYield(model.value, surfaceId, enabled)) }

  /** user:“关闭=收起（内容不销毁，可唤回）”+(从浮层集合摘掉，内容留在实例表里)。 */
  function collapseFloat(surfaceId: string) {
    const tab = content.get(surfaceId)
    const next = cloneModel(model.value)
    next.floats = next.floats.filter(box => box.id !== surfaceId)
    if (next.floatFocus === surfaceId) next.floatFocus = next.floats[next.floats.length - 1]?.id ?? null
    commit(next)
    if (tab && !parkedFloats.value.some(item => item.id === tab.id)) parkedFloats.value = [...parkedFloats.value, tab]
  }

  function reviveFloat(surfaceId: string) {
    const tab = content.get(surfaceId)
    if (!tab) return
    if (model.value.floats.some(box => box.id === surfaceId)) { focusFloat(surfaceId); return }
    const next = cloneModel(model.value)
    next.floats = [...next.floats, { id: surfaceId, rect: { ...DEFAULT_FLOAT_RECT }, yieldEnabled: false }]
    next.floatFocus = surfaceId
    commit(next)
    parkedFloats.value = parkedFloats.value.filter(item => item.id !== surfaceId)
  }

  // 交互相位
  function beginInteraction(kind: Exclude<WorkspacePhase, 'idle'>) { phase.value = kind; interacting.value = true }
  function endInteraction(commitFn?: () => void) {
    if (commitFn) commitFn()
    phase.value = 'idle'
    interacting.value = false
  }

  /** 分隔条拖动：只改 ratio，几何由 compute 算。 */
  function resizeDivider(path: number[], ratio: number) { commit(resizeSplit(model.value, path, ratio)) }
  /**
   * user:“更好的方式是折叠就等于关闭，这样可以通过右上角标签页抽屉直接再次将其显示出来”+
   * (收起一块分屏 = 关掉这块分屏 + 把它的标签放进「已收起」：内容不销毁、也不留在看不见的状态，
   *  抽屉里点一下就能唤回来；拖动分隔条永远不会走到这里)。
   */
  function collapseArea(pane: string) {
    const area = areasOf(model.value).find(item => item.id === pane && item.role !== 'main')
    if (!area) return
    const tabs = area.tabs.map(id => content.get(id)).filter((tab): tab is SplitTab => Boolean(tab))
    const result = closeArea(model.value, pane)
    if (!result.ok) return
    commit(result.model)
    if (!tabs.length) return
    const parked = parkedFloats.value.filter(item => !tabs.some(tab => tab.id === item.id))
    parkedFloats.value = [...parked, ...tabs]
  }

  /**
   * user:“拖标签：同区排序、跨区移动”+(引擎的 moveTab 已经处理“源区空了就收拢”，
   * 这里只负责把 index 翻成区域 id，并保证 active 跟着走)。
   */
  function moveTab(from: { pane: string; index: number }, to: { pane: string; index: number }) {
    commit(moveTabIn(model.value, { areaId: from.pane, index: from.index }, { areaId: to.pane, index: to.index }))
  }

  function reorderTab(pane: string, from: number, to: number) {
    const area = areasOf(model.value).find(item => item.id === pane)
    if (!area) return
    const tabs = [...area.tabs]
    const [moved] = tabs.splice(from, 1)
    if (!moved) return
    tabs.splice(to, 0, moved)
    const next = cloneModel(model.value)
    const target = areasOf(next).find(item => item.id === pane)!
    target.tabs = tabs
    commit(next)
  }

  function setBounds(rect: Rect) {
    // 值相等短路：外壳滚动/输入法弹出会反复调它，不短路就会变成重排放大器。
    if (bounds.value.x === rect.x && bounds.value.y === rect.y
      && bounds.value.width === rect.width && bounds.value.height === rect.height) return
    bounds.value = { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
  }

  // 内容页和文件编辑器可以各自登记守卫，按登记顺序确认后才关闭。
  const guards = new Map<string, Set<CloseGuard>>()
  function registerGuard(id: string, guard: CloseGuard) {
    const list = guards.get(id) ?? new Set<CloseGuard>()
    list.add(guard)
    guards.set(id, list)
    return () => {
      list.delete(guard)
      if (list.size === 0 && guards.get(id) === list) guards.delete(id)
    }
  }

  function runCloseGuards(ids: string[], proceed: () => void) {
    const checks = ids.flatMap(id => [...(guards.get(id) ?? [])])
    const run = (index: number) => {
      const check = checks[index]
      if (!check) { proceed(); return }
      let accepted = false
      check(() => {
        if (accepted) return
        accepted = true
        run(index + 1)
      })
    }
    run(0)
  }

  // ---------------------------------------------------------------------------
  // 便捷派生：外壳直接读这些，不再自己算
  // ---------------------------------------------------------------------------
  const areas = computed(() => areasOf(model.value).map(area => ({
    area,
    geometry: geometry.value.areas[area.id],
    tabs: area.tabs.map(id => content.get(id)).filter((tab): tab is SplitTab => Boolean(tab)),
    active: area.active ? content.get(area.active) ?? null : null,
  })))

  /** 按 surface id 查它的落点（内容组件判断自己该不该显示）。 */
  function placementOf(surfaceId: string) { return placeOf(model.value, surfaceId) }

  /** 网页可见性输入：矩形 + 区域可见 + 浮层计数 + 相位的唯一出口。 */
  function areaVisible(areaId: string): boolean {
    if (hidden.value) return false
    return Boolean(geometry.value.areas[areaId])
  }

  watch(() => model.value.prefs.compact, () => { save() })

  const controller = {
    // 状态（旧调用面）
    state,
    tabs: tabsView,
    hidden,
    interacting,
    interactionPhase: phase,
    cramped,
    issues,
    insufficient,
    foldDetails,

    // 几何
    model,
    geometry,
    areas,
    bounds,
    limits,
    setBounds,
    placementOf,
    areaVisible,
    // 标签 / 区域
    add,
    split,
    splitAt,
    ensureAgentBrowserArea,
    addAgentBrowserTab,
    activate,
    closeTab,
    closePane,
    updateTabMetadata,
    show,
    toggle,
    setCompact,
    setSurfaceMode,
    setMain,
    canSplit,
    openInMain,
    setLayout,
    openFloat,
    frontFloat,
    openPluginPage,
    // 浮层
    floats,
    floatOrder,
    floatFocus,
    parkedFloats,
    focusFloat,
    sendFloatToBack,
    cycleFloats,
    moveFloat,
    setFloatYieldEnabled,
    collapseFloat,
    reviveFloat,
    pinPreview,
    pinPlan,
    pinCommit,
    unpinPlan,
    unpinCommit,
    // 交互
    beginInteraction,
    endInteraction,
    resizeDivider,
    collapseArea,
    moveTab,
    reorderTab,
    // 内容守卫
    registerGuard,
    // 存档
    save,
    storageKey: WORKSPACE_STORAGE_KEY,
  }
  // user:“内容组件靠注入拿控制器，不需要知道控制器在哪儿创建”+
  // (旧内核的 SplitWorkspaceKey 已下线；非组件环境（单测）会静默跳过)。
  if (hasInjectionContext()) provide(WorkspaceKey, controller as unknown as WorkspaceController)
  return controller
}

/**
 * user:“浮层拖动/缩放跟手（每次变更即写、每帧最多一次、矩形不变不写，松手补最后一帧）”+
 * (这三条正是“容器出去了、网页还在原地，松手才跟上”的解药：
 *  变更立刻排队 → 同一帧只下发一次 → 和上一帧一样就一个字节都不写。
 *  松手时 `flush()` 把被合并掉的那一次补上。写成纯函数，行为可以直接断言)。
 */
export interface RectQueue {
  schedule: (rect: Rect) => void
  /** 立刻下发挂起的最后一帧（松手时用）。 */
  flush: () => void
  dispose: () => void
  readonly pending: Rect | null
}

export function createRectQueue(
  emit: (rect: Rect) => void,
  opts: { raf?: (callback: () => void) => number; cancelRaf?: (handle: number) => void; initial?: Rect } = {},
): RectQueue {
  const hasRaf = typeof requestAnimationFrame === 'function'
  const raf = opts.raf ?? (hasRaf ? (callback: () => void) => requestAnimationFrame(callback) : (callback: () => void) => { callback(); return 0 })
  const cancelRaf = opts.cancelRaf ?? (hasRaf ? (handle: number) => cancelAnimationFrame(handle) : () => {})
  let last: Rect | null = opts.initial ? { ...opts.initial } : null
  let pending: Rect | null = null
  let handle = 0
  let disposed = false

  const same = (a: Rect, b: Rect) => a.x === b.x && a.y === b.y && a.width === b.width && a.height === b.height

  function commitValue(value: Rect) {
    if (last && same(value, last)) return
    last = value
    emit(value)
  }

  return {
    schedule(rect: Rect) {
      if (disposed) return
      if (last && same(rect, last)) return
      pending = { ...rect }
      if (handle) return
      handle = raf(() => {
        handle = 0
        const value = pending
        pending = null
        if (value) commitValue(value)
      })
    },
    flush() {
      if (handle) { cancelRaf(handle); handle = 0 }
      const value = pending
      pending = null
      if (value) commitValue(value)
    },
    dispose() {
      disposed = true
      if (handle) cancelRaf(handle)
      handle = 0
      pending = null
    },
    get pending() { return pending },
  }
}

/** 键盘意图：纯映射，组件只负责执行（这样按键表可以逐条断言）。 */
export type WorkspaceIntent =
  | { kind: 'split'; edge: 'right' | 'bottom' }
  | { kind: 'close-aux' }
  | { kind: 'select-area'; index: number }
  | { kind: 'cycle-tab'; reverse: boolean }
  | { kind: 'escape' }
  | null

export function keyboardIntent(input: {
  key: string
  ctrlKey?: boolean
  metaKey?: boolean
  shiftKey?: boolean
  altKey?: boolean
}): WorkspaceIntent {
  const meta = Boolean(input.ctrlKey || input.metaKey)
  if (meta && input.key === '\\') return { kind: 'split', edge: input.shiftKey ? 'bottom' : 'right' }
  if (meta && (input.key === 'w' || input.key === 'W')) return { kind: 'close-aux' }
  if (input.altKey && /^[1-9]$/.test(input.key)) return { kind: 'select-area', index: Number(input.key) - 1 }
  if (meta && input.key === 'Tab') return { kind: 'cycle-tab', reverse: Boolean(input.shiftKey) }
  if (input.key === 'Escape') return { kind: 'escape' }
  return null
}

export type WorkspaceController = ReturnType<typeof useWorkspace>
