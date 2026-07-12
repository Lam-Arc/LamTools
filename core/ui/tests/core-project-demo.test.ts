import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { buildCoreProjectGroups } from '../src/projects/types'

describe('Core project workspace grouping', () => {
  it('groups sessions by persisted project and displays its path', () => {
    const groups = buildCoreProjectGroups(
      [{ id: 'project-1', name: 'Docs', workRoot: 'E:\\docs' }],
      [{ id: 'session-1', title: 'Write guide', metadata: { project_id: 'project-1', work_root: 'E:\\docs' } }],
    )

    expect(groups[0]).toMatchObject({ id: 'project-1', name: 'Docs', workRoot: 'E:\\docs' })
    expect(groups[0].sessions).toHaveLength(1)
  })

  it('keeps historical sessions without project_id in one explicit compatibility group', () => {
    const groups = buildCoreProjectGroups([], [
      { id: 'old-1', title: 'Legacy one', metadata: { work_root: 'E:\\one' } },
      { id: 'old-2', title: 'Legacy two' },
    ])

    expect(groups).toEqual([expect.objectContaining({ id: 'unassigned', name: 'Unassigned', sessions: expect.any(Array) })])
    expect(groups[0].sessions).toHaveLength(2)
  })
})

describe('Core project demo wiring', () => {
  it('replaces the synthetic group with project creation, project actions, and persisted session metadata', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')

    expect(source).toContain('<CoreProjectCreate')
    expect(source).toContain('<CoreAgentsEditor')
    expect(source).toContain('createCoreProjectClient')
    expect(source).toContain('buildCoreProjectGroups')
    expect(source).toContain('project_id')
    expect(source).not.toContain("name: 'Core Agent'")
  })
})
