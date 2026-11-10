import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import MaterialsView from '../src/components/MaterialsView.vue'

function artifact(id: string, name: string, tags: string[], rating = 0) {
  return {
    artifact_id: id,
    name,
    path: `workspace://${name}`,
    uri: `workspace://${name}`,
    kind: 'file',
    role: 'deliverable',
    mime_type: 'text/plain',
    favorite: false,
    deleted: false,
    folder: '',
    updated_at: new Date().toISOString(),
    tags,
    rating,
  }
}

function makeRpc(rows: ReturnType<typeof artifact>[]) {
  const state = rows.map(row => ({ ...row }))
  const rpc = vi.fn(async (method: string, params: Record<string, unknown> = {}) => {
    if (method === 'artifact.list') return { artifacts: state }
    if (method === 'artifact.stats') return { count: state.length, bytes: 10 }
    if (method === 'artifact.tags') {
      const row = state.find(item => item.artifact_id === params.artifact_id)
      if (row) row.tags = [...(params.tags as string[])]
      return { artifact: row }
    }
    if (method === 'artifact.rating') {
      const row = state.find(item => item.artifact_id === params.artifact_id)
      if (row) row.rating = Number(params.rating ?? 0)
      return { artifact: row }
    }
    return {}
  })
  return { rpc, state }
}

function mountView(rows: ReturnType<typeof artifact>[]) {
  const { rpc, state } = makeRpc(rows)
  const wrapper = mount(MaterialsView, {
    props: {
      projectId: 'p1',
      workRoot: '/lab',
      requestRpc: rpc as never,
      transport: {} as never,
      uploadFiles: async () => {},
    },
  })
  return { wrapper, rpc, state }
}

describe('资料库 · 标签输入', () => {
  it('输入后按回车落成新标签', async () => {
    const { wrapper, rpc, state } = mountView([artifact('a1', 'one.css', ['css'])])
    await flushPromises()

    const input = wrapper.get('[data-material-tag-input="a1"]')
    await input.setValue('but')
    await input.trigger('keydown.enter')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('artifact.tags', expect.objectContaining({ artifact_id: 'a1', tags: ['css', 'but'] }))
    expect(state[0].tags).toEqual(['css', 'but'])
  })

  it('空格也算提交，并且统一转小写、重复的忽略', async () => {
    const { wrapper, rpc, state } = mountView([artifact('a1', 'one.css', ['css'])])
    await flushPromises()

    const input = wrapper.get('[data-material-tag-input="a1"]')
    await input.setValue('  Button ')
    await input.trigger('keydown.space')
    await flushPromises()
    expect(state[0].tags).toEqual(['css', 'button'])

    const calls = rpc.mock.calls.filter(call => call[0] === 'artifact.tags').length
    await wrapper.get('[data-material-tag-input="a1"]').setValue('button')
    await wrapper.get('[data-material-tag-input="a1"]').trigger('keydown.enter')
    await flushPromises()
    expect(rpc.mock.calls.filter(call => call[0] === 'artifact.tags').length).toBe(calls)
  })

  it('聚焦时按已前缀补全，点一条直接落成标签', async () => {
    const { wrapper, state } = mountView([
      artifact('a1', 'one.css', ['css']),
      artifact('a2', 'two.css', ['css', 'button', 'badge']),
    ])
    await flushPromises()

    const input = wrapper.get('[data-material-tag-input="a1"]')
    await input.trigger('focus')
    await input.setValue('but')
    await flushPromises()

    const options = wrapper.findAll('[data-material-tag-suggest]')
    expect(options.map(option => option.text())).toContain('button')

    await options[0].trigger('mousedown')
    await flushPromises()
    expect(state[0].tags).toContain('button')
  })

  it('点已有标签仍然能删掉', async () => {
    const { wrapper, state } = mountView([artifact('a1', 'one.css', ['css', 'button'])])
    await flushPromises()

    await wrapper.get('.material-tag').trigger('click')
    await flushPromises()
    expect(state[0].tags).toEqual(['button'])
  })
})
