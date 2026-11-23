// @vitest-environment jsdom
/**
 * user:“Office走分屏路径，自动打开分屏或为已有分屏增加标签页”+
 * (验收四条：① 分屏收着的时候点文档也要把它亮出来；② 已经有分屏时，文档标签落进分屏，
 *  不会顶掉主区里的会话；③ 已经有同类标签就复用那块屏，不无限开新屏；
 *  ④ 灯箱遇到只有分屏能渲染的文档时，直接交接过去而不是停在“看不了”。)
 */
import { afterEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import PreviewLightbox, { type PreviewResolver } from '../src/preview/PreviewLightbox.vue'
import { openInLightbox, resetPreviewLightbox } from '../src/preview/usePreviewLightbox'
import { filePreviewTarget } from '../src/preview/target'
import { openFileInSplit } from '../src/split/openFile'
import { useSplitPreviewPreference } from '../src/split/previewPreference'
import { useWorkspace } from '../src/workspace/useWorkspace'
import { WorkspaceKey } from '../src/workspace/context'
import type { WorkspaceController } from '../src/workspace/types'

function makeWorkspace(): WorkspaceController {
  const controller = useWorkspace(ref('office-split-test'), undefined, undefined, { persist: false })
  controller.setBounds({ x: 0, y: 0, width: 1400, height: 900 })
  return controller
}

const paneOf = (workspace: WorkspaceController, id: string) => (
  workspace.tabs.value.find(entry => entry.tab.id === id)?.pane || ''
)

afterEach(() => {
  useSplitPreviewPreference().setEnabled(true)
  resetPreviewLightbox()
  document.body.innerHTML = ''
})

describe('office files open in the split pane', () => {
  it('分屏收着的时候打开文档，分屏自动亮出来', () => {
    const workspace = makeWorkspace()
    workspace.state.hidden = true
    const tab = openFileInSplit(workspace, 'E:/p/季度报告.docx', { workRoot: 'E:/p' })
    expect(tab, '文档没有拿到标签页').not.toBeNull()
    expect(tab!.kind).toBe('preview')
    expect(workspace.state.hidden).toBe(false)
    expect(workspace.state.mainTab?.resource).toBe('E:/p/季度报告.docx')
  })

  it('已经有分屏时，文档标签落进那块分屏，不顶掉主区', () => {
    const workspace = makeWorkspace()
    const right = workspace.split('main', 'right')
    expect(right).toBeTruthy()
    workspace.add('browser', 'https://example.com', '浏览器', right!)
    // 用户回到会话里点击，此时活动屏是主区。
    workspace.state.activePane = 'main'
    const tab = openFileInSplit(workspace, 'E:/p/预算.xlsx', { workRoot: 'E:/p' })
    expect(tab).not.toBeNull()
    expect(paneOf(workspace, tab!.id)).toBe(right)
    // 主区仍然是会话本体：文档没有把正在聊的会话顶掉。
    expect(paneOf(workspace, 'agent-main')).toBe('main')
  })

  it('已经有同类标签就复用那块屏，不无限开新屏', () => {
    const workspace = makeWorkspace()
    const first = openFileInSplit(workspace, 'E:/p/季度报告.docx', { workRoot: 'E:/p' })
    const right = workspace.split('main', 'right')!
    workspace.add('browser', 'https://example.com', '浏览器', right)
    const second = openFileInSplit(workspace, 'E:/p/预算.xlsx', { workRoot: 'E:/p' })
    expect(paneOf(workspace, second!.id)).toBe(paneOf(workspace, first!.id))
  })

  it('灯箱遇到 Office 文档时交给分屏并把灯箱关掉', async () => {
    const workspace = makeWorkspace()
    const resolveOffice: PreviewResolver = async () => ({
      mode: 'unsupported',
      reason: 'Word 文档要用分屏里的渲染器打开',
      title: '季度报告.docx',
    })
    const wrapper = mount(PreviewLightbox, {
      props: { resolver: resolveOffice, transport: { request: async () => ({ status: 200, headers: {}, body: new Uint8Array() }) } as never },
      attachTo: document.body,
      global: { provide: { [WorkspaceKey as unknown as string]: workspace } },
    })
    openInLightbox(filePreviewTarget('E:/p/季度报告.docx', { workRoot: 'E:/p' }))
    await flushPromises()
    await nextTick()
    await flushPromises()
    expect(workspace.tabs.value.some(entry => entry.tab.resource === 'E:/p/季度报告.docx')).toBe(true)
    expect(workspace.state.hidden).toBe(false)
    expect(document.querySelector('[data-preview-lightbox]')).toBeNull()
    wrapper.unmount()
  })
})
