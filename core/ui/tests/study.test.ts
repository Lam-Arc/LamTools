import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, nextTick, ref, toValue } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { anchorRange, captureAnchor, expandWord, locateOffsets, splitRangeForFormulaHighlight } from '../src/study/anchors'
import { stableLayeredStudyLayout } from '../src/study/layout'
import { CORE_PLUGIN_MODE_CONTEXT, CORE_PLUGIN_MODE_RUNTIME, createPluginModeRuntime } from '../src/plugins/context'
import StudyView from '../src/study/StudyView.vue'
import NotesManager from '../src/study/NotesManager.vue'
import StudySidebar from '../src/study/StudySidebar.vue'
import StudySidebarHost from '../src/study/StudySidebarHost.vue'
import StudyNoteRelationGraph from '../src/study/StudyNoteRelationGraph.vue'
import StudyGraph from '../src/study/StudyGraph.vue'
import SelectionAssistant from '../src/study/SelectionAssistant.vue'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'
import { contextMenuState, closeContextMenu } from '../src/components/context-menu/context-menu'
import { marks, selectionEvents, showMark } from '../src/study/annotations'
import { extractMarkdownHeadings, normalizeNote } from '../src/study/api'
import type { Course, KnowledgeItem, MarkAnchor, Relation, StudyMark } from '../src/study/types'
import type { CoreSessionListItem } from '../src/types'

vi.mock('@vue-flow/core', () => ({
  VueFlow: { props: ['nodes', 'edges'], template: '<div v-bind="$attrs"><button v-for="node in nodes" :key="node.id" class="test-node" @click="$emit(\'nodeClick\', { node })">{{ node.data.name }}</button><template v-for="node in nodes" :key="`render-${node.id}`"><slot name="node-knowledge" :data="node.data" :selected="false" /></template><i v-for="node in nodes" :key="`position-${node.id}`" class="test-position" :data-node-id="node.id" :data-position="`${node.position.x},${node.position.y}`" /><i v-for="edge in edges" :key="edge.id" class="test-edge" :data-edge-type="edge.type" :data-edge-class="edge.class" /></div>' },
  Handle: { template: '<span />' }, Position: { Left: 'left', Right: 'right' }, MarkerType: { ArrowClosed: 'arrowclosed' },
}))
if (typeof HTMLElement !== 'undefined' && !HTMLElement.prototype.scrollIntoView) {
  Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', { configurable: true, value: () => undefined })
}

afterEach(() => { document.body.innerHTML = ''; window.getSelection()?.removeAllRanges(); closeContextMenu(); marks.value = []; localStorage.clear(); vi.restoreAllMocks() })
function fixture() {
  document.body.innerHTML = '<main class="workspace-main"><div data-message-id="msg1"><div class="markdown-renderer__content">We are running and running today.</div></div></main>'
  const text = document.querySelector('.markdown-renderer__content')!.firstChild!
  const r = document.createRange(); r.setStart(text, 20); r.setEnd(text, 23)
  const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(r)
  return captureAnchor(selection, 'study:main', 'study:study')!
}
function context(rpc: ReturnType<typeof vi.fn>) {
  return {
    requestRpc: rpc, transport: {}, sessions: ref<CoreSessionListItem[]>([]), selectedModelId: ref('model'), activeSessionId: ref('study:main'),
    composerText: ref(''), selectSession: vi.fn().mockResolvedValue(undefined), refreshSessions: vi.fn().mockResolvedValue(undefined),
    lastEvent: ref(null), setRuntimeStatus: vi.fn(), chat: { messages: ref([]), processExpandedIds: ref(new Set()), activeTurnId: computed(() => ''), activeTurnRunning: computed(() => false), toggleProcess: vi.fn(), onDecisionSelect: vi.fn() },
  }
}

async function flushStudyGraph(): Promise<void> {
  await vi.dynamicImportSettled()
  await flushPromises()
}

describe('Study anchoring', () => {
  it('expands partial words and restores the correct repeated occurrence', () => {
    vi.stubGlobal('CSS', { escape: (value: string) => value, highlights: new Map() })
    const anchor = fixture()
    expect(anchor.quote).toBe('running')
    expect(anchor.start).toBe(19)
    expect(anchorRange(anchor)?.toString()).toBe('running')
    expect(expandWord('running', 2, 4)).toEqual([0, 7])
    expect(expandWord('two words', 1, 7)).toEqual([1, 7])
    expect(expandWord("we're", 3, 5)).toEqual([0, 5])
  })
  it('relocates after a preceding edit, and refuses ambiguous or deleted text', () => {
    const a = fixture()
    expect(locateOffsets('Intro. We are running and running today.', a)).toEqual([26, 33])
    expect(locateOffsets('gone', a)).toBeNull()
    expect(locateOffsets('x run y run', { ...a, start: 99, end: 102, quote: 'run', prefix: '', suffix: '' })).toBeNull()
  })
  it('separates formula fragments from mixed and ordinary text highlights', () => {
    document.body.innerHTML = '<p><span id="plain">before</span><span class="katex"><span id="math-a">x</span><span id="math-b">2</span></span><span id="after">after</span></p>'
    const math = document.createRange()
    math.setStart(document.querySelector('#math-a')!.firstChild!, 0)
    math.setEnd(document.querySelector('#math-b')!.firstChild!, 1)
    expect(splitRangeForFormulaHighlight(math).textRanges).toHaveLength(0)
    expect(splitRangeForFormulaHighlight(math).formulaRanges.map(range => range.toString())).toEqual(['x', '2'])

    const mixed = document.createRange()
    mixed.setStart(document.querySelector('#plain')!.firstChild!, 0)
    mixed.setEnd(document.querySelector('#math-b')!.firstChild!, 1)
    const mixedSplit = splitRangeForFormulaHighlight(mixed)
    expect(mixedSplit.textRanges.map(range => range.toString())).toEqual(['before'])
    expect(mixedSplit.formulaRanges.map(range => range.toString())).toEqual(['x', '2'])

    const plain = document.createRange()
    plain.selectNodeContents(document.querySelector('#after')!)
    const plainSplit = splitRangeForFormulaHighlight(plain)
    expect(plainSplit.textRanges).toEqual([plain])
    expect(plainSplit.formulaRanges).toHaveLength(0)
  })
})

