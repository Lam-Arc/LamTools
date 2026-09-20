import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { normalizeNote, type StudyRpc } from '../src/study/api'
import { useStudyNotes } from '../src/study/useStudyNotes'

const wrappers: Array<ReturnType<typeof mount>> = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

function setup(rpc: StudyRpc) {
  let state!: ReturnType<typeof useStudyNotes>
  wrappers.push(mount(defineComponent({ setup() { state = useStudyNotes(rpc); return () => null } })))
  return state
}

const note = (id: string, body = '# 原始\n\n正文') => normalizeNote({
  id, title: id, path: `知识/${id}.md`, revision: 1, content_hash: 'hash-1',
  body_md: body, resource_ids: ['resource-1'], resources: [{ id: 'resource-1', title: '会话来源', kind: 'session' }],
  locks: [], links: [], backlinks: [],
})

describe('Study notes three-layer controller', () => {
  it('ignores stale tree, detail, and graph responses independently', async () => {
    let treeFirst!: (value: Record<string, unknown>) => void
    let treeSecond!: (value: Record<string, unknown>) => void
    let detailFirst!: (value: Record<string, unknown>) => void
    let detailSecond!: (value: Record<string, unknown>) => void
    let graphFirst!: (value: Record<string, unknown>) => void
    let graphSecond!: (value: Record<string, unknown>) => void
    const rpc = vi.fn((method: string): Promise<Record<string, unknown>> => {
      if (method !== 'study.notes') return Promise.resolve({})
      const call = rpc.mock.calls.filter(([name]) => name === 'study.notes').length
      if (call === 1) return new Promise<Record<string, unknown>>(resolve => { treeFirst = resolve })
      if (call === 2) return new Promise<Record<string, unknown>>(resolve => { treeSecond = resolve })
      if (call === 3) return new Promise<Record<string, unknown>>(resolve => { detailFirst = resolve })
      if (call === 4) return new Promise<Record<string, unknown>>(resolve => { graphFirst = resolve })
      if (call === 5) return new Promise<Record<string, unknown>>(resolve => { detailSecond = resolve })
      return new Promise<Record<string, unknown>>(resolve => { graphSecond = resolve })
    })
    const state = setup(rpc as StudyRpc)
    const firstTree = state.loadTree(); const secondTree = state.loadTree()
    treeSecond!({ tree: [{ id: 'fresh', title: 'Fresh.md', path: 'Fresh.md', kind: 'note' }] }); await secondTree
    treeFirst!({ tree: [{ id: 'stale', title: 'Stale.md', path: 'Stale.md', kind: 'note' }] }); await firstTree
    expect(state.tree.value[0].id).toBe('fresh')

    const firstDetail = state.selectNote(note('a')); const secondDetail = state.selectNote(note('b'))
    detailSecond!({ note: note('b') }); graphSecond!({ nodes: [{ id: 'b', title: 'B', kind: 'note' }], edges: [] }); await secondDetail
    detailFirst!({ note: note('a') }); graphFirst!({ nodes: [{ id: 'a', title: 'A', kind: 'note' }], edges: [] }); await firstDetail
    expect(state.selectedNote.value?.id).toBe('b')
    expect(state.graph.value.nodes.map(node => node.id)).toEqual(['b'])
  })

  it('saves one complete Markdown body with CAS and preserves resource IDs', async () => {
    const saved = note('a', '# 已保存\n\n新的正文')
    const rpc = vi.fn()
      .mockResolvedValueOnce({ note: note('a') })
      .mockResolvedValueOnce({ nodes: [], edges: [] })
      .mockResolvedValueOnce({ revision: 2, content_hash: 'hash-2', saved: true })
      .mockResolvedValueOnce({ note: { ...saved, revision: 2, content_hash: 'hash-2' } })
    const state = setup(rpc)
    await state.selectNote(note('a'))
    const original = note('a')
    const acknowledged = await state.saveNoteDocument(original, saved.bodyMd, { revision: 1, contentHash: 'hash-1', resourceIds: ['resource-1'] })
    expect(rpc).toHaveBeenNthCalledWith(3, 'study.notes', {
      action: 'update', note_id: 'a', body_md: saved.bodyMd, expected_revision: 1, expected_content_hash: 'hash-1', resource_ids: ['resource-1'],
    })
    expect(acknowledged?.revision).toBe(2)
    expect(state.selectedNote.value?.bodyMd).toBe(saved.bodyMd)
  })

  it('returns the write acknowledgement when the post-save detail refresh fails', async () => {
    const original = note('a')
    const rpc = vi.fn()
      .mockResolvedValueOnce({ note: original })
      .mockResolvedValueOnce({ nodes: [], edges: [] })
      .mockResolvedValueOnce({ revision: 2, content_hash: 'hash-2', saved: true })
      .mockRejectedValueOnce(Object.assign(new Error('offline'), { code: 'NETWORK_ERROR' }))
    const state = setup(rpc)
    await state.selectNote(original)
    const acknowledged = await state.saveNoteDocument(original, '# changed', { revision: 1, contentHash: 'hash-1', resourceIds: ['resource-1'] })
    expect(acknowledged).toMatchObject({ revision: 2, contentHash: 'hash-2', bodyMd: '# changed' })
    expect(state.selectedNote.value?.bodyMd).toBe('# changed')
  })

  it('keeps a draft-visible error for revision and locked-region conflicts', async () => {
    const original = note('a')
    const conflict = Object.assign(new Error('locked'), {
      code: 'NOTE_REGION_LOCKED',
      data: { error: 'NOTE_REGION_LOCKED', reason: '用户锁定', overlaps: [{ quote: '受保护', overlap_start: 2, overlap_end: 5 }] },
    })
    const rpc = vi.fn()
      .mockResolvedValueOnce({ note: original })
      .mockResolvedValueOnce({ nodes: [], edges: [] })
      .mockRejectedValueOnce(conflict)
    const state = setup(rpc)
    await state.selectNote(original)
    await expect(state.saveNoteDocument(original, '# draft')).rejects.toBe(conflict)
    expect(state.notesError.value).toContain('NOTE_REGION_LOCKED')
  })

  it('sends browser-native UTF-16 lock offsets, including surrogate pairs', async () => {
    const original = note('a', '😀 锁定这段')
    const rpc = vi.fn().mockResolvedValue({ lock_id: 'lock-1', start: 2, end: 6, quote: '锁定这段' })
    const state = setup(rpc)
    const lock = await state.lockRange(original, { start: 2, end: 6, quote: '锁定这段' })
    expect(rpc).toHaveBeenCalledWith('study.notes', expect.objectContaining({ action: 'lock_range', start: 2, end: 6, unit: 'utf16_code_unit' }))
    expect(lock).toMatchObject({ id: 'lock-1', start: 2, end: 6 })
  })

  it('filters the overall graph to note nodes and note-only edges', async () => {
    const rpc = vi.fn().mockResolvedValue({ graph: {
      nodes: [{ id: 'note-a', title: 'A', kind: 'note' }, { id: 'node-x', title: 'X', kind: 'node' }],
      edges: [{ id: 'link', source: 'note-a', target: 'note-b', kind: 'wikilink' }, { id: 'bad', source: 'note-a', target: 'node-x', kind: 'source' }],
    } })
    const state = setup(rpc)
    await state.loadGraph()
    expect(state.graph.value.nodes.map(node => node.id)).toEqual(['note-a'])
    expect(state.graph.value.edges).toHaveLength(0)
  })

  it('loads the overall graph when refreshing an empty note workspace', async () => {
    const rpc = vi.fn(async (_method: string, params?: Record<string, unknown>) => {
      if (params?.action === 'list') return { notes: [] }
      if (params?.action === 'tree') return { tree: [] }
      if (params?.action === 'graph') return { nodes: [{ id: 'note-a', title: 'A', kind: 'note' }], edges: [] }
      return {}
    })
    const state = setup(rpc)
    await state.refreshNotes()
    expect(rpc).toHaveBeenCalledWith('study.notes', { action: 'graph' })
    expect(state.graph.value.nodes.map(node => node.id)).toEqual(['note-a'])
  })
})
