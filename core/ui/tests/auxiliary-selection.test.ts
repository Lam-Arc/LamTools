import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import SelectionAssistant from '../src/study/SelectionAssistant.vue'
import UserReferenceText from '../src/components/UserReferenceText.vue'
import { captureAnchor } from '../src/study/anchors'
import ContextMenuHost from '../src/components/context-menu/ContextMenuHost.vue'
import { CORE_PLUGIN_MODE_CONTEXT } from '../src/plugins/context'
import { AuxiliaryWorkspaceKey } from '../src/auxiliary/workspace'
import { contextMenuState, closeContextMenu } from '../src/components/context-menu/context-menu'
import { marks, showMark } from '../src/study/annotations'
import type { StudyMark } from '../src/study/types'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(w => w.unmount()); document.body.innerHTML = ''; marks.value = []; closeContextMenu(); vi.unstubAllGlobals() })
function setup() {
  vi.stubGlobal('CSS', { escape: (v: string) => v, highlights: new Map() })
  document.body.innerHTML = '<section class="split-tab-content" data-source-session-id="source-split"><div data-message-id="message-a"><div class="markdown-renderer__content">hello world</div></div></section>'
  const node = document.querySelector('.markdown-renderer__content')!.firstChild!, range = document.createRange()
  range.setStart(node, 0); range.setEnd(node, 5)
  window.getSelection()!.removeAllRanges(); window.getSelection()!.addRange(range)
  const mark: StudyMark = { id: 'mark-a', anchor: { document_id: 'message-a', block_id: 'body|0', start: 0, end: 5, quote: 'hello', prefix: '', suffix: ' world', session_id: 'source-split' }, explain: '解释结果', translate: '你好', thread: [{ role: 'user', content: '之前的问题' }, { role: 'assistant', content: '之前的回答' }] }
  const open = vi.fn(() => ({ id: 'aux' }))
  const rpc = vi.fn(async (method: string) => method === 'study.marks' ? { marks: [], total: 0 } : { mark })
  wrappers.push(mount(ContextMenuHost, { attachTo: document.body }))
  wrappers.push(mount(SelectionAssistant, { attachTo: document.body, props: { sessionId: 'main-other', mode: 'core:agent', themeMode: 'light', jump: vi.fn() }, global: { provide: {
    [CORE_PLUGIN_MODE_CONTEXT as symbol]: { requestRpc: rpc, selectedModelId: ref('model'), lastEvent: ref(null), setRuntimeStatus: vi.fn() },
    [AuxiliaryWorkspaceKey as symbol]: { open },
  } } }))
  return { open, rpc, mark }
}
// user:“价值一致就行，不必逐项功能对齐”+(保存标记、快速阅读和深入讨论各司其职，不再堆叠重复小聊天)。
describe('selection to auxiliary conversation', () => {
  it('opens the captured source directly without creating a mark or invoking a model', async () => {
    const { open, rpc } = setup(); await flushPromises()
    document.querySelector('.markdown-renderer__content')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
    const entry = contextMenuState.items.find(item => 'label' in item && item.label === '辅助对话')
    expect(entry && 'action' in entry).toBe(true)
    if (entry && 'action' in entry) await entry.action()
    expect(open).toHaveBeenCalledWith({ anchor: expect.objectContaining({ quote: 'hello', session_id: 'source-split' }) })
    expect(rpc.mock.calls.every(([method]) => method === 'study.marks')).toBe(true)
    expect(document.querySelector('.selection-card')).toBeNull()
  })
  it('carries an existing mark discussion into the pane without erasing old answers', async () => {
    const { open, mark } = setup(); await flushPromises()
    showMark(mark, 'ask'); await flushPromises()
    expect(open).toHaveBeenCalledWith({ anchor: mark.anchor, mark })
    expect(mark.thread).toHaveLength(2)
    expect(mark.translate).toBe('你好')
  })
  it('promotes a quick result with the quote and previous discussion intact', async () => {
    const { open, mark } = setup(); await flushPromises()
    showMark(mark, 'translate'); await flushPromises()
    const button = Array.from(document.querySelectorAll<HTMLButtonElement>('.selection-card button')).find(el => el.textContent?.includes('辅助对话'))!
    expect(button).toBeTruthy(); button.click(); await flushPromises()
    expect(open).toHaveBeenCalledWith({ anchor: mark.anchor, mark })
    expect(document.querySelector('.selection-card')).toBeNull()
  })
  it('keeps source offsets exact when the visible question folds its reference context', () => {
    const prefix = 'Reference information.\n\nQuestion:\n'
    document.body.innerHTML = '<section class="workspace-main"><div data-message-id="aux-user"><div class="user-bubble"></div></div></section>'
    const bubble = document.querySelector('.user-bubble')!
    const wrapper = mount(UserReferenceText, { attachTo: bubble, props: { text: prefix + 'Why', foldedPrefix: prefix } }); wrappers.push(wrapper)
    expect(wrapper.find('[data-auxiliary-reference-prefix]').attributes('hidden')).toBeDefined()
    const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT)
    let visible: Node | null = null
    while (walker.nextNode()) if (walker.currentNode.textContent === 'Why') visible = walker.currentNode
    expect(visible).not.toBeNull()
    const range = document.createRange(); range.selectNodeContents(visible!)
    const selection = window.getSelection()!; selection.removeAllRanges(); selection.addRange(range)
    const anchor = captureAnchor(selection, 'aux-session', 'core:agent')!
    expect(anchor.quote).toBe('Why')
    expect(anchor.start).toBe(prefix.length)
    expect(anchor.end).toBe(prefix.length + 3)
  })
})
