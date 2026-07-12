export interface WriterProjectAgents {
  content: string
  exists: boolean
}

export function shouldApplyWriterProjectAgents(
  targetProjectId: string,
  requestToken: number,
  currentProjectId: string,
  currentRequestToken: number,
): boolean {
  return targetProjectId === currentProjectId && requestToken === currentRequestToken
}

export function createWriterProjectAgentsSaveHandler(
  projectId: string,
  save: (projectId: string, content: string) => Promise<WriterProjectAgents>,
): (content: string) => Promise<WriterProjectAgents> {
  return (content) => save(projectId, content)
}
