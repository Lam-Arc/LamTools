import { describe, expect, it } from 'vitest'
import { listPreviewSiblings } from '../src/preview/siblings'
import { filePreviewTarget } from '../src/preview/target'
import type { LamToolsTransport } from '../src/transport'

// user:“灯箱加上切换用的左右键”+
// (同目录、同类、按名字自然排序；当前文件的位置要能对上；读不到目录就当作没有邻居)。

function transportWith(entries: { name: string; path: string; directory: boolean }[], status = 200): LamToolsTransport {
  return {
    request: async () => ({
      status,
      headers: {},
      body: new TextEncoder().encode(JSON.stringify({ entries })),
    }),
  } as unknown as LamToolsTransport
}

const folder = 'E:/pics'

describe('preview siblings', () => {
  it('keeps only the same family and sorts naturally', async () => {
    const entries = [
      { name: '10-尾.png', path: `${folder}/10-尾.png`, directory: false },
      { name: '2-二.png', path: `${folder}/2-二.png`, directory: false },
      { name: '1-一.png', path: `${folder}/1-一.png`, directory: false },
      { name: 'a.pdf', path: `${folder}/a.pdf`, directory: false },
      { name: 'notes.txt', path: `${folder}/notes.txt`, directory: false },
      { name: 'sub', path: `${folder}/sub`, directory: true },
    ]
    const result = await listPreviewSiblings(filePreviewTarget(`${folder}/2-二.png`, { workRoot: 'E:/p' }), transportWith(entries))
    expect(result.items.map(item => item.kind === 'file' ? item.path : '')).toEqual([
      `${folder}/1-一.png`,
      `${folder}/2-二.png`,
      `${folder}/10-尾.png`,
    ])
    expect(result.index).toBe(1)
  })

  it('does not mix images with text or pdf', async () => {
    const entries = [
      { name: 'a.png', path: `${folder}/a.png`, directory: false },
      { name: 'b.txt', path: `${folder}/b.txt`, directory: false },
      { name: 'c.pdf', path: `${folder}/c.pdf`, directory: false },
    ]
    const png = await listPreviewSiblings(filePreviewTarget(`${folder}/a.png`), transportWith(entries))
    expect(png.items).toHaveLength(1)
    expect(png.index).toBe(0)
    const txt = await listPreviewSiblings(filePreviewTarget(`${folder}/b.txt`), transportWith(entries))
    expect(txt.items).toHaveLength(1)
  })

  it('returns nothing when the directory cannot be read', async () => {
    const target = filePreviewTarget(`${folder}/a.png`)
    expect((await listPreviewSiblings(target, transportWith([], 404))).items).toEqual([])
    expect((await listPreviewSiblings(target, undefined)).items).toEqual([])
  })

  it('keeps index -1 when the file is missing from the listing', async () => {
    const entries = [{ name: 'b.png', path: `${folder}/b.png`, directory: false }]
    const result = await listPreviewSiblings(filePreviewTarget(`${folder}/a.png`), transportWith(entries))
    expect(result.items).toHaveLength(1)
    expect(result.index).toBe(-1)
  })

  it('ignores non-file targets', async () => {
    const result = await listPreviewSiblings({ kind: 'html', html: '<p>x</p>', title: 'x' }, transportWith([]))
    expect(result).toEqual({ items: [], index: -1 })
  })
})
