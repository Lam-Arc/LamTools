import { computed, hasInjectionContext, inject, onBeforeUnmount, onMounted, provide, reactive, ref, watch, type InjectionKey, type Ref } from 'vue'
import { arrangeLayout, canFitSplit, closePane, closeTab, createSplitState, layoutRects, newTabId, openTab, paneIds, restoreSplitState, splitPane, type SplitContent, type SplitEdge, type SplitState, type SplitTab } from './layout'
import { pluginPageKey, type PluginPageEntry, type PluginPageScope } from '@/plugins/pages'
export type CloseGuard = (proceed: () => void) => void
export type SplitWorkspaceController = ReturnType<typeof useSplitWorkspace>
export const SplitWorkspaceKey: InjectionKey<SplitWorkspaceController> = Symbol('split-workspace')
export function useOptionalSplitWorkspace() { return hasInjectionContext() ? inject(SplitWorkspaceKey, null) : null }
// user:“将大的前端文件拆分成小块”+(分屏状态、保存和内容入口独立于主应用文件)。
export function useSplitWorkspace(storageKey: Ref<string>, workRoot?: Ref<string>, projectId?: Ref<string | null | undefined>) {
  const state = reactive<SplitState>(createSplitState()), guards = new Map<string, CloseGuard>()
  const bounds = ref({ width: 0, height: 0 })
  const canSplit = (target: string, edge: SplitEdge) => !Object.keys(state.panes).length || !bounds.value.width || canFitSplit(state.tree, target, edge, bounds.value.width, bounds.value.height)
  let restoring = false
  const load = () => {
    restoring = true
    let raw: string | null = null
    try { raw = localStorage.getItem(storageKey.value) } catch { /* Storage unavailable: keep the in-memory workspace. */ }
    Object.assign(state, restoreSplitState(raw)); restoring = false
  }
  load()
  let saveTimer: ReturnType<typeof setTimeout> | undefined
  const save = () => { try { localStorage.setItem(storageKey.value, JSON.stringify(state)) } catch { /* Quota failure must not discard live content. */ } }
  watch(state, () => { if (!restoring) { clearTimeout(saveTimer); saveTimer = setTimeout(save, 150) } }, { deep: true })
  // Layout is global to this application instance. Do not destroy dirty screens when changing projects.
  // Each file/agent tab stores its own project/session scope in its resource identity.
  onMounted(() => window.addEventListener('pagehide', save))
  onBeforeUnmount(() => { clearTimeout(saveTimer); save(); window.removeEventListener('pagehide', save) })
  const tabs = computed(() => Object.values(state.panes).flatMap(pane => pane.tabs.map(tab => ({ pane: pane.id, tab }))))
  function add(kind: SplitContent, resource = '', title = '', target?: string, sessionId?: string, root = workRoot?.value || '', boundProjectId: string | null | undefined = projectId?.value) {
    let pane: string | undefined = target && state.panes[target] ? target : state.activePane !== 'main' && state.panes[state.activePane] ? state.activePane : Object.keys(state.panes)[0]
    if (!pane) pane = splitPane(state, 'main', 'right') || undefined
    if (!pane) return null
    state.focused = null
    return openTab(state, pane, { id: newTabId(), kind, resource, root, projectId: boundProjectId || undefined, title: title || ({ page: resource, editor: '文本编辑器', files: '文件', browser: '浏览器', agent: '子代理', conversation: '辅助对话', plugin: '插件页面' })[kind], ...(sessionId ? { sessionId } : {}) })
  }
  function guardTabs(list: SplitTab[], proceed: () => void) {
    const next = (index: number) => { if (index === list.length) proceed(); else { const guard = guards.get(list[index].id); if (guard) guard(() => next(index + 1)); else next(index + 1) } }
    next(0)
  }
  // user:“通过拖动拉起，而不是点击按钮。就类似 blender”+(拖动时把指针算出的分隔比例一次带进布局，再按最小尺寸校正显示)。
  const splitAt = (target: string, edge: SplitEdge, ratio?: number) => canSplit(target, edge) ? splitPane(state, target, edge, ratio) : null
  const toggle = () => { if (!Object.keys(state.panes).length) splitPane(state, 'main', 'right'); else state.hidden = !state.hidden }
  // user:“点一下这个分屏键，自动在右边起一个分屏...分屏键里面不需要有任何东西”+(标题栏入口只向右分屏；已收起时恢复原布局，不弹菜单)。
  const splitRight = () => {
    if (state.hidden) { toggle(); return null }
    let target = state.focused || state.activePane
    if (!state.focused && bounds.value.width) {
      const rects = layoutRects(state.tree, { x: 0, y: 0, ...bounds.value }).panes
      let right = -Infinity
      for (const [id, rect] of Object.entries(rects)) if (rect.x + rect.width >= right) { right = rect.x + rect.width; target = id }
    }
    return splitAt(target, 'right')
  }
  const controller = {
    state, tabs,
    canSplit,
    setBounds(width: number, height: number) { bounds.value = { width, height } },
    add,
    // user:“支持一下”+(仅添加辅助屏标签，不改变主聊天模式；项目由打开时捕获)。
    openPluginPage(page: PluginPageEntry, target?: string, scope?: Omit<PluginPageScope, 'instanceId'>) {
      return scope
        ? add('plugin', pluginPageKey(page.plugin, page.id, scope.filePath), scope.filePath?.split(/[\\/]/).pop() || page.title, target, scope.sessionId || undefined, scope.workRoot, scope.projectId ?? null)
        : add('plugin', pluginPageKey(page.plugin, page.id), page.title, target)
    },
    splitAt,
    splitRight,
    toggle,
    split(target: string, edge: SplitEdge) { return splitAt(target, edge) },
    closeTab(pane: string, tab: SplitTab) { guardTabs([tab], () => closeTab(state, pane, tab.id)) },
    closePane(pane: string) { guardTabs(state.panes[pane]?.tabs || [], () => closePane(state, pane)) },
    registerGuard(id: string, guard: CloseGuard) { guards.set(id, guard); return () => { if (guards.get(id) === guard) guards.delete(id) } },
    preset(preset: Parameters<typeof arrangeLayout>[1]) { arrangeLayout(state, preset) },
    focus(pane: string) { state.focused = state.focused === pane ? null : pane },
    activate(pane: string, tab?: string) { state.activePane = pane; if (tab && state.panes[pane]) state.panes[pane].activeTab = tab },
    show(pane: string) { if (paneIds(state.tree).includes(pane)) { state.hidden = false; state.activePane = pane } },
  }
  provide(SplitWorkspaceKey, controller)
  return controller
}