describe('Study mode', () => {
  it('offers the Notes workspace only when the host declares the capability', async () => {
    // The Note vault is a host capability: a host without it must not render a
    // navigation entry that can only fail.
    const courses: Course[] = []
    const declared = mount(StudySidebar, { props: { courses, active: 'chat', select: vi.fn() } })
    expect(declared.findAll('button').some(button => button.text() === '笔记')).toBe(true)

    const undeclared = mount(StudySidebar, {
      props: { courses, active: 'chat', select: vi.fn(), notesEnabled: false },
    })
    expect(undeclared.findAll('button').some(button => button.text() === '笔记')).toBe(false)
    // Everything else in the Study navigator stays available.
    expect(undeclared.findAll('button').some(button => button.text() === '图谱')).toBe(true)
    expect(undeclared.findAll('button').some(button => button.text() === '搜索')).toBe(true)
  })

  it('reads the host capability declaration and refuses the Notes workspace without it', () => {
    const studySource = readFileSync(resolve(import.meta.dirname, '../src/study/StudyView.vue'), 'utf8')
    // The declaration drives the gate rather than a host name or a flag.
    expect(studySource).toContain('ctx.modeCapabilities')
    expect(studySource).toContain("capabilities.includes('notes')")
    // Every entry into the workspace goes through the guarded navigation.
    expect(studySource).toContain('if (!notesEnabled.value) return')
    expect(studySource).toContain('notesEnabled: notesEnabled.value')
  })

  it('expands sidebar modules through the course/module hierarchy contract', async () => {
    const loadChildren = vi.fn(async (parent: { id: string; kind: 'course' | 'module'; courseId?: string }): Promise<KnowledgeItem[]> => (
      parent.kind === 'course'
        ? [{ id: 'm-exam', name: '考研初试', entity: 'module', course_id: 'course-28-ai', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null }]
        : parent.id === 'm-exam'
          ? [{ id: 'm-math', name: '数学一', entity: 'module', course_id: 'course-28-ai', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null }]
          : [{ id: 'n-math', name: '函数', entity: 'node', course_id: 'course-28-ai', learnable: true, progressRole: 'unit', assessment: 'unassessed', mastery: null }]
    ))
    const wrapper = mount(StudySidebar, { props: {
      courses: [{ id: 'course-28-ai', name: '28考研', total: 1, passed: 0 }],
      active: 'chat', select: vi.fn(), loadChildren,
    } })
    await flushPromises()
    expect(loadChildren).not.toHaveBeenCalled()
    await wrapper.findAll('.study-tree-label').find(button => button.text() === '28考研')!.trigger('click')
    await flushPromises()
    expect(loadChildren).toHaveBeenCalledWith({ id: 'course-28-ai', kind: 'course' })
    await wrapper.findAll('.study-tree-label').find(button => button.text() === '考研初试')!.trigger('click')
    await flushPromises()
    expect(loadChildren).toHaveBeenLastCalledWith({ id: 'm-exam', kind: 'module', courseId: 'course-28-ai' })
    await wrapper.findAll('.study-tree-label').find(button => button.text() === '数学一')!.trigger('click')
    await flushPromises()
    expect(loadChildren).toHaveBeenLastCalledWith({ id: 'm-math', kind: 'module', courseId: 'course-28-ai' })
    expect(wrapper.text()).toContain('函数')
  })

  it('exposes the knowledge-management action instead of an overview page', async () => {
    const select = vi.fn()
    const wrapper = mount(StudySidebar, { props: {
      courses: [], active: 'manage', select,
    } })
    const manage = wrapper.findAll('button').find(button => button.text() === '管理你的知识')
    expect(manage).toBeTruthy()
    expect(manage!.classes()).toContain('active')
    await manage!.trigger('click')
    expect(select).toHaveBeenCalledWith('manage')
    wrapper.unmount()
  })

  it('retries failed session initialization and enables the composer after recovery', async () => {
    const rpc = vi.fn(async (method: string) => method === 'study.session' ? { session_id: 'study:main' } : { revision: 0, total: 0 })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    ctx.selectSession.mockRejectedValueOnce(new Error('thread not found'))
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    expect(toValue(runtime.get('study:study')!.composerDisabled)).toBe(true)
    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(ctx.selectSession).toHaveBeenCalledTimes(2)
    expect(toValue(runtime.get('study:study')!.composerDisabled)).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('binds map/node sessions, drills down and only prefills learning once', async () => {
    const layouts = new Map<string, unknown>()
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session') {
        const scope = String(params?.scope || 'map')
        return scope === 'node'
          ? { session_id: `study:node:${String(params?.node_id)}`, scope, node_id: params?.node_id }
          : { session_id: scope === 'notes' ? 'study:notes' : 'study:main', scope }
      }
      if (method === 'study.context') return {
        instructions: 'study-system',
        latest_context: { session_id: params?.session_id },
        request_local_late_context: '[Study latest context]{}',
      }
      if (method === 'study.layout') {
        if (params?.value) layouts.set(String(params.scope), params.value)
        return { value: layouts.get(String(params?.scope)) || null }
      }
      if (method === 'study.get' && params?.module_id) return { revision: 1, total: 1, course: { name: '数学' }, items: [{ id: 'vector', name: '向量', entity: 'node', passed: false }] }
      if (method === 'study.get' && params?.course_id) return { revision: 1, total: 1, course: { name: '数学' }, items: [{ id: 'module', name: '代数', entity: 'module' }] }
      if (method === 'study.get' && params?.view === 'overview') return { revision: 1, total: 1, courses: [{ id: 'math', name: '数学', total: 1, passed: 0 }], items: [{ id: 'vector', name: '向量', entity: 'node', passed: false }] }
      return { revision: 1, total: 1, courses: [{ id: 'math', name: '数学', total: 1, passed: 0 }] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const surface = runtime.get('study:study')!
    expect(surface).toBeTruthy()
    expect(ctx.selectSession).toHaveBeenCalledWith('study:main')
    const sidebar = (surface.sidebar!.componentProps as { value: { select: (id: string) => Promise<void> } }).value
    await sidebar.select('map'); await flushStudyGraph()
    expect(wrapper.find('.test-node').text()).toBe('数学')
    await wrapper.find('.test-node').trigger('click'); await flushPromises()
    expect(wrapper.find('[data-study-header] .study-header-title').text()).toBe('数学')
    expect(wrapper.find('.test-node').text()).toBe('代数')
    await sidebar.select('math'); await flushStudyGraph()
    await wrapper.find('.test-node').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('向量')
    await wrapper.findAll('button').find(b => b.text() === '返回')!.trigger('click'); await flushPromises()
    expect(toValue(surface.useCoreThread)).toBe(true)
    expect(wrapper.find('[data-study-core-thread-host]').exists()).toBe(true)
    await wrapper.findAll('button').find(b => b.text() === '知识图谱')!.trigger('click'); await flushStudyGraph()
    expect(wrapper.find('.test-node').text()).toBe('数学')
    await wrapper.find('.test-node').trigger('click'); await flushPromises()
    expect(wrapper.find('.test-node').text()).toBe('代数')
    await wrapper.find('.test-node').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('向量')
    await wrapper.find('.test-node').trigger('click'); await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:node:vector')
    expect(ctx.composerText.value).toBe('我想学向量，给我讲一下')
    expect(rpc.mock.calls.some(([method]) => method === 'turn.start')).toBe(false)
    await expect(surface.turnOptions!()).resolves.toMatchObject({ active_mode: 'study:study', work_root: '' })
    await expect(surface.turnOptions!()).resolves.toMatchObject({ study_node_id: 'vector' })
    expect(rpc.mock.calls.find(([method, params]) => method === 'study.context' && params?.node_id === 'vector')?.[1]).toMatchObject({ session_id: 'study:node:vector' })
    ctx.composerText.value = '用户还没发送的草稿'
    await sidebar.select('math'); await flushStudyGraph()
    await wrapper.find('.test-node').trigger('click'); await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:node:vector')
    expect(ctx.composerText.value).toBe('用户还没发送的草稿')
    await sidebar.select('chat'); await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:node:vector')
    expect((surface.sidebar!.componentProps as { value: { active: string } }).value.active).toBe('')
    await expect(surface.turnOptions!()).resolves.toMatchObject({ instructions: 'study-system' })
    const sessionCallsBeforeManage = rpc.mock.calls.filter(([method]) => method === 'study.session').length
    await sidebar.select('manage'); await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:main')
    expect(rpc.mock.calls.filter(([method]) => method === 'study.session')).toHaveLength(sessionCallsBeforeManage)
    expect((surface.sidebar!.componentProps as { value: { active: string } }).value.active).toBe('manage')
    expect(wrapper.find('[data-study-header] .study-header-title').text()).toBe('学习')
    wrapper.unmount()
    expect(runtime.get('study:study')).toBeUndefined()
  })

  it('delegates chat, attachments, history and sentinel ownership to the canonical Core surface', async () => {
    const rpc = vi.fn(async (method: string): Promise<Record<string, unknown>> => {
      if (method === 'study.session') return { session_id: 'study:main' }
      if (method === 'study.layout') return { value: null }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const surface = runtime.get('study:study')!
    expect(toValue(surface.useCoreThread)).toBe(true)
    expect(toValue(surface.allowAttachmentOnlySubmit)).toBe(true)
    const studySource = readFileSync(resolve(import.meta.dirname, '../src/study/StudyView.vue'), 'utf8')
    const appSource = readFileSync(resolve(import.meta.dirname, '../src/app/LamToolsApp.vue'), 'utf8')
    const scrollSource = readFileSync(resolve(import.meta.dirname, '../src/composables/useCoreAutoFollowScroll.ts'), 'utf8')
    expect(studySource).not.toContain('ChatThread')
    expect(studySource).not.toContain('IntersectionObserver')
    expect(studySource).not.toContain('study-chat-bottom-sentinel')
    expect(studySource).not.toContain('setInterval')
    expect(appSource).toMatch(/<div\s+v-if="activePluginMode"\s+v-show="!pluginUsesCoreThread"\s+class="plugin-mode-surface"/)
    expect(appSource).not.toMatch(/<PluginModeHost\s+[^>]*v-show=/)
    expect(appSource).toContain('<AttachmentTray')
    expect(appSource).toContain('workbench.attachments.value = items')
    expect(appSource).toContain('attachmentOnly && pendingAttachments.value.length')
    expect(appSource).toContain('ref="threadBottomSentinel"')
    expect(appSource).toContain(':message-actions="true"')
    expect(appSource).toContain("session?.metadata?.owner_plugin === 'study'")
    expect(appSource).toContain('isStudyOwnedSessionId(anchor.session_id)')
    expect(scrollSource).toContain('new IntersectionObserver')
    wrapper.unmount()
  })

  it('presents backend relations as a deterministic layered graph with course progress affordances', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session') return { session_id: 'study:main' }
      if (method === 'study.layout') return { value: null }
      if (method === 'study.get' && params?.course_id) return {
        revision: 1,
        total: 2,
        course: { id: 'math', name: '数学' },
        items: [
          { id: 'vector', name: '向量', entity: 'node', passed: false },
          { id: 'matrix', name: '矩阵', entity: 'node', passed: false },
        ],
        relations: [{ id: 'r1', source: 'vector', target: 'matrix', type: 'prerequisite' }],
      }
      return { revision: 1, total: 1, courses: [{ id: 'math', name: '数学', total: 2, passed: 0 }] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const sidebar = (runtime.get('study:study')!.sidebar!.componentProps as { value: { select: (id: string) => Promise<void> } }).value
    await sidebar.select('math'); await flushStudyGraph()
    expect(wrapper.find('[data-study-header] .study-header-title').text()).toBe('数学')
    expect(wrapper.find('.study-graph-meta').text()).toContain('2 个节点')
    expect(wrapper.find('.study-graph-meta').text()).toContain('1 条关系')
    expect(wrapper.find('.study-graph-legend').text()).toContain('前置')
    expect(wrapper.findAll('.test-node')).toHaveLength(2)
    expect(wrapper.find('[data-study-layout="layered"]').exists()).toBe(true)
    expect(wrapper.findAll('.test-edge')).toHaveLength(1)
    expect(wrapper.find('.test-edge').attributes('data-edge-type')).toBe('default')
    const positions = wrapper.findAll('.test-position').map(position => position.attributes('data-position'))
    expect(positions).toHaveLength(2)
    expect(positions.every(position => /^-?\d+,-?\d+$/.test(position || ''))).toBe(true)
    expect(new Set(positions).size).toBe(2)

    const css = readFileSync(resolve(import.meta.dirname, '../src/study/study.css'), 'utf8')
    expect(css).not.toContain('.study-overview')
    expect(css).not.toContain('.study-course {')
    expect(css).toContain('.study-node--course')
    expect(css).toContain('.study-course-ring')
    expect(css).toContain('stroke: var(--blue)')
    expect(css).not.toContain('.study-chat')
    expect(css).toContain('.study-node-dot')
    expect(css).toContain('.study-node--module')
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).not.toContain('radial-gradient')
    const studySource = readFileSync(resolve(import.meta.dirname, '../src/study/StudyView.vue'), 'utf8')
    const sidebarSource = readFileSync(resolve(import.meta.dirname, '../src/study/StudySidebar.vue'), 'utf8')
    const graphSource = readFileSync(resolve(import.meta.dirname, '../src/study/StudyGraph.vue'), 'utf8')
    expect(studySource).not.toContain("page === 'overview'")
    expect(studySource).not.toContain("id === 'overview'")
    expect(sidebarSource).toContain('管理你的知识')
    expect(sidebarSource).toContain("select('manage')")
    expect(studySource).toContain('stableLayeredStudyLayout')
    expect(studySource).toContain("defineAsyncComponent(() => import('./StudyGraph.vue'))")
    expect(graphSource).toContain('data-study-layout="layered"')
    expect(graphSource).toContain("type: 'default'")
    expect(graphSource).toContain('@init="bindGraphViewport"')
    expect(graphSource).toContain('@move-end="syncGraphViewport($event)"')
    expect(graphSource).toContain('setViewport')
    expect(graphSource).toContain('function courseProgress')
    expect(graphSource).toContain('total <= 0')
    expect(graphSource).toContain('Math.min(1, Math.max(0, passed / total))')
    expect(graphSource).toContain('courseProgressTitle')
    expect(graphSource).toContain('study-course-name')
    expect(graphSource).toContain('study-course-percentage')
    expect(graphSource).toContain('study-course-ring-value')
    expect(graphSource).toContain("isCourse(data) ? 'study-node--course'")
    expect(graphSource).toContain("isGroup(data) ? 'study-node--module'")
    expect(graphSource).toContain('aria-hidden="true" focusable="false"')
    expect(graphSource).not.toContain('v-model:viewport')
    expect(graphSource).not.toContain("type: 'smoothstep'")
    expect(graphSource).not.toContain('width: 192px')
    wrapper.unmount()
  })

  it('renders course spheres with clamped progress while deeper nodes stay compact', () => {
    const items: KnowledgeItem[] = [
      { id: 'course-long', name: '线性代数与解析几何', entity: 'course', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null, total: 4, passed: false, progressPassed: 2 },
      { id: 'course-empty', name: '待开始课程', entity: 'course', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null, total: 0, passed: false, progressPassed: 9 },
      { id: 'course-over', name: '已完成课程', entity: 'course', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null, total: 2, passed: false, progressPassed: 9 },
      { id: 'module', name: '章节', entity: 'module', learnable: false, progressRole: 'none', assessment: 'unassessed', mastery: null },
      { id: 'node', name: '向量', entity: 'node', learnable: true, progressRole: 'unit', assessment: 'unassessed', mastery: null },
    ]
    const wrapper = mount(StudyGraph, {
      props: {
        net: { revision: 1, total: items.length, relations: [] },
        nodes: items.map(item => ({ id: item.id, type: 'knowledge', data: item, position: { x: 0, y: 0 } })),
        viewport: { x: 0, y: 0, zoom: 1 }, loading: false, graphFocusId: '', graphSelectedId: '', inspected: null, layoutNotice: '',
      },
    })
    const courses = wrapper.findAll('.study-node--course')
    expect(courses).toHaveLength(3)
    expect(courses[0].text()).toContain('线性代数与解析几何')
    expect(courses[0].text()).toContain('50%')
    expect(courses[0].attributes('aria-label')).toContain('学习进度 50%')
    expect(courses[0].attributes('title')).toContain('学习进度 50%')
    expect(courses[0].find('.study-course-ring-value').attributes('stroke-dasharray')).toBe('50 50')
    expect(courses[1].text()).toContain('0%')
    expect(courses[1].find('.study-course-ring-value').attributes('stroke-dasharray')).toBe('0 100')
    expect(courses[2].text()).toContain('100%')
    expect(courses[2].find('.study-course-ring-value').attributes('stroke-dasharray')).toBe('100 0')
    expect(wrapper.find('.study-node--module .study-node-dot').exists()).toBe(true)
    expect(wrapper.find('.study-node--knowledge .study-node-dot').exists()).toBe(true)
    wrapper.unmount()
  })

  it('starts pin hydration and session binding concurrently, then selects the binding once', async () => {
    const starts: string[] = []
    let releasePins!: () => void
    let releaseBinding!: () => void
    const pinsGate = new Promise<void>(resolve => { releasePins = resolve })
    const bindingGate = new Promise<void>(resolve => { releaseBinding = resolve })
    const events: string[] = []
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.pin') {
        starts.push('study.pin')
        await pinsGate
        return { pins: [], scope: { user_id: 'alice', environment_id: 'desktop-a', library_id: 'math' } }
      }
      if (method === 'study.session') {
        starts.push('study.session')
        await bindingGate
        return { session_id: 'study:main', scope: params?.scope || 'map' }
      }
      if (method === 'study.get' && params?.view === 'overview') {
        events.push('study.get:overview')
        return { revision: 1, total: 0, courses: [] }
      }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc)
    ctx.refreshSessions.mockImplementation(async () => { events.push('refreshSessions') })
    ctx.selectSession.mockImplementation(async (id: string) => {
      events.push(`selectSession:${id}`)
      ctx.activeSessionId.value = id
    })
    const runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })

    // Both independent startup reads must be in flight before either gate is released.
    await Promise.resolve()
    expect(starts).toEqual(['study.pin', 'study.session'])
    releasePins()
    releaseBinding()
    await flushPromises()

    expect(rpc.mock.calls.filter(([method]) => method === 'study.session')).toHaveLength(1)
    expect(ctx.refreshSessions).toHaveBeenCalledTimes(1)
    expect(ctx.selectSession).toHaveBeenCalledTimes(1)
    expect(ctx.selectSession).toHaveBeenCalledWith('study:main')
    expect(events.indexOf('refreshSessions')).toBeLessThan(events.indexOf('selectSession:study:main'))
    expect(events).toContain('study.get:overview')
    expect(toValue(runtime.get('study:study')!.useCoreThread)).toBe(true)
    wrapper.unmount()
  })

  it('switches to a knowledge session with one binding, refresh, and select sequence', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session') {
        return params?.scope === 'node'
          ? { session_id: `study:node:${String(params.node_id)}`, scope: 'node', node_id: params.node_id }
          : { session_id: 'study:main', scope: 'map' }
      }
      if (method === 'study.pin') return { pins: [], scope: { user_id: 'alice', environment_id: 'desktop-a', library_id: 'math' } }
      if (method === 'study.get' && params?.view === 'overview') return { revision: 1, total: 0, courses: [] }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc)
    ctx.sessions.value = [
      { id: 'study:main', title: '知识图谱', createdAt: '' },
      { id: 'study:node:vector', title: '学习 · 向量', createdAt: '' },
    ]
    const runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    vi.clearAllMocks()

    const events: string[] = []
    ctx.refreshSessions.mockImplementation(async () => { events.push('refreshSessions') })
    ctx.selectSession.mockImplementation(async (id: string) => {
      events.push(`selectSession:${id}`)
      ctx.activeSessionId.value = id
    })
    const openNode = (runtime.get('study:study')!.sidebar!.componentProps as { value: { openNode: (node: KnowledgeItem) => Promise<void> } }).value.openNode
    await openNode({ id: 'vector', name: '向量', entity: 'node', learnable: true, progressRole: 'unit', assessment: 'unassessed', mastery: null })
    await flushPromises()

    expect(rpc.mock.calls.filter(([method]) => method === 'study.session')).toHaveLength(1)
    expect(ctx.refreshSessions).not.toHaveBeenCalled()
    expect(ctx.selectSession).toHaveBeenCalledTimes(1)
    expect(ctx.selectSession).toHaveBeenCalledWith('study:node:vector')
    expect(events).toEqual(['selectSession:study:node:vector'])
    expect(toValue(runtime.get('study:study')!.useCoreThread)).toBe(true)
    wrapper.unmount()
  })
})

