/**
 * Ping 独立运行时：轮盘、屏幕标注、截图、标记动画、会话卡片与目标会话路由。
 *
 * user:"ping 环跟桌宠应当是解耦的，它们是两个独立的功能，我只是在这一次设计方案中把它写在一起了"+
 * (本模块不 import engine/*、不 import usePetRuntime、不持有任何宠物实例——
 *  零宠物时 Ping 完整可用；桌宠页面（usePetRuntime/PetSurface）只做组合。
 *  确实需要桌宠参与的子功能全部显式化成可选注入：
 *  - customActions: 自定义扇区触发的桌宠/覆盖层操作（设置/导入/显隐宠物/刷新L3/地形线/关闭覆盖层），
 *    没注入的动作只报错不静默；
 *  - notify: 需要用户注意的提示交给组合方展示（桌宠在就进气泡，不在就自行处理）。
 * 系统能力（截图、快捷键）走 bridge，会话通道走 agent/host——两者都不是桌宠引擎。)
 */
import { computed, reactive, ref } from 'vue'
import type { PingConfig, PingSectorConfig } from '../config.ts'
import * as bridge from '../bridge.ts'
import type { CapturedFrame, MonitorInfo, OverlayBounds } from '../bridge.ts'
import type { PetAgentClient, PetScreenshotUpload } from '../agent/client.ts'
import { type SessionChannel, type PetAgentHost } from '../agent/host.ts'
import { ringSectors, sectorIndexAt } from './ringModel.ts'

export interface PingMarker {
  x: number
  y: number
  kind: 'question' | 'exclamation' | 'note' | 'select'
  label: string
  color: string
}

export interface PingResultPayload {
  sector: PingSectorConfig
  prompt: string
  marker: PingMarker | null
  image: Blob | null
  imageMeta: { monitor: MonitorInfo | null; x: number; y: number; width: number; height: number } | null
}

export interface CardState {
  sessionId: string
  projectId: string | null
  pinned: boolean
  containerX: number
  containerY: number
  cardX: number
  cardY: number
  title: string
  unread: number
  draft: string
  pendingAttachments: PetScreenshotUpload[]
}

/** 自定义 Ping 项可触发的桌宠/覆盖层操作：由组合方注入，Ping 自己不实现。 */
export interface PingCustomActions {
  openSettings(): void
  openImporter(): Promise<void>
  togglePets(): void | Promise<void>
  refreshTerrain(): Promise<void>
  toggleTerrainLines(): void
  hideOverlay(): Promise<void>
}

export interface PingRuntimeDeps {
  /**
   * 共享持久配置的根对象（结构上只需要 enabled + ping 两块）。
   * 传根而不传 config.ping 的快照：loadConfig 迁移时会整体替换 ping 子对象，
   * 持根引用才能一直读到最新值。
   */
  config: { enabled: boolean; ping: PingConfig }
  /** 覆盖层物理像素边界（共享响应式对象）。 */
  overlay: OverlayBounds
  /** 显示器列表读取器（卡片优先停靠在鼠标所在显示器）。 */
  monitors: () => MonitorInfo[]
  /** 光标物理像素坐标（共享响应式对象；Ping 只读）。 */
  cursor: { readonly x: number; readonly y: number }
  /** 会话宿主与客户端：Ping 的会话能力来源，未连接时为 null。 */
  getHost: () => PetAgentHost | null
  getClient: () => PetAgentClient | null
  /** 配置落盘调度（去抖保存由组合方实现）。 */
  save: () => void
  /** 错误上报（与桌宠共用同一个错误面板）。 */
  report: (scope: string, error: unknown) => void
  /** 轻量通知（如「Ping 已排队」）；桌宠在场时进气泡系统。petId 用于气泡锚定（可空）。 */
  notify: (input: { petId?: string; sessionId: string; title: string; body: string }) => void
  /** 轮盘「切换会话」扇区打开选择器的入口（选择器 UI 由组合方提供）。 */
  openSessionPicker: (projectId?: string) => void
  /**
   * 「框选」扇区打开独立截图窗口的入口。
   * user:“重新设计与实现 Ping 的框选工具”+(框选不再在 Ping 覆盖层里做，
   * 由组合方打开一个可聚焦、可被看门狗回收的独立窗口。)
   */
  openCapture?: () => void | Promise<void>
  /** 三级会话选择：项目列表（第 2 级轮盘）。 */
  listProjects?: () => Promise<{ id: string; name: string }[]>
  /** 三级会话选择：项目内会话（第 3 级轮盘，取最近 6 条 + 更多）。 */
  listSessions?: (projectId: string) => Promise<{ id: string; title: string; updatedAt?: string | number }[]>
  /** 自定义扇区动作表：缺哪个动作，触发时就报「未绑定」。 */
  customActions: Partial<PingCustomActions>
}

