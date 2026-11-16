import { describe, expect, it } from 'vitest'
import { createLibraryPreviewData } from '../src/design-system/libraryPreviewData'

// user:“交互测试”+(示例中的增删改查只影响独立内存，重新创建时恢复初始状态)。
describe('isolated library preview data', () => {
  it('supports memory file and folder operations with descendants', async () => {
    const { memoryRpc } = createLibraryPreviewData()
    await memoryRpc('memory.mkdir', { path: '项目' })
    await memoryRpc('memory.write', { path: '项目/笔记.md', content: '内容' })
    await memoryRpc('memory.rename', { path: '项目', new_path: '归档' })
    expect((await memoryRpc('memory.read', { path: '归档/笔记.md' })).content).toBe('内容')
    await memoryRpc('memory.delete', { path: '归档' })
    expect((await memoryRpc('memory.tree')).entries).not.toContainEqual(expect.objectContaining({ path: '归档/笔记.md' }))
    expect((await createLibraryPreviewData().memoryRpc('memory.tree')).entries).toContainEqual(expect.objectContaining({ path: '示例记忆.md' }))
  })
  it('supports plan creation, editing, moving, favorites, renaming and deletion', async () => {
    const { client } = createLibraryPreviewData()
    await client.createPlanLibraryFolder('sample', '工作')
    const created = (await client.createPlanLibraryFile('sample', '测试', '')).entry
    await client.writeFile('sample', created.path, '正文')
    const moved = (await client.movePlanLibraryFile('sample', created.path, '工作')).entry
    const favorite = (await client.favoritePlanLibraryFile('sample', moved.path, true)).entry
    expect(favorite.favorite).toBe(true)
    const renamed = (await client.renamePlanLibraryFile('sample', moved.path, '新名称')).entry
    expect((await client.readFile('sample', renamed.path)).content).toBe('正文')
    await client.deletePlanLibraryFile('sample', renamed.path)
    await client.deletePlanLibraryFolder('sample', '方案/工作')
    const result = await client.listPlanLibrary('sample')
    expect(result.entries.some(item => item.path === renamed.path)).toBe(false)
    expect(result.folders.some(item => item.dir === '工作')).toBe(false)
  })
})