describe('Study v2 layout and notes', () => {
  it('returns from the note tree and notes chat to the learning sidebar', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session') return { session_id: params?.scope === 'notes' ? 'study:notes' : 'study:main', scope: params?.scope || 'map' }
      if (method === 'study.notes') return { tree: [], notes: [], nodes: [], edges: [] }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const sidebar = runtime.get('study:study')!.sidebar!.componentProps as { value: InstanceType<typeof StudySidebarHost>['$props'] }
    for (const chat of [false, true]) {
      await sidebar.value.select('notes'); await flushPromises()
      if (chat) {
        await wrapper.get('.study-note-header-chat').trigger('click'); await flushPromises()
      }
      const host = mount(StudySidebarHost, { props: sidebar.value, global: { stubs: { Teleport: true } } })
      expect(host.find('.study-note-tree').exists()).toBe(true)
      await host.get('.study-note-tree-back').trigger('click'); await flushPromises()
      expect(ctx.selectSession).toHaveBeenLastCalledWith('study:main')
      await host.setProps(sidebar.value)
      expect(host.find('.study-note-tree').exists()).toBe(false)
      expect(host.findComponent(StudySidebar).exists()).toBe(true)
      host.unmount()
    }
    wrapper.unmount()
  })
  it('opens the notes workspace and keeps the current note session for dialog handoff', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session') return { session_id: params?.scope === 'notes' ? 'study:notes' : 'study:main', scope: params?.scope || 'map' }
      if (method === 'study.notes') {
        if (params?.action === 'tree') return { tree: [] }
        if (params?.action === 'list') return { notes: [] }
        if (params?.action === 'graph') return { nodes: [], edges: [] }
      }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const sidebar = (runtime.get('study:study')!.sidebar!.componentProps as { value: { select: (id: string) => Promise<void> } }).value
    await sidebar.select('notes'); await flushPromises()
    expect(rpc.mock.calls.some(([method, params]) => method === 'study.notes' && params?.action === 'graph')).toBe(true)
    ctx.composerText.value = '请保留这个已有要求'
    await nextTick()
    await wrapper.findComponent(NotesManager).props().onCreate?.()
    await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:notes')
    expect(ctx.composerText.value).toBe('请保留这个已有要求')
    expect(toValue(runtime.get('study:study')!.useCoreThread)).toBe(true)
    expect(wrapper.findComponent(NotesManager).exists()).toBe(true)
    expect(wrapper.findComponent(NotesManager).isVisible()).toBe(false)
    wrapper.unmount()
  })
  it('extracts a stable h1-h6 outline with duplicate-safe anchors', () => {
    expect(extractMarkdownHeadings('# Intro\n\nSetext\n------\n\n## Detail\n\n## Detail\n\n```md\n# ignored\n```')).toEqual([
      { level: 1, text: 'Intro', id: 'intro' },
      { level: 2, text: 'Setext', id: 'setext' },
      { level: 2, text: 'Detail', id: 'detail' },
      { level: 2, text: 'Detail', id: 'detail-2' },
    ])
  })

  it('renders a note-only relation SVG and keeps a keyboard-accessible list fallback', async () => {
    const onOpenNote = vi.fn()
    const wrapper = mount(StudyNoteRelationGraph, { props: {
      graph: {
        revision: 1,
        nodes: [{ id: 'a', title: 'A', kind: 'note' }, { id: 'node-x', title: 'Raw', kind: 'node' }, { id: 'b', title: 'B', kind: 'note' }],
        edges: [{ id: 'ab', source: 'a', target: 'b', kind: 'wikilink' }],
      },
      onOpenNote,
    } })
    await flushPromises()
    expect(wrapper.find('[data-note-graph-svg]').exists()).toBe(true)
    expect(wrapper.findAll('[data-note-graph-node]')).toHaveLength(2)
    expect(wrapper.find('[data-note-graph-node="node-x"]').exists()).toBe(false)
    await wrapper.find('[data-note-graph-node="b"]').trigger('keydown', { key: 'Enter' })
    expect(onOpenNote).toHaveBeenCalledWith('b')
    expect(wrapper.findAll('.study-note-graph-node')).toHaveLength(2)
    wrapper.unmount()
  })

  it('renders the full Markdown body, outline, and safe wikilink navigation', async () => {
    const note = normalizeNote({ id: 'note-1', title: 'Current', path: 'Current.md', body_md: '# Intro\n\n## Detail\n\n[[note-2|Next note]] and [[梯度|方法]] and [[missing]]\n\n    [[missing]]', resources: [{ id: 'resource-1', title: '会话来源', kind: 'session' }], resource_ids: ['resource-1'], links: [
      { target: 'note-2', id: 'note-2', kind: 'note', title: 'Next' },
      { target: '梯度', id: 'gradient', kind: 'node', title: '梯度' },
      { target: 'missing', id: 'missing', kind: 'unresolved', title: 'Missing' },
    ], backlinks: [], revision: 1 })
    const linked = normalizeNote({ id: 'note-2', title: 'Next', path: 'Next.md', body_md: '# Next', resources: [{ id: 'resource-2' }], resource_ids: ['resource-2'], links: [], backlinks: [], revision: 1 })
    const onSelect = vi.fn().mockResolvedValue(undefined)
    const onOpenNode = vi.fn().mockResolvedValue(undefined)
    const wrapper = mount(NotesManager, { props: { notes: [note, linked], selected: note, onSelect, onOpenNode } })
    await flushPromises()

    expect(wrapper.find('[data-study-note-document]').exists()).toBe(true)
    expect(wrapper.findAll('.study-note-outline-link')).toHaveLength(2)
    expect(wrapper.find('.study-note-references').text()).toContain('会话来源')
    expect(wrapper.findAll('[data-study-note-document] a').map(link => link.text())).toEqual(['Next note', '方法', 'missing'])
    await wrapper.findAll('[data-study-note-document] a')[0].trigger('click')
    await wrapper.findAll('[data-study-note-document] a')[1].trigger('click')
    expect(onSelect).toHaveBeenCalledWith(linked)
    expect(onOpenNode).toHaveBeenCalledWith('gradient')
    wrapper.unmount()
  })

  it('edits and saves the complete body, retaining locks and templates', async () => {
    const note = normalizeNote({
      id: 'note-1', title: 'Current', path: 'Current.md', body_md: '正文', revision: 3, content_hash: 'hash-3',
      resource_ids: ['source-1'], resources: [{ id: 'source-1', title: '原始会话', kind: 'session' }],
      locks: [{ lock_id: 'lock-1', start: 0, end: 2, quote: '正文' }], links: [], backlinks: [],
    })
    const onSaveDocument = vi.fn().mockResolvedValue({ ...note, bodyMd: '正文\n$$\nx\n$$\n', body_md: '正文\n$$\nx\n$$\n', revision: 4, contentHash: 'hash-4' })
    const wrapper = mount(NotesManager, { props: { notes: [note], selected: note, onSelect: vi.fn(), onSaveDocument } })
    await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
    const editor = wrapper.find('.study-note-full-editor')
    await editor.setValue('正文\n$$\nx\n$$\n')
    expect(wrapper.find('.study-note-full-editor').element).toHaveProperty('value', '正文\n$$\nx\n$$\n')
    expect(wrapper.text()).toContain('Agent 保护区域')
    await wrapper.findAll('button').find(button => button.text() === '保存')!.trigger('click')
    await flushPromises()
    expect(onSaveDocument).toHaveBeenCalledWith(note, '正文\n$$\nx\n$$\n', expect.objectContaining({ revision: 3, contentHash: 'hash-3', resourceIds: ['source-1'] }))
    expect(wrapper.text()).toContain('已保存')
    wrapper.unmount()
  })

  it('protects an exact editor selection with a visible lock conflict', async () => {
    const note = normalizeNote({ id: 'note-lock', title: 'Lock', path: 'Lock.md', body_md: '😀 受保护', revision: 1, content_hash: 'h1', resource_ids: ['resource-1'], resources: [{ id: 'resource-1' }], locks: [], links: [], backlinks: [] })
    const onLockRange = vi.fn().mockRejectedValue(Object.assign(new Error('locked'), { code: 'NOTE_REGION_LOCKED', data: { error: 'NOTE_REGION_LOCKED', reason: '用户保护', overlaps: [{ quote: '受保护', overlap_start: 3, overlap_end: 6 }] } }))
    const wrapper = mount(NotesManager, { props: { notes: [note], selected: note, onSelect: vi.fn(), onLockRange } })
    await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
    const textarea = wrapper.find('.study-note-full-editor').element as HTMLTextAreaElement
    textarea.focus(); textarea.setSelectionRange(3, 6)
    await wrapper.find('.study-note-full-editor').trigger('contextmenu', { clientX: 20, clientY: 20 })
    const lockItem = contextMenuState.items.find(item => 'label' in item && item.label === '锁定选中内容')
    if (lockItem && 'action' in lockItem) await lockItem.action()
    expect(onLockRange).toHaveBeenCalledWith(note, expect.objectContaining({ start: 3, end: 6, quote: '受保护' }))
    await flushPromises()
    expect(wrapper.text()).toContain('用户保护')
    expect(wrapper.text()).toContain('受保护')
    wrapper.unmount()
  })

  it('keeps layered positions deterministic and preserves user coordinates', () => {
    const item = (id: string): KnowledgeItem => ({
      id,
      name: id,
      entity: 'node',
      learnable: true,
      progressRole: 'unit',
      assessment: 'unassessed',
      mastery: null,
    })
    const relations: Relation[] = [
      { id: 'r2', source: 'b', target: 'c', type: 'prerequisite' },
      { id: 'r1', source: 'a', target: 'c', type: 'prerequisite' },
      { id: 'r3', source: 'a', target: 'b', type: 'related' },
    ]
    const first = stableLayeredStudyLayout([item('c'), item('b'), item('a')], relations)
    expect(first).toEqual({
      a: { x: 48, y: 56 },
      b: { x: 48, y: 168 },
      c: { x: 280, y: 56 },
    })
    expect(stableLayeredStudyLayout([item('c'), item('b'), item('a')], relations, { c: { x: 900, y: 42 } }).c).toEqual({ x: 900, y: 42 })
  })

  it('loads the Markdown vault tree, enters the notes session, and edits a full document', async () => {
    const note = {
      id: 'note-1', title: '向量复习', path: '数学/向量复习.md', body_md: '# 向量\n\n补充定义', resource_ids: ['vector-resource'],
      resources: [{ id: 'vector-resource', title: '向量会话', kind: 'session' }], revision: 3, content_hash: 'hash-3', links: [], backlinks: [], locks: [],
    }
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session.binding') throw new Error('legacy Study host')
      if (method === 'study.session') return { session_id: String(params?.scope) === 'notes' ? 'study:notes' : 'study:main', scope: params?.scope || 'map' }
      if (method === 'study.layout') return { value: null }
      if (method === 'study.notes' && params?.action === 'tree') return { tree: [{ id: 'folder', title: '数学', kind: 'folder', children: [{ id: note.id, note_id: note.id, title: note.title, path: note.path, kind: 'note' }] }] }
      if (method === 'study.notes' && params?.action === 'list') return { notes: [note] }
      if (method === 'study.notes' && params?.action === 'graph') return { nodes: [{ id: note.id, title: note.title, kind: 'note' }], edges: [] }
      if (method === 'study.notes' && params?.action === 'get') return { note }
      if (method === 'study.notes' && params?.action === 'update') {
        note.body_md = String(params.body_md)
        note.revision = 4
        note.content_hash = 'hash-4'
        return { saved: true, revision: 4, content_hash: 'hash-4' }
      }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const sidebar = (runtime.get('study:study')!.sidebar!.componentProps as { value: { select: (id: string) => Promise<void> } }).value
    await sidebar.select('notes'); await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:notes')
    const sidebarProps = (runtime.get('study:study')!.sidebar!.componentProps as { value: { noteTree: any[]; selectNote: (node: any) => Promise<void> } }).value
    expect(sidebarProps.noteTree).toHaveLength(1)
    await sidebarProps.selectNote({ id: note.id, note_id: note.id, title: note.title, path: note.path, kind: 'note' }); await flushPromises()
    expect(wrapper.find('.study-note-document').text()).toContain('补充定义')
    const edit = wrapper.findAll('button').find(button => button.text() === '编辑')
    expect(edit).toBeTruthy()
    await edit!.trigger('click'); await flushPromises()
    const editor = wrapper.find('.study-note-full-editor')
    expect(editor.element).toHaveProperty('value', '# 向量\n\n补充定义')
    await editor.setValue('# 向量\n\n修订后的定义')
    const save = wrapper.findAll('button').find(button => button.text() === '保存')
    expect(save).toBeTruthy()
    await save!.trigger('click'); await flushPromises()
    expect(rpc.mock.calls.find(([name, params]) => name === 'study.notes' && params?.action === 'update')?.[1]).toMatchObject({
      note_id: 'note-1', body_md: '# 向量\n\n修订后的定义', expected_revision: 3, expected_content_hash: 'hash-3', resource_ids: ['vector-resource'],
    })
    expect(wrapper.find('.study-note-full-editor').element).toHaveProperty('value', '# 向量\n\n修订后的定义')
    wrapper.unmount()
  })

  it('routes file-tree, header back, and header chat through the dirty-note gate', async () => {
    const first = {
      id: 'note-first', title: '第一篇', path: '第一篇.md', body_md: '# 第一篇', resource_ids: [],
      resources: [], revision: 1, content_hash: 'first-hash', links: [], backlinks: [], locks: [],
    }
    const second = {
      id: 'note-second', title: '第二篇', path: '第二篇.md', body_md: '# 第二篇', resource_ids: [],
      resources: [], revision: 1, content_hash: 'second-hash', links: [], backlinks: [], locks: [],
    }
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.session') return { session_id: String(params?.scope) === 'notes' ? 'study:notes' : 'study:main', scope: params?.scope || 'map' }
      if (method === 'study.layout') return { value: null }
      if (method === 'study.notes' && params?.action === 'tree') return { tree: [
        { id: first.id, note_id: first.id, title: first.title, path: first.path, kind: 'note' },
        { id: second.id, note_id: second.id, title: second.title, path: second.path, kind: 'note' },
      ] }
      if (method === 'study.notes' && params?.action === 'list') return { notes: [first, second] }
      if (method === 'study.notes' && params?.action === 'graph') return { nodes: [
        { id: first.id, title: first.title, kind: 'note' }, { id: second.id, title: second.title, kind: 'note' },
      ], edges: [] }
      if (method === 'study.notes' && params?.action === 'get') return { note: params.note_id === second.id ? second : first }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const surface = runtime.get('study:study')!
    const sidebar = (surface.sidebar!.componentProps as { value: { select: (id: string) => Promise<void>; selectNote: (node: { id: string; note_id: string; title: string; path: string; kind: 'note' }) => Promise<void> } }).value
    await sidebar.select('notes'); await flushPromises()
    await sidebar.selectNote({ id: first.id, note_id: first.id, title: first.title, path: first.path, kind: 'note' }); await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
    await wrapper.find('.study-note-full-editor').setValue('# 未保存草稿')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)

    await sidebar.selectNote({ id: second.id, note_id: second.id, title: second.title, path: second.path, kind: 'note' }); await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.study-note-full-editor').element).toHaveProperty('value', '# 未保存草稿')

    await wrapper.find('[data-study-header] > button.text-btn').trigger('click'); await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-study-header] .study-note-header-chat').exists()).toBe(true)

    await wrapper.find('[data-study-header] .study-note-header-chat').trigger('click'); await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(3)
    expect(wrapper.find('[data-study-header] .study-note-header-chat').exists()).toBe(true)

    const noteSidebar = toValue(surface.sidebar!.componentProps) as { leaveNotes: () => Promise<void>; noteWorkspaceActive: boolean }
    await noteSidebar.leaveNotes(); await flushPromises()
    expect(confirm).toHaveBeenCalledTimes(4)
    expect(wrapper.find('.study-note-full-editor').element).toHaveProperty('value', '# 未保存草稿')
    expect((toValue(surface.sidebar!.componentProps) as { noteWorkspaceActive: boolean }).noteWorkspaceActive).toBe(true)
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:notes')

    confirm.mockReturnValue(true)
    ctx.selectSession.mockRejectedValueOnce(new Error('session unavailable'))
    await noteSidebar.leaveNotes(); await flushPromises()
    expect(wrapper.find('.study-note-full-editor').element).toHaveProperty('value', '# 未保存草稿')
    expect((toValue(surface.sidebar!.componentProps) as { noteWorkspaceActive: boolean }).noteWorkspaceActive).toBe(true)
    expect(wrapper.get('.study-error').text()).toContain('session unavailable')

    await wrapper.find('[data-study-header] .study-note-header-chat').trigger('click'); await flushPromises()
    expect(ctx.selectSession).toHaveBeenLastCalledWith('study:notes')
    expect(wrapper.find('[data-study-header] .study-note-header-chat').exists()).toBe(false)
    wrapper.unmount()
  })
})