export function createPingRuntime(deps: PingRuntimeDeps) {
  const ring = reactive({
    visible: false,
    x: 0,
    y: 0,
    pointerX: 0,
    pointerY: 0,
    hovered: '' as string,
    sectors: [] as PingSectorConfig[],
    /** 0 = 主轮盘；1 = 从某个扇区展开的子轮盘。 */
    depth: 0,
    parentId: '',
  })

  // user:“第二级和第三级依旧还是扇形或完整圆环”“它不会使之前的圆环消失”+
  // (二三级是同心的外圈圆环：悬停一级项时在更大的半径上长出项目环，悬停项目
  //  再长出会话环；所有层级同时可见，命中也按各自的半径区间判断。)
  const tierState = reactive({
    /** 正在展开子环的一级扇区 id（保持高亮）。 */
    expanded: '' as string,
    l2: {
      visible: false,
      radius: 0,
      width: 0,
      /** 这段局部扇环的起始角（弧度，屏幕坐标）与跨度。 */
      start: 0,
      span: 0,
      /** 每个子项占用的角度（弧度），按文字长度自适应分配。 */
      slots: [] as number[],
      sectors: [] as PingSectorConfig[],
      hovered: '',
      projectId: '',
    },
    l3: {
      visible: false,
      radius: 0,
      width: 0,
      start: 0,
      span: 0,
      slots: [] as number[],
      sectors: [] as PingSectorConfig[],
      hovered: '',
      projectId: '',
    },
  })
  let loadingTier2 = false
  let loadingTier3 = ''

  /** 请求进行中的轻量标记动画：只做视觉确认，绝不阻塞提交。 */
  const markerFx = reactive({
    visible: false,
    x: 0,
    y: 0,
    kind: 'question' as PingMarker['kind'],
    label: '',
    color: '#6AA8FF',
    startedAt: 0,
  })

  const capture = reactive({
    busy: false,
    lastError: '',
    lastAt: 0,
    lastMonitor: null as MonitorInfo | null,
  })

  const pending = reactive({
    /** 「对话」Ping 会先把截图放进输入区但不发送。 */
    attach: null as PetScreenshotUpload | null,
  })

  const cards = reactive(new Map<string, CardState>())
  const activeCardSessionId = ref<string | null>(null)
  const activeCardSession = computed({
    get: () => activeCardSessionId.value,
    set: (value: string | null) => { activeCardSessionId.value = value },
  })

  /** 会话宿主/客户端的只读视图（组合方boot完成后才有值）。 */
  const host = computed(() => deps.getHost())
  const client = computed(() => deps.getClient())

  function sectorAt(x: number, y: number): string {
    const sectors = ring.sectors
    if (sectors.length === 0) return ''
    const index = sectorIndexAt(
      x - ring.x,
      y - ring.y,
      sectors.length,
      deps.config.ping.radius,
      deps.config.ping.ringWidth,
    )
    return index < 0 ? '' : (sectors[index]?.id || '')
  }

  /** 切换会话固定放在正右方（3 点钟），它展开的外圈更平、更好读。 */
  function orderRootSectors(sectors: PingSectorConfig[]): PingSectorConfig[] {
    const index = sectors.findIndex(sector => sector.kind === 'switch')
    if (index < 0 || sectors.length < 2) return sectors
    const step = (Math.PI * 2) / sectors.length
    const target = ((Math.round((Math.PI / 2) / step - 0.5) % sectors.length) + sectors.length) % sectors.length
    if (index === target) return sectors
    const ordered = [...sectors]
    const [switcher] = ordered.splice(index, 1)
    ordered.splice(target, 0, switcher)
    return ordered
  }

  function openRing(x: number, y: number): void {
    // Ping 与桌宠解耦：config.enabled 只控制桌宠模块，Ping 环照常可用。
    // user:“你看看 ping 环 要不也自己做窗口？”+(桌宠禁用不影响 Ping 入口。)
    // user:“可以自由自定义扇区数量，不限制 4～8”+(全部启用项参与排布)
    ring.sectors = orderRootSectors(ringSectors(deps.config.ping.sectors, null))
    ring.depth = 0
    ring.parentId = ''
    collapseTiers()
    if (ring.sectors.length === 0) return
    ring.visible = true
    ring.x = x
    ring.y = y
    ring.pointerX = x
    ring.pointerY = y
    ring.hovered = ''
  }

  function cancelRing(): void {
    ring.visible = false
    ring.hovered = ''
    ring.depth = 0
    ring.parentId = ''
    collapseTiers()
  }

  function collapseTiers(): void {
    tierState.expanded = ''
    tierState.l2.visible = false
    tierState.l2.sectors = []
    tierState.l2.slots = []
    tierState.l2.hovered = ''
    tierState.l2.projectId = ''
    tierState.l3.visible = false
    tierState.l3.sectors = []
    tierState.l3.slots = []
    tierState.l3.hovered = ''
    tierState.l3.projectId = ''
  }

  function openSubRing(sector: PingSectorConfig, x: number, y: number): boolean {
    const children = ringSectors(deps.config.ping.sectors, sector)
    if (children.length === 0) {
      deps.report('ping:subring', new Error(`子轮盘「${sector.subring || sector.id}」里没有可用项`))
      return false
    }
    ring.sectors = children
    ring.depth = 1
    ring.parentId = sector.id
    ring.visible = true
    ring.x = x
    ring.y = y
    ring.hovered = ''
    return true
  }

  /** 覆盖层光标移动时同步轮盘悬停态；由组合方的事件循环转发，Ping 不自己监听光标。 */
  function onCursorMoved(x: number, y: number): void {
    if (!ring.visible) return
    ring.pointerX = x
    ring.pointerY = y
    ring.hovered = sectorAt(x, y)

    // 第三级优先：光标落在会话环上。
    const l3Hover = tierSectorAt(x, y, tierState.l3)
    if (l3Hover) {
      tierState.l3.hovered = l3Hover
      return
    }
    tierState.l3.hovered = ''
    // 第二级：光标落在项目环上；悬停项目展开第三级。
    const l2Hover = tierSectorAt(x, y, tierState.l2)
    if (l2Hover) {
      tierState.l2.hovered = l2Hover
      const item = tierState.l2.sectors.find(sector => sector.id === l2Hover)
      const projectId = item?.id.startsWith('project:') ? item.id.slice('project:'.length) : ''
      if (projectId) void openTier3(projectId)
      return
    }
    tierState.l2.hovered = ''

    // 一级：悬停「切换会话」展开项目环；悬停其他项收起整条链。
    if (ring.hovered) {
      const sector = ring.sectors.find(item => item.id === ring.hovered)
      if (sector?.kind === 'switch') {
        void openTier2()
      } else {
        collapseTiers()
      }
      return
    }

    // 光标在环与环之间的缝隙：只要还在链的范围内就保持，离开就收起。
    const distance = Math.hypot(x - ring.x, y - ring.y)
    const chainOuter = tierState.l3.visible
      ? tierState.l3.radius + tierState.l3.width / 2
      : tierState.l2.visible
        ? tierState.l2.radius + tierState.l2.width / 2
        : 0
    if (chainOuter > 0 && distance <= chainOuter + 8) return
    collapseTiers()
  }

  /** 把角度归一化到 [0, 2π)。 */
  function normalizeAngle(angle: number): number {
    let value = angle % (Math.PI * 2)
    if (value < 0) value += Math.PI * 2
    return value
  }

  /** 从圆心沿 dir 方向到屏幕边缘的距离（物理像素）。 */
  function rayDistance(cx: number, cy: number, dir: number): number {
    const dx = Math.cos(dir)
    const dy = Math.sin(dir)
    const minX = deps.overlay.x
    const minY = deps.overlay.y
    const maxX = deps.overlay.x + deps.overlay.width
    const maxY = deps.overlay.y + deps.overlay.height
    let t = Number.POSITIVE_INFINITY
    if (dx > 1e-6) t = Math.min(t, (maxX - cx) / dx)
    else if (dx < -1e-6) t = Math.min(t, (minX - cx) / dx)
    if (dy > 1e-6) t = Math.min(t, (maxY - cy) / dy)
    else if (dy < -1e-6) t = Math.min(t, (minY - cy) / dy)
    return Math.max(0, t)
  }

  /**
   * 子菜单布局：角度随项数增长，半径随文字长度增长，内环半径保持不变。
   *
   * user:“这个东西长就加半径，这个东西高再加角度”“一个环形有两个半径，
   * 两个半径一块儿加，能放得下就见鬼了！内环半径就不能变”+
   * (内缘贴着上一级外缘不动，只把外缘往外扩：带宽增加，文字所在的半径变大，
   *  从而获得更多弧长；文字放不下就截断，不允许整体向外飘。)
   */
  function layoutTier(
    sectors: PingSectorConfig[],
    parentMid: number,
    baseInner: number,
    desiredWidth: number,
  ): { width: number; radius: number; start: number; span: number; slots: number[] } | null {
    const count = sectors.length
    if (count === 0) return null
    // 高度：项数越多，角度范围越大（上限约 120°）。
    const span = Math.min(2.1, Math.max(0.7, count * 0.3))
    const slot = span / count
    const slots = new Array(count).fill(slot)
    // 屏幕在该弧段方向上的可用半径。
    let available = Number.POSITIVE_INFINITY
    for (const ratio of [0.05, 0.3, 0.5, 0.7, 0.95]) {
      available = Math.min(
        available,
        rayDistance(ring.x, ring.y, parentMid - span / 2 + span * ratio),
      )
    }
    // 横向长度：按 12px 字号估算每项需要的弧长，据此决定外缘扩到多远。
    const estimateSize = 12
    const needPerItem = Math.max(
      56,
      ...sectors.map(sector => estimateLabelWidth(sector.label, estimateSize) + 18),
    )
    const neededRadius = needPerItem / slot
    const minWidth = 40
    const maxWidth = 96
    let width = Math.max(minWidth, 2 * (neededRadius - baseInner))
    width = Math.min(width, maxWidth, Math.max(minWidth, available - baseInner - 8))
    width = Math.max(minWidth, width)
    // 内缘固定 = baseInner；外缘 = baseInner + width。
    const radius = baseInner + width / 2
    return {
      width,
      radius,
      start: normalizeAngle(parentMid - span / 2),
      span,
      slots,
    }
  }

  function tierItem(id: string, label: string, icon: string): PingSectorConfig {
    return {
      id,
      label: label.trim(),
      icon,
      kind: 'custom',
      color: '#FFFFFF',
      enabled: true,
    }
  }

  /** 估算文字宽度：中文按 1 个字宽，西文按 0.58 个字宽。 */
  function estimateLabelWidth(text: string, fontSize: number): number {
    let units = 0
    for (const char of text) {
      units += /[⺀-鿿＀-￯]/.test(char) ? 1 : 0.58
    }
    return units * fontSize
  }

  /** 外圈命中：本环半径区间 + 局部扇环的角度范围内。 */
  function tierSectorAt(
    x: number,
    y: number,
    tier: {
      visible: boolean
      radius: number
      width: number
      start: number
      span: number
      slots: number[]
      sectors: PingSectorConfig[]
    },
  ): string {
    if (!tier.visible || tier.sectors.length === 0 || tier.width <= 0) return ''
    const dx = x - ring.x
    const dy = y - ring.y
    const distance = Math.hypot(dx, dy)
    const inner = tier.radius - tier.width / 2
    const outer = tier.radius + tier.width / 2
    if (distance < inner - 10 || distance > outer + 10) return ''
    const relative = normalizeAngle(Math.atan2(dy, dx) - tier.start)
    if (relative > tier.span) return ''
    let acc = 0
    for (let index = 0; index < tier.slots.length; index += 1) {
      acc += tier.slots[index]
      if (relative <= acc) return tier.sectors[index]?.id || ''
    }
    return tier.sectors[tier.sectors.length - 1]?.id || ''
  }

  /** 第二级：以父扇区中心角为轴，在一级外缘展开的局部扇环。 */
  async function openTier2(): Promise<void> {
    if (tierState.l2.visible || loadingTier2) return
    const parentId = ring.hovered
    const parentIndex = ring.sectors.findIndex(sector => sector.id === parentId)
    if (parentIndex < 0) return
    loadingTier2 = true
    try {
      const projects = deps.listProjects ? await deps.listProjects() : []
      if (projects.length === 0) return
      const max = 7
      const sectors = projects
        .slice(0, max)
        .map(project => tierItem(`project:${project.id}`, project.name, ''))
      if (projects.length > max) sectors.push(tierItem('more', '更多…', ''))
      const parentStep = (Math.PI * 2) / ring.sectors.length
      const parentMid = -Math.PI / 2 + (parentIndex + 0.5) * parentStep
      const baseOuter = deps.config.ping.radius + deps.config.ping.ringWidth / 2
      const desiredWidth = Math.max(46, deps.config.ping.ringWidth * 2.2)
      const layout = layoutTier(sectors, parentMid, baseOuter + 8, desiredWidth)
      if (!layout) return
      tierState.l2.radius = layout.radius
      tierState.l2.width = layout.width
      tierState.l2.start = layout.start
      tierState.l2.span = layout.span
      tierState.l2.slots = layout.slots
      tierState.l2.sectors = sectors
      tierState.l2.hovered = ''
      tierState.l2.projectId = ''
      tierState.l2.visible = true
      tierState.expanded = parentId
    } catch (error) {
      deps.report('ping:tier2', error)
    } finally {
      loadingTier2 = false
    }
  }

  /** 第三级：以选中的项目项为中心角，在二级外缘再展开一层局部扇环。 */
  async function openTier3(projectId: string): Promise<void> {
    if (tierState.l3.visible && tierState.l3.projectId === projectId) return
    if (loadingTier3 === projectId) return
    const projectIndex = tierState.l2.sectors.findIndex(
      sector => sector.id === `project:${projectId}`,
    )
    if (projectIndex < 0) return
    loadingTier3 = projectId
    try {
      const sessions = deps.listSessions ? await deps.listSessions(projectId) : []
      const sorted = [...sessions].sort((a, b) => timeValue(b.updatedAt) - timeValue(a.updatedAt))
      if (sorted.length === 0) {
        tierState.l3.visible = false
        tierState.l3.sectors = []
        tierState.l3.hovered = ''
        tierState.l3.projectId = projectId
        return
      }
      const max = 6
      // user:“会话名称那儿不用带图标，一个文本就行了”+(三级会话项只放文字)。
      const sectors = sorted
        .slice(0, max)
        .map(session => tierItem(`session:${session.id}`, session.title || session.id.slice(0, 8), ''))
      if (sorted.length > max) sectors.push(tierItem('more', '更多…', ''))
      let before = 0
      for (let index = 0; index < projectIndex; index += 1) {
        before += tierState.l2.slots[index] || 0
      }
      const projectSlot = tierState.l2.slots[projectIndex] || 0.3
      const parentMid = tierState.l2.start + before + projectSlot / 2
      const baseInner = tierState.l2.radius + tierState.l2.width / 2 + 8
      const desiredWidth = tierState.l2.width || Math.max(46, deps.config.ping.ringWidth * 2.2)
      const layout = layoutTier(sectors, parentMid, baseInner, desiredWidth)
      if (!layout) {
        tierState.l3.visible = false
        tierState.l3.sectors = []
        return
      }
      tierState.l3.radius = layout.radius
      tierState.l3.width = layout.width
      tierState.l3.start = layout.start
      tierState.l3.span = layout.span
      tierState.l3.slots = layout.slots
      tierState.l3.sectors = sectors
      tierState.l3.hovered = ''
      tierState.l3.projectId = projectId
      tierState.l3.visible = true
    } catch (error) {
      deps.report('ping:tier3', error)
    } finally {
      loadingTier3 = ''
    }
  }

  function timeValue(value?: string | number): number {
    if (typeof value === 'number') return value
    if (typeof value === 'string') {
      const parsed = Date.parse(value)
      return Number.isFinite(parsed) ? parsed : 0
    }
    return 0
  }

  /** 自定义 Ping 项的落地动作：只做本地操作，不发请求。 */
  async function runCustomSector(sector: PingSectorConfig): Promise<void> {
    const action = sector.action || ''
    switch (action) {
      case 'settings':
        deps.customActions.openSettings?.()
        return
      case 'import':
        await deps.customActions.openImporter?.()
        return
      case 'toggle-pets':
        await deps.customActions.togglePets?.()
        return
      case 'refresh-l3':
        await deps.customActions.refreshTerrain?.()
        return
      case 'debug-terrain':
        deps.customActions.toggleTerrainLines?.()
        return
      case 'hide-overlay':
        await deps.customActions.hideOverlay?.()
        return
      default: {
        // 未配置动作时把 icon 当作提示，不静默吞掉点击。
        deps.report('ping:custom', new Error(`自定义项「${sector.label}」还没有绑定动作`))
      }
    }
  }

  function showMarker(marker: PingMarker): void {
    markerFx.visible = true
    markerFx.x = marker.x
    markerFx.y = marker.y
    markerFx.kind = marker.kind
    markerFx.label = marker.label
    markerFx.color = marker.color
    markerFx.startedAt = Date.now()
    const duration = Math.max(600, deps.config.ping.markerMs)
    window.setTimeout(() => {
      if (Date.now() - markerFx.startedAt >= duration - 20) markerFx.visible = false
    }, duration)
  }

  async function commitRing(x: number, y: number): Promise<void> {
    if (!ring.visible) return
    // 第三级：会话环上的叶子优先执行（最近 6 条里的某一条）。
    if (tierState.l3.visible && tierState.l3.hovered) {
      const item = tierState.l3.sectors.find(sector => sector.id === tierState.l3.hovered)
      const projectId = tierState.l3.projectId
      cancelRing()
      if (!item) return
      if (item.id === 'more') deps.openSessionPicker(projectId)
      else applyPickedTarget(projectId, item.id.slice('session:'.length))
      return
    }
    // 第二级：项目环是父项；「更多…」进完整选择页，其余松开即收起。
    if (tierState.l2.visible) {
      const item = tierState.l2.sectors.find(sector => sector.id === tierState.l2.hovered)
      if (item?.id === 'more') {
        cancelRing()
        deps.openSessionPicker()
        return
      }
      if (tierState.l2.hovered || !ring.hovered) {
        cancelRing()
        return
      }
    }
    const sectorId = sectorAt(x, y)
    const depth = ring.depth
    if (!sectorId) {
      cancelRing()
      return
    }
    const sector = ring.sectors.find(item => item.id === sectorId)
      || deps.config.ping.sectors.find(item => item.id === sectorId)
    if (!sector) {
      cancelRing()
      return
    }

    // user:“只要鼠标选到对应的一级项，其二级项就出来”+(切换会话是父项：
    // 悬停已经长出外圈，松开父项就收起整条链。)
    if (sector.kind === 'switch') {
      cancelRing()
      return
    }

    // 子轮盘：在这一层选中的项直接执行；主轮盘选中 subring 项则展开下一层。
    if (depth === 0 && sector.kind === 'subring') {
      if (!openSubRing(sector, x, y)) cancelRing()
      return
    }
    cancelRing()
    try {
      await executeSector(sector, { x, y })
    } catch (error) {
      deps.report(`ping:${sector.kind}`, error)
    }
  }

  async function executeSector(sector: PingSectorConfig, point: { x: number; y: number }): Promise<void> {
    console.log('[ping] execute sector', sector.kind, sector.id)
    if (sector.kind === 'switch') {
      // 轮盘内切换由悬停浮层负责；直接调用（CLI）时退回完整选择页。
      deps.openSessionPicker()
      return
    }
    if (sector.kind === 'chat') {
      await openPingConversation()
      return
    }
    if (sector.kind === 'select') {
      // user:“重新设计与实现 Ping 的框选工具”+(静态截图在独立窗口里框选；
      // 环先收起，避免截图时还盖着一层 UI。)
      cancelRing()
      if (!deps.openCapture) throw new Error('框选入口未绑定')
      await deps.openCapture()
      return
    }
    if (sector.kind === 'subring') {
      openSubRing(sector, point.x, point.y)
      return
    }
    if (sector.kind === 'custom') {
      await runCustomSector(sector)
      return
    }
    const marker: PingMarker = {
      x: point.x,
      y: point.y,
      kind: sector.kind,
      label: sector.label,
      color: sector.color,
    }
    // 先给视觉确认，再走截图与提交：动画不参与请求时序。
    showMarker(marker)
    await submitPing(sector, sector.prompt || '', marker)
  }

  /**
   * 截图 → 合成标记 → 上传 → 发到 Ping 目标会话。
   * 先拍"不含覆盖层的原始画面"（覆盖层自身对捕获 API 隐形），再合成标记。
   */
  /** 快速 Ping：拍鼠标所在显示器整屏，合成标记后提交。 */
  async function submitPing(sector: PingSectorConfig, prompt: string, marker: PingMarker | null): Promise<void> {
    capture.busy = true
    capture.lastError = ''
    try {
      const frame = await bridge.captureMonitorUnderCursor()
      capture.lastMonitor = null
      const blob = await composeMarkedImage(frame, marker)
      await submitPingWithBlob(sector, prompt, blob, marker, {
        meta: { x: frame.x, y: frame.y, width: frame.width, height: frame.height, scale: frame.scale },
      })
    } catch (error) {
      capture.busy = false
      capture.lastError = error instanceof Error ? error.message : String(error)
      throw error
    }
  }

  /**
   * 已合成好的图片（快速 Ping 与框选标注共用）→ 上传 → 发到 Ping 目标会话。
   * 路由、排队和卡片兜底都在这里，两条入口不会各写一套。
   */
  async function submitPingWithBlob(
    sector: PingSectorConfig | null,
    prompt: string,
    blob: Blob,
    marker: PingMarker | null,
    options: { meta?: { x: number; y: number; width: number; height: number; scale: number } } = {},
  ): Promise<void> {
    capture.busy = true
    capture.lastError = ''
    try {
      const agentHost = deps.getHost()
      const agentClient = deps.getClient()
      if (!agentHost || !agentClient) throw new Error('Agent 连接还没准备好')
      const target = await agentHost.pingTarget()
      syncPingTarget(target)
      const channel = agentHost.channel(target.projectId || null, target.sessionId)
      const effectiveSector: PingSectorConfig = sector || {
        id: 'ping', label: 'Ping', icon: '?', kind: 'question', color: '#6AA8FF', enabled: true,
      }
      const upload = await uploadScreenshot(channel, blob, effectiveSector)
      const text = buildPingText(prompt)
      const result = await channel.send(text, [agentClient.attachmentInput(upload)])
      // user:“pin 的所有东西都是按引导进去的，不是按排队进去的”+
      // (引导被拒时必须明确失败；先打开主窗口再报错会让用户以为消息已经发出。)
      if (result.status === 'ignored') {
        throw new Error(result.message || 'Ping 消息未能送达目标会话')
      }
      // user:“ping完之后用一个合适的大小打开Sunday本体”+(Ping 发出后直接把
      // 主窗口打开到目标会话，后续追问在 Sunday 本体里继续。)
      await bridge.openMainSession(target.projectId || null, target.sessionId)
      capture.lastAt = Date.now()
      capture.busy = false
    } catch (error) {
      capture.busy = false
      capture.lastError = error instanceof Error ? error.message : String(error)
      throw error
    }
  }

  /// user:“不要带那么多有的没的”+(发送文字就是提示词本身：不再拼接标记坐标、
  /// 显示器尺寸等额外说明；标记已经画在图上。)
  function buildPingText(prompt: string): string {
    return prompt.trim()
  }

  async function composeMarkedImage(frame: CapturedFrame, marker: PingMarker | null): Promise<Blob> {
    const canvasElement = bridge.frameToCanvas(frame)
    const context = canvasElement.getContext('2d')
    if (!context) throw new Error('无法创建截图画布')
    if (marker) {
      const localX = marker.x - frame.x
      const localY = marker.y - frame.y
      // 轻微标记：圈 + 符号，不遮挡被指内容。
      context.strokeStyle = marker.color
      context.lineWidth = Math.max(3, Math.round(3 * frame.scale))
      context.beginPath()
      context.arc(localX, localY, 26 * frame.scale, 0, Math.PI * 2)
      context.stroke()
      context.fillStyle = marker.color
      context.font = `${Math.round(20 * frame.scale)}px system-ui, sans-serif`
      context.textAlign = 'center'
      context.textBaseline = 'middle'
      context.fillText(marker.kind === 'question' ? '?' : marker.kind === 'exclamation' ? '!' : '●', localX, localY)
      context.font = `${Math.round(11 * frame.scale)}px system-ui, sans-serif`
      context.fillStyle = 'rgba(0,0,0,0.65)'
      const label = `${Math.round(marker.x)}, ${Math.round(marker.y)}`
      const width = context.measureText(label).width + 10 * frame.scale
      context.fillRect(localX + 30 * frame.scale, localY - 26 * frame.scale, width, 18 * frame.scale)
      context.fillStyle = '#fff'
      context.textAlign = 'left'
      context.fillText(label, localX + 35 * frame.scale, localY - 17 * frame.scale)
    }
    const blob = await new Promise<Blob | null>(resolve => canvasElement.toBlob(resolve, 'image/png'))
    if (!blob) throw new Error('截图编码失败')
    return blob
  }

  async function uploadScreenshot(channel: SessionChannel, blob: Blob, sector: PingSectorConfig): Promise<PetScreenshotUpload> {
    const agentClient = deps.getClient()
    if (!agentClient) throw new Error('Agent 连接还没准备好')
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    return await agentClient.uploadScreenshot(
      channel.sessionId,
      channel.projectId,
      blob,
      `ping-${sector.kind}-${stamp}.png`,
    )
  }

  /** 「对话」：打开 Sunday 本体并切到该会话。
   *
   * user:“ping完之后用一个合适的大小打开Sunday本体…这样最大程度复用”+
   * (不再为 Ping 开独立的卡片窗口：直接复用主窗口完整的聊天与输入界面。)
   */
  async function openPingConversation(): Promise<void> {
    const agentHost = deps.getHost()
    console.log('[ping] open conversation, host=', Boolean(agentHost))
    if (!agentHost) return
    const target = await agentHost.pingTarget()
    syncPingTarget(target)
    console.log('[ping] conversation target', target.projectId, target.sessionId)
    await bridge.openMainSession(target.projectId || null, target.sessionId)
  }

  // -------------------------------------------------------------------------
  // 会话卡片
  // -------------------------------------------------------------------------

  function ensureCard(projectId: string | null, sessionId: string): CardState {
    const existing = cards.get(sessionId)
    if (existing) return existing
    // 一张卡片优先放鼠标所在显示器右侧；不够则放左侧。
    const monitorList = deps.monitors()
    const monitor = monitorList.find(item => (
      deps.cursor.x >= item.x && deps.cursor.x <= item.x + item.width && deps.cursor.y >= item.y && deps.cursor.y <= item.y + item.height
    )) || monitorList[0]
    const width = 380
    const height = 420
    const gap = 24
    const anchor = monitor || { x: deps.overlay.x, y: deps.overlay.y, width: deps.overlay.width, height: deps.overlay.height }
    let x = anchor.x + anchor.width - width - gap
    if (x < anchor.x + gap) x = anchor.x + gap
    let y = anchor.y + gap
    const created: CardState = {
      sessionId,
      projectId,
      pinned: false,
      containerX: x,
      containerY: y,
      cardX: x,
      cardY: y + cards.size * gap,
      title: sessionId.slice(0, 8),
      unread: 0,
      draft: '',
      pendingAttachments: [],
    }
    cards.set(sessionId, created)
    activeCardSessionId.value = sessionId
    void resolveCardTitle(created)
    return created
  }

  async function resolveCardTitle(card: CardState): Promise<void> {
    const agentClient = deps.getClient()
    if (!agentClient || !card.projectId) return
    try {
      const sessions = await agentClient.listSessions(card.projectId)
      const matched = sessions.find(session => session.id === card.sessionId)
      if (matched) card.title = matched.title
    } catch (error) {
      deps.report('card-title', error)
    }
  }

  function pinCard(sessionId: string): void {
    const card = cards.get(sessionId)
    if (!card) return
    card.pinned = true
    card.cardX = card.containerX + 24
    card.cardY = card.containerY + 24
  }

  function unpinCard(sessionId: string): void {
    const card = cards.get(sessionId)
    if (!card) return
    card.pinned = false
    card.containerX = Math.min(card.containerX, deps.overlay.x + deps.overlay.width - 400)
    card.containerY = Math.min(card.containerY, deps.overlay.y + deps.overlay.height - 440)
  }

  /** 关闭视图不等于取消任务：只从界面移除，会话继续跑。 */
  function closeCard(sessionId: string): void {
    cards.delete(sessionId)
    if (activeCardSessionId.value === sessionId) {
      activeCardSessionId.value = [...cards.keys()][0] || null
    }
  }

  function moveCard(sessionId: string, x: number, y: number): void {
    const card = cards.get(sessionId)
    if (!card) return
    const clampedX = Math.min(Math.max(deps.overlay.x + 8, x), deps.overlay.x + deps.overlay.width - 200)
    const clampedY = Math.min(Math.max(deps.overlay.y + 8, y), deps.overlay.y + deps.overlay.height - 120)
    if (card.pinned) {
      card.cardX = clampedX
      card.cardY = clampedY
    } else {
      card.containerX = clampedX
      card.containerY = clampedY
    }
  }

  // -------------------------------------------------------------------------
  // Ping 目标会话与快捷键
  // -------------------------------------------------------------------------

  /**
   * 会话选择器里选完 Ping 目标后的写回：host 路由 + 配置持久化 + 立即开卡。
   * （轮盘内切换会话立即影响后续 Ping。）
   */
  /**
   * 把当前生效的 Ping 目标回写进配置。
   * 首次兜底/旧目标失效重建后，配置里的 target 与 host 绑定保持一致。
   */
  function syncPingTarget(target: { projectId: string; sessionId: string }): void {
    const current = deps.config.ping.target
    if (current && current.projectId === target.projectId && current.sessionId === target.sessionId) return
    deps.config.ping.target = { projectId: target.projectId, sessionId: target.sessionId }
    deps.save()
  }

  /**
   * 会话选择器里选完 Ping 目标后的写回：host 路由 + 配置持久化。
   * （轮盘内切换会话立即影响后续 Ping，并固定为新默认。）
   */
  function applyPickedTarget(projectId: string, sessionId: string): void {
    const agentHost = deps.getHost()
    if (!agentHost) return
    agentHost.setPingTarget(projectId, sessionId)
    deps.config.ping.target = { projectId, sessionId }
    deps.save()
  }

  /** 把当前配置里的快捷键注册到系统；空串视为注销。 */
  async function applyHotkey(): Promise<void> {
    await bridge.setPingHotkey(deps.config.ping.hotkey || null)
  }

  /** 注销快捷键（Ping 被禁用/覆盖层关闭时调用）。 */
  async function disable(): Promise<void> {
    await bridge.setPingHotkey(null)
  }

  /**
   * Ping 自己的输入通道：全局快捷键 down/up。
   * 与桌宠的光标/拖拽事件分开注册，摘掉桌宠不影响 Ping 的入口。
   *
   * user:“为什么会一瞬间给我弹出来这么多东西”+(热更新/重复挂载会把监听叠加，
   * 一次快捷键被处理多次，瞬间发出多条 Ping；这里做幂等，并支持显式摘除。)
   */
  let hotkeyUnlisten: (() => void) | null = null
  let hotkeyAttaching = false
  function attachNativeEvents(): void {
    if (hotkeyUnlisten || hotkeyAttaching) return
    hotkeyAttaching = true
    void (async () => {
      const { listen } = await import('@tauri-apps/api/event')
      hotkeyUnlisten = await listen<{ phase: 'down' | 'up'; x: number; y: number }>('pet://ping/hotkey', ({ payload }) => {
        if (payload.phase === 'down') openRing(payload.x, payload.y)
        else void commitRing(payload.x, payload.y)
      })
      hotkeyAttaching = false
    })().catch(error => {
      hotkeyAttaching = false
      deps.report('ping:events', error)
    })
  }

  function detachNativeEvents(): void {
    hotkeyUnlisten?.()
    hotkeyUnlisten = null
    hotkeyAttaching = false
  }

  /** 轮盘打开时的命中矩形（物理像素）：组合方每帧汇总给 Rust 命中区。 */
  function ringHitRect(): number[] | null {
    if (!ring.visible) return null
    const outer = deps.config.ping.radius + deps.config.ping.ringWidth
    return [ring.x - outer, ring.y - outer, outer * 2, outer * 2]
  }

  return {
    deps,
    config: deps.config,
    /** 覆盖层物理像素边界（共享对象，组件换算坐标用）。 */
    overlay: deps.overlay,
    ring,
    markerFx,
    capture,
    pending,
    cards,
    activeCardSession,
    host,
    client,
    sectorAt,
    openRing,
    cancelRing,
    openSubRing,
    onCursorMoved,
    commitRing,
    executeSector,
    submitPing,
    submitPingWithBlob,
    buildPingText,
    composeMarkedImage,
    openPingConversation,
    ensureCard,
    pinCard,
    unpinCard,
    closeCard,
    moveCard,
    applyPickedTarget,
    applyHotkey,
    disable,
    attachNativeEvents,
    detachNativeEvents,
    ringHitRect,
    tiers: tierState,
  }
}

export type PingRuntime = ReturnType<typeof createPingRuntime>
