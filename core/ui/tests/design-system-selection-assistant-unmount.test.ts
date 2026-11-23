import { flushPromises, mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { ref } from 'vue'
import SelectionAssistant from '../src/study/SelectionAssistant.vue'
import { CORE_PLUGIN_MODE_CONTEXT } from '../src/plugins/context'
import { marks, showMark } from '../src/study/annotations'
import { normalizeMark } from '../src/study/api'

// user:“确保视觉、功能和交互不退化”+(组件卸载时取消未完成的请求，迟到的结果不能修改标记)。
it('cancels pending requests and ignores results after unmount', async () => {
  vi.stubGlobal('CSS', { escape: (value: string) => value, highlights: new Map() })
  const mark = normalizeMark({ id: 'sample', anchor: { document_id: 'example', quote: '示例' }, explain: '', translate: '', thread: [] })
  let finish!: (value: unknown) => void
  const rpc = vi.fn(async (method: string) => {
    if (method === 'study.marks') return { marks: [], total: 0 }
    if (method === 'study.text') return new Promise(resolve => { finish = resolve })
    return {}
  })
  const wrapper = mount(SelectionAssistant, { attachTo: document.body, props: { sessionId: 'session', mode: 'study', themeMode: 'light', jump: vi.fn() }, global: { provide: { [CORE_PLUGIN_MODE_CONTEXT as symbol]: { requestRpc: rpc, selectedModelId: ref('model'), lastEvent: ref(null), setRuntimeStatus: vi.fn() } } } })
  await flushPromises(); showMark(mark, 'explain'); await flushPromises()
  const button = [...document.querySelectorAll<HTMLButtonElement>('.selection-answer button')].find(el => el.textContent === '解释')!
  button.click(); await flushPromises()
  wrapper.unmount()
  expect(rpc.mock.calls.some(([method]) => method === 'study.text.cancel')).toBe(true)
  finish({ mark: { ...mark, explain: '迟到结果' } }); await flushPromises()
  expect(marks.value.some(item => item.id === mark.id)).toBe(false)
  marks.value = []; vi.unstubAllGlobals()
})
