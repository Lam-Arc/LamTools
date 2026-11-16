import { describe, expect, it } from 'vitest'
import { createMaterialsPreviewData } from '../src/design-system/materialsPreviewData'

// user:“交互测试”+(资料收藏、归档、移除和上传均只更改当前展厅的内存示例)。
describe('isolated materials preview data', () => {
  it('supports the actions used by the real materials page without external access', async () => {
    const data = createMaterialsPreviewData()
    await data.rpc('artifact.favorite', { artifact_id: 'sample-a', favorite: true })
    await data.rpc('artifact.folder', { artifact_id: 'sample-a', folder: '归档' })
    await data.rpc('artifact.tags', { artifact_id: 'sample-a', tags: ['设计'] })
    await data.rpc('artifact.rating', { artifact_id: 'sample-a', rating: 3 })
    expect((await data.rpc('artifact.open', { artifact_id: 'sample-a' })).opened).toBe('sample-a')
    expect((await data.rpc('artifact.list')).artifacts).toContainEqual(expect.objectContaining({ artifact_id: 'sample-a', favorite: true, folder: '归档', tags: ['设计'], rating: 3 }))
    await data.upload('归档')
    expect((await data.rpc('artifact.list')).artifacts).toContainEqual(expect.objectContaining({ name: '示例上传-1.txt', folder: '归档' }))
    await data.rpc('artifact.delete', { artifact_ids: ['sample-a', 'sample-b'] })
    expect((await data.rpc('artifact.stats')).count).toBe(1)
    expect((await createMaterialsPreviewData().rpc('artifact.stats')).count).toBe(2)
  })
})
