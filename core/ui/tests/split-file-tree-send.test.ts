import { mount } from '@vue/test-utils'
import { flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import CoreSplitFileTree from '../src/components/CoreSplitFileTree.vue'
import { closeContextMenu, contextMenuState } from '../src/components/context-menu/context-menu.ts'
import type { SplitFileEntry } from '../src/split/native.ts'

// user:“CoreSplitFileTree.vue 右键菜单加「发送到设备」，复用现成 SendToDeviceMenu；
// 发送资格沿用现有判定，不另写”+
// (这里只证明两件事：文件行右键能拿到这一项、目录行拿不到；点下去出现的清单是那个
//  现成组件，而不是又造一个发送入口。)

const ROOT = 'E:/demo'
const TREE: Record<string, SplitFileEntry[]> = {
  [ROOT]: [
    { name: '笔记.md', path: `${ROOT}/笔记.md`, directory: false },
    { name: '示例目录', path: `${ROOT}/示例目录`, directory: true },
  ] as SplitFileEntry[],
  [`${ROOT}/示例目录`]: [
    { name: '深处.txt', path: `${ROOT}/示例目录/深处.txt`, directory: false },
  ] as SplitFileEntry[],
}

const listFiles = async (_root: string, path: string): Promise<SplitFileEntry[]> => TREE[path] ?? []

afterEach(() => { closeContextMenu() })

async function mountTree() {
  const wrapper = mount(CoreSplitFileTree, { props: { root: ROOT, listFiles } })
  await flushPromises()
  await nextTick()
  return wrapper
}

function rowByName(wrapper: Awaited<ReturnType<typeof mountTree>>, name: string) {
  const row = wrapper.findAll('[role="treeitem"]').find(item => item.text().includes(name))
  if (!row) throw new Error(`没有找到文件树行：${name}`)
  return row
}

function contextMenuEvent(): MouseEvent {
  return new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 60, clientY: 70 })
}

describe('文件树的「发送到设备」入口', () => {
  it('文件行右键给出「发送到设备」，点了出现统一的设备清单', async () => {
    const wrapper = await mountTree()
    const row = rowByName(wrapper, '笔记.md')
    row.element.dispatchEvent(contextMenuEvent())
    await nextTick()

    const labels = contextMenuState.items.map(item => ('label' in item ? item.label : ''))
    expect(labels).toContain('发送到设备')

    const send = contextMenuState.items.find(item => 'label' in item && item.label === '发送到设备')
    await (send as { action: () => unknown }).action()
    await flushPromises()
    await nextTick()

    const layer = wrapper.find('[data-split-file-send]')
    expect(layer.exists()).toBe(true)
    // 复用的是现成的发送清单组件，它的根节点带 data-send-to-device。
    expect(layer.find('[data-send-to-device]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('目录行右键没有「发送到设备」（发的是文件，不是目录）', async () => {
    const wrapper = await mountTree()
    const row = rowByName(wrapper, '示例目录')
    row.element.dispatchEvent(contextMenuEvent())
    await nextTick()

    const labels = contextMenuState.items.map(item => ('label' in item ? item.label : ''))
    expect(labels).toContain('打开')
    expect(labels).not.toContain('发送到设备')
    wrapper.unmount()
  })

  it('清单里的资格判定来自统一实现：没宿主管道时如实说明不能发', async () => {
    const wrapper = await mountTree()
    const row = rowByName(wrapper, '笔记.md')
    row.element.dispatchEvent(contextMenuEvent())
    await nextTick()
    const send = contextMenuState.items.find(item => 'label' in item && item.label === '发送到设备')
    await (send as { action: () => unknown }).action()
    await flushPromises()
    await nextTick()

    // 测试环境没有 Tauri 宿主：清单必须说出来，而不是给一个点不动的空列表。
    expect(wrapper.find('[data-split-file-send]').text()).toContain('桌面应用')
    wrapper.unmount()
  })
})
