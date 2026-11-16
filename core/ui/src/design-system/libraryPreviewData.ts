import type { CoreProjectClient } from '@/projects/client'

// user:“交互测试”+(展厅文件和目录仅存于独立内存，所有操作均不触及真实项目)。
export function createLibraryPreviewData() {
  let memories = [
    { path: '示例记忆.md', is_dir: false, size: 12, modified: '', summary: '本地示例', content: '# 示例记忆\n\n本地预览内容。' },
    { path: '示例目录', is_dir: true, size: 0, modified: '', summary: '', content: '' },
  ]
  let entries = [{ name: '示例方案.md', path: '方案/示例方案.md', folder: '', title: '示例方案', status: 'draft', summary: '本地预览内容', favorite: false, size: 12, updated_at: 0 }]
  let folders = [{ name: '示例目录', path: '方案/示例目录', dir: '示例目录', parent: '', count: 0 }]
  const contents = new Map([['方案/示例方案.md', '# 示例方案\n\n本地预览内容。']])
  const clone = <T>(value: T): T => structuredClone(value)
  const getEntry = (path: string) => { const entry = entries.find(item => item.path === path); if (!entry) throw new Error('示例方案不存在'); return entry }
  const markdownName = (name: string) => name.toLowerCase().endsWith('.md') ? name : `${name}.md`
  const pathFor = (folder: string, name: string) => `方案/${folder ? `${folder}/` : ''}${name}`
  const changePath = (path: string, folder: string, name: string) => {
    const entry = getEntry(path); const next = pathFor(folder, name)
    if (next !== path && entries.some(item => item.path === next)) throw new Error('示例名称已存在')
    contents.set(next, contents.get(path) ?? ''); if (next !== path) contents.delete(path)
    Object.assign(entry, { path: next, folder, name, title: name.replace(/\.md$/i, '') })
    return { entry: clone(entry) }
  }
  async function memoryRpc(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    const path = String(params.path ?? '')
    if (method === 'memory.projects') return { projects: [] }
    if (method === 'memory.tree') return { entries: clone(memories.map(({ content, ...entry }) => entry)) }
    const item = memories.find(entry => entry.path === path)
    if (method === 'memory.read') { if (!item || item.is_dir) throw new Error('示例记忆不存在'); return { path, content: item.content } }
    if (method === 'memory.write') {
      if (item?.is_dir) throw new Error('目录不能作为文件写入')
      const content = String(params.content ?? '')
      if (item) { item.content = content; item.size = content.length }
      else memories.push({ path, is_dir: false, size: content.length, modified: '', summary: '', content })
      return { path }
    }
    if (method === 'memory.mkdir') { if (item) throw new Error('示例名称已存在'); memories.push({ path, is_dir: true, size: 0, modified: '', summary: '', content: '' }); return { path } }
    if (method === 'memory.delete') { if (!item) throw new Error('示例不存在'); memories = memories.filter(entry => entry.path !== path && !entry.path.startsWith(`${path}/`)); return {} }
    if (method === 'memory.rename') {
      const next = String(params.new_path ?? '')
      if (!item || memories.some(entry => entry.path === next)) throw new Error('示例不存在或名称已占用')
      memories = memories.map(entry => entry.path === path || entry.path.startsWith(`${path}/`) ? { ...entry, path: next + entry.path.slice(path.length) } : entry)
      return { path: next }
    }
    throw new Error('展厅示例不支持此操作')
  }
  const client = {
    list: async () => [],
    listPlanLibrary: async () => ({ dir: '方案', entries: clone(entries), folders: clone(folders.map(folder => ({ ...folder, count: entries.filter(entry => entry.folder === folder.dir || entry.folder.startsWith(`${folder.dir}/`)).length }))) }),
    readFile: async (_project: string, path: string) => { getEntry(path); return { path, content: contents.get(path) ?? '' } },
    writeFile: async (_project: string, path: string, content: string) => { getEntry(path); contents.set(path, content); return { path, content } },
    createPlanLibraryFile: async (_project: string, title: string, folder = '') => {
      const name = markdownName(title); const path = pathFor(folder, name)
      if (entries.some(entry => entry.path === path)) throw new Error('示例名称已存在')
      const entry = { name, path, folder, title: name.replace(/\.md$/i, ''), status: 'draft', summary: '', favorite: false, size: 0, updated_at: 0 }
      entries.push(entry); contents.set(path, ''); return { entry: clone(entry) }
    },
    createPlanLibraryFolder: async (_project: string, dir: string) => {
      if (folders.some(folder => folder.dir === dir)) throw new Error('示例名称已存在')
      const name = dir.split('/').pop()!; const parent = dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : ''
      const folder = { name, path: `方案/${dir}`, dir, parent, count: 0 }; folders.push(folder); return { folder: clone(folder) }
    },
    deletePlanLibraryFile: async (_project: string, path: string) => { getEntry(path); entries = entries.filter(entry => entry.path !== path); contents.delete(path); return { deleted: path } },
    deletePlanLibraryFolder: async (_project: string, path: string) => { const folder = folders.find(item => item.path === path); if (!folder) throw new Error('示例目录不存在'); if (entries.some(entry => entry.folder === folder.dir || entry.folder.startsWith(`${folder.dir}/`)) || folders.some(item => item.parent === folder.dir)) throw new Error('示例目录不为空'); folders = folders.filter(item => item !== folder); return { deleted: path } },
    favoritePlanLibraryFile: async (_project: string, path: string, favorite: boolean) => { const entry = getEntry(path); entry.favorite = favorite; return { entry: clone(entry) } },
    renamePlanLibraryFile: async (_project: string, path: string, name: string) => changePath(path, getEntry(path).folder, markdownName(name)),
    movePlanLibraryFile: async (_project: string, path: string, folder: string) => changePath(path, folder, getEntry(path).name),
  } as unknown as CoreProjectClient
  return { memoryRpc, client }
}
