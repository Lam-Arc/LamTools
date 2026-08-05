export interface WriterProjectWorkspaceResult {
  project: { id: string; name: string; work_root: string }
  session: { id: string; title: string; work_root: string }
}

export async function saveWriterProjectAgents(
  projectId: string,
  content: string,
  save: (projectId: string, content: string) => Promise<unknown>,
): Promise<void> {
  await save(projectId, content)
}

export async function createWriterProjectWorkspace(
  payload: { name: string; work_root: string },
  dependencies: {
    createProject: (payload: { name: string; work_root: string }) => Promise<WriterProjectWorkspaceResult>
    onCreated: (created: WriterProjectWorkspaceResult) => void
    selectSession: (sessionId: string) => Promise<void>
    refresh: () => Promise<void>
  },
): Promise<WriterProjectWorkspaceResult> {
  const workRoot = payload.work_root.trim()
  if (!workRoot) throw new Error('work_root is required')
  const created = await dependencies.createProject({
    name: payload.name.trim() || workRoot.split(/[/\\]/).filter(Boolean).pop() || '未命名',
    work_root: workRoot,
  })
  dependencies.onCreated(created)
  await dependencies.selectSession(created.session.id)
  await dependencies.refresh()
  return created
}
