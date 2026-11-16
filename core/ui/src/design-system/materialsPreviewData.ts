// user:“交互测试”+(资料展厅操作使用独立内存，不打开、上传或删除实际文件)。
export function createMaterialsPreviewData(onUpdate?: (item: { tags: string[]; rating: number }) => void) {
  const createItem = (id: string, name: string, folder = '', tags: string[] = []) => ({
    artifact_id: id, name, path: `workspace://${name}`, uri: `workspace://${name}`, kind: 'file', role: 'deliverable', mime_type: 'text/plain', favorite: false, deleted: false, folder, updated_at: '2026-01-01', tags, rating: 0,
  })
  let items = [createItem('sample-a', 'sample-a.txt'), createItem('sample-b', 'sample-b.txt', '', ['button'])]
  let uploads = 0
  async function rpc(method: string, params: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    if (method === 'artifact.list') return { artifacts: structuredClone(items) }
    if (method === 'artifact.stats') return { count: items.length, bytes: 0 }
    if (method === 'artifact.delete') {
      const ids = Array.isArray(params.artifact_ids) ? params.artifact_ids : []
      items = items.filter(item => !ids.includes(item.artifact_id)); return {}
    }
    const item = items.find(entry => entry.artifact_id === params.artifact_id)
    if (!item) throw new Error('示例不存在')
    if (method === 'artifact.open') return { opened: item.artifact_id }
    if (method === 'artifact.text') return { text: '本地示例内容' }
    if (method === 'artifact.rating') item.rating = Number(params.rating)
    else if (method === 'artifact.tags') item.tags = Array.isArray(params.tags) ? params.tags.map(String) : []
    else if (method === 'artifact.favorite') item.favorite = Boolean(params.favorite)
    else if (method === 'artifact.folder') item.folder = String(params.folder ?? '')
    else throw new Error('展厅示例不支持此操作')
    onUpdate?.(item)
    return { artifact: structuredClone(item) }
  }
  async function upload(folder = ''): Promise<void> {
    uploads += 1
    items.push(createItem(`sample-upload-${uploads}`, `示例上传-${uploads}.txt`, folder))
  }
  return { rpc, upload }
}