describe('Study search and scoped pins', () => {
  it('hydrates pins from the scoped server endpoint and mirrors only under a scoped cache key', async () => {
    const scope = { user_id: 'alice', environment_id: 'desktop-a', library_id: 'math' }
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.pin') {
        if (params?.action === 'add') return { pins: [{ kind: 'node', id: 'vector', title: '向量' }], scope }
        return { pins: [], scope }
      }
      if (method === 'study.session') return { session_id: 'study:main', scope: 'map' }
      if (method === 'study.layout') return { value: null }
      if (method === 'study.get' && params?.view === 'overview') return { revision: 1, total: 0, courses: [] }
      return { revision: 1, total: 0, courses: [] }
    })
    const ctx = context(rpc), runtime = createPluginModeRuntime()
    const wrapper = mount(StudyView, { global: { stubs: { Teleport: true }, provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx, [CORE_PLUGIN_MODE_RUNTIME as symbol]: runtime } } })
    await flushPromises()
    const sidebar = (runtime.get('study:study')!.sidebar!.componentProps as { value: { togglePin: (pin: { id: string; kind: 'node'; title: string }) => Promise<void> } }).value
    await sidebar.togglePin({ id: 'vector', kind: 'node', title: '向量' })
    await flushPromises()
    expect(rpc.mock.calls.some(([method, params]) => method === 'study.pin' && params?.action === 'add' && params?.entity_id === 'vector')).toBe(true)
    expect(localStorage.getItem('lamtools-study-pins')).toBeNull()
    expect(Object.keys(localStorage).some(key => key.startsWith('lamtools-study-pins:'))).toBe(true)
    const source = readFileSync(resolve(import.meta.dirname, '../src/study/StudyView.vue'), 'utf8')
    expect(source).toContain("rpc('study.pin'")
    expect(source).not.toContain("localStorage.getItem('lamtools-study-pins'")
    wrapper.unmount()
  })
})

