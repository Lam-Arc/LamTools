import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CoreSplitFileTree from '../src/components/CoreSplitFileTree.vue'
import type { LamToolsTransport } from '../src/transport'

// user:“给现有 search_files 能力一个可见入口”+
// (验收的是入口本身：结果落在同一棵树的位置上、点开走同一条打开通道、
// 并且一定要说清「扫了多少、扫全了没有」，不能让用户以为搜的就是全部)。

function fakeTransport(body: Record<string, unknown>, status = 200) {
  const calls: Array<{ path: string }> = []
  const request = vi.fn(async (input: { path: string }) => {
    calls.push({ path: input.path })
    return { status, headers: {}, body: new TextEncoder().encode(JSON.stringify(body)) }
  })
  return { transport: { request } as unknown as LamToolsTransport, calls, request }
}

async function settle(rounds = 8): Promise<void> {
  for (let index = 0; index < rounds; index += 1) await Promise.resolve()
}

function mountTree(transport: LamToolsTransport | undefined, listFiles = vi.fn(async () => [])) {
  return mount(CoreSplitFileTree, {
    props: { root: 'E:/p', transport, listFiles },
  })
}

describe('file tree search entry', () => {
  it('searches by name and opens a hit through the same open channel as the tree', async () => {
    const { transport, calls } = fakeTransport({
      matches: [
        { path: 'src/main.ts', line: null, text: '' },
        { path: 'README.md', line: null, text: '' },
      ],
      match_count: 2,
      scanned_entries: 128,
      scan_exhausted: false,
      truncated: false,
    })
    const wrapper = mountTree(transport)
    await settle()

    await wrapper.get('[data-split-file-search-input]').setValue('main')
    await wrapper.get('[data-split-file-search-input]').trigger('keydown', { key: 'Enter' })
    await settle()

    // 走的是后台既有的检索接口，并带上工作根。
    expect(calls[0].path).toContain('/files/search')
    expect(calls[0].path).toContain('mode=name')
    expect(calls[0].path).toContain('work_root=E%3A%2Fp')

    // 命中数、扫了多少都说出来。
    expect(wrapper.get('[data-split-file-search-summary]').text()).toContain('2 处结果')
    expect(wrapper.get('[data-split-file-search-summary]').text()).toContain('128')

    // 点开命中：相对路径换成可打开的绝对路径，交给同一个 open 通道。
    await wrapper.get('[data-split-file-hit="src/main.ts"]').trigger('click')
    expect(wrapper.emitted('open')?.[0]).toEqual(['E:/p/src/main.ts'])
    wrapper.unmount()
  })

  it('says the scan was cut short instead of pretending the results are complete', async () => {
    // user:“检索带扫描预算与进度反馈…不要自研全盘索引”+(预算耗尽必须明示可能不全)。
    const { transport } = fakeTransport({
      matches: [{ path: 'a.txt', line: null, text: '' }],
      match_count: 1,
      scanned_entries: 100000,
      scan_exhausted: true,
      truncated: false,
    })
    const wrapper = mountTree(transport)
    await settle()

    await wrapper.get('[data-split-file-search-input]').setValue('a')
    await wrapper.get('[data-split-file-search-input]').trigger('keydown', { key: 'Enter' })
    await settle()

    const summary = wrapper.get('[data-split-file-search-summary]').text()
    expect(summary).toContain('扫描预算已用完')
    expect(summary).toContain('结果可能不全')
    wrapper.unmount()
  })

  it('says how many results were withheld when the list is capped', async () => {
    const { transport } = fakeTransport({
      matches: Array.from({ length: 50 }, (_, index) => ({ path: `f${index}.txt`, line: null, text: '' })),
      match_count: 50,
      scanned_entries: 400,
      scan_exhausted: false,
      truncated: true,
    })
    const wrapper = mountTree(transport)
    await settle()

    await wrapper.get('[data-split-file-search-input]').setValue('f')
    await wrapper.get('[data-split-file-search-input]').trigger('keydown', { key: 'Enter' })
    await settle()

    expect(wrapper.get('[data-split-file-search-summary]').text()).toContain('只显示前 50 条')
    wrapper.unmount()
  })

  it('switches to content mode and shows the matching line', async () => {
    const { transport, calls } = fakeTransport({
      matches: [{ path: 'src/a.ts', line: 12, text: 'const answer = 42' }],
      match_count: 1,
      scanned_entries: 30,
      scan_exhausted: false,
      truncated: false,
    })
    const wrapper = mountTree(transport)
    await settle()

    await wrapper.get('[data-split-file-search-input]').setValue('answer')
    await wrapper.get('[data-split-file-search-mode]').trigger('click')
    await settle()

    expect(calls.at(-1)?.path).toContain('mode=content')
    expect(wrapper.get('[data-split-file-hit="src/a.ts"]').text()).toContain(':12')
    expect(wrapper.get('[data-split-file-hit="src/a.ts"]').text()).toContain('const answer = 42')
    wrapper.unmount()
  })

  it('reports a backend failure instead of silently showing nothing', async () => {
    // user:“失败要有明确错误，不允许点了没反应”。
    const { transport } = fakeTransport({ detail: '项目目录不存在' }, 400)
    const wrapper = mountTree(transport)
    await settle()

    await wrapper.get('[data-split-file-search-input]').setValue('x')
    await wrapper.get('[data-split-file-search-input]').trigger('keydown', { key: 'Enter' })
    await settle()

    expect(wrapper.get('.split-content-error').text()).toContain('项目目录不存在')
    wrapper.unmount()
  })

  it('hides the search box when there is no backend channel', async () => {
    // 没有通道时不假装能搜（展厅/无后台场景），文件树本身照常可用。
    const wrapper = mountTree(undefined)
    await settle()
    expect(wrapper.find('[data-split-file-search-input]').exists()).toBe(false)
    wrapper.unmount()
  })
})