describe('Global selection assistant', () => {
  it('embeds one non-interactive theme-aware icon before each restored mark', async () => {
    vi.useFakeTimers()
    try {
      vi.stubGlobal('CSS', { escape: (value: string) => value, highlights: new Map() })
      const anchor = fixture()
      const mark: StudyMark = { id: 'mark-icon', anchor, explain: '标记解释', translate: '', thread: [] }
      const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
        if (method === 'study.marks' && params?.action === 'list') return { marks: [mark], total: 1 }
        return { mark }
      })
      const wrapper = mount(SelectionAssistant, { props: { sessionId: 'study:main', mode: 'study:study', themeMode: 'light', jump: vi.fn() }, attachTo: document.body, global: { provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: context(rpc) } } })
      await flushPromises()
      await vi.advanceTimersByTimeAsync(200)
      await nextTick()

      const icon = document.querySelector<HTMLSpanElement>('[data-study-mark-icon]')
      expect(document.querySelectorAll('[data-study-mark-icon]')).toHaveLength(1)
      expect(icon?.tagName).toBe('SPAN')
      expect(icon?.getAttribute('aria-label')).toBe('已标记')
      expect(icon?.classList.contains('study-mark-icon--light')).toBe(true)
      expect(icon?.nextSibling?.textContent?.startsWith('running')).toBe(true)
      expect(document.querySelector('.selection-card')).toBeNull()

      await wrapper.setProps({ themeMode: 'dark' })
      await vi.advanceTimersByTimeAsync(200)
      await nextTick()
      expect(document.querySelector('.study-mark-icon--dark')).not.toBeNull()
      wrapper.unmount()

      const componentSource = readFileSync(resolve(import.meta.dirname, '../src/study/SelectionAssistant.vue'), 'utf8')
      const tokenSource = readFileSync(resolve(import.meta.dirname, '../src/styles/variables.css'), 'utf8')
      expect(componentSource).toContain('::highlight(study-marks-text-light)')
      expect(componentSource).toContain('::highlight(study-marks-formula-dark)')
      expect(tokenSource).toContain('--study-mark-light: #002fa7')
      expect(tokenSource).toContain('--study-mark-dark: #ffea00')
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps copy, invokes the independent endpoint and restores a mark mini thread', async () => {
    vi.stubGlobal('CSS', { escape: (value: string) => value, highlights: new Map() })
    const anchor = fixture()
    const mark: StudyMark = { id: 'mark1', anchor, explain: '', translate: '', thread: [] }
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (method === 'study.marks' && params?.action === 'list') return { marks: [], total: 0 }
      if (method === 'study.text') return { mark: { ...mark, explain: '**解释结果**', thread: [{ role: 'user', content: '**为什么**' }, { role: 'assistant', content: '**因为…**' }] } }
      return { mark }
    })
    const ctx = context(rpc)
    const wrapper = mount(SelectionAssistant, { props: { sessionId: 'study:main', mode: 'core:agent', themeMode: 'light', jump: vi.fn() }, attachTo: document.body, global: { provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: ctx } } })
    await flushPromises()
    document.querySelector('.markdown-renderer__content')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 900, clientY: 700 }))
    expect(contextMenuState.items.filter(e => e.type !== 'separator').map(e => 'label' in e && e.label)).toEqual(['复制', '标记', '解释', '询问', '翻译'])
    const markAction = contextMenuState.items.find(e => 'label' in e && e.label === '标记')!
    if ('action' in markAction) await markAction.action()
    await flushPromises()
    expect(rpc.mock.calls.find(([name, params]) => name === 'study.marks' && params?.action === 'create' && params?.pure)?.[1]).toMatchObject({ pure: true, anchor: { quote: 'running' } })
    expect(rpc.mock.calls.some(([name]) => name === 'study.text')).toBe(false)
    const explain = contextMenuState.items.find(e => 'label' in e && e.label === '解释')!
    if ('action' in explain) await explain.action()
    await flushPromises()
    expect(document.querySelector('.selection-card')!.textContent).toContain('解释结果')
    expect(document.querySelector('.selection-assistant-markdown.markdown-renderer')).not.toBeNull()
    expect(wrapper.findAllComponents(MarkdownRenderer).every(renderer => renderer.props('mermaid') === false)).toBe(true)
    expect(rpc.mock.calls.find(([name, params]) => name === 'study.marks' && params?.action === 'create')?.[1]).toMatchObject({
      anchor: { quote: 'running' },
    })
    expect(rpc.mock.calls.find(([name]) => name === 'study.text')?.[1]).toMatchObject({ id: 'mark1', action: 'explain', model_id: 'model' })
    showMark(marks.value[0], 'ask'); await nextTick()
    expect(document.querySelector('.selection-card')!.textContent).toContain('因为…')
    expect(document.querySelector('.selection-question')!.textContent).toBe('**为什么**')
    expect(document.querySelector('.selection-question strong')).toBeNull()
    expect(document.querySelector('.selection-assistant-markdown strong')?.textContent).toBe('因为…')
    expect(document.querySelector('.selection-card')?.classList.contains('optical-glass')).toBe(true)
    expect(ctx.composerText.value).toBe('')
    wrapper.unmount()
  })
})
