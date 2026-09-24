import { afterEach, describe, expect, it, vi } from 'vitest'

const { invokeMock } = vi.hoisted(() => ({ invokeMock: vi.fn() }))

vi.mock('@tauri-apps/api/core', () => ({ invoke: invokeMock }))

import { StandaloneExtensionsStore } from '../src/standalone/StandaloneExtensionsStore'
import { MemoryStandaloneStateStorage } from '../src/standalone/StandaloneStateStorage'

/** The app-private skill root, modelled the way the host implements it. */
function userSkillHost() {
  const skills = new Map<string, { description: string; content: string }>()
  invokeMock.mockImplementation(async (command: string, args: Record<string, unknown> = {}) => {
    if (command === 'sunday_user_skills') {
      return [...skills.entries()].map(([name, skill]) => ({
        name,
        description: skill.description,
        location: `skills/${name}/SKILL.md`,
      }))
    }
    if (command === 'sunday_skill_create') {
      const name = String(args.name || '')
      if (!name.trim()) throw new Error('标题（name）是必填的')
      if (!/^[A-Za-z0-9._-]+$/.test(name)) throw new Error('技能名只允许字母/数字/._-（将作为目录名）')
      if (!String(args.description || '').trim()) throw new Error('描述（description）是必填的')
      if (!String(args.content || '').trim()) throw new Error('内容（content）是必填的')
      if (skills.has(name)) throw new Error(`技能 '${name}' 已存在`)
      skills.set(name, { description: String(args.description), content: String(args.content) })
      return { name, description: String(args.description), location: `skills/${name}/SKILL.md` }
    }
    if (command === 'sunday_skill_delete') {
      const name = String(args.name || '')
      if (!skills.delete(name)) throw new Error(`技能 '${name}' 不存在或不可删除`)
      return { name, location: `skills/${name}/SKILL.md`, deleted: true }
    }
    if (command === 'sunday_study_skill_catalog') return []
    throw new Error(`unexpected ${command}`)
  })
  return skills
}

function store() {
  return new StandaloneExtensionsStore(
    new MemoryStandaloneStateStorage<any>(),
    async () => [],
  )
}

afterEach(() => { invokeMock.mockReset(); vi.unstubAllGlobals() })

describe('standalone user skills', () => {
  it('creates, lists and deletes a skill through the host, and refuses what the host refuses', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    const skills = userSkillHost()
    const manager = store()

    const created = await manager.handleRpc('skill.create', {
      name: 'my-skill',
      description: '何时使用',
      content: '加载后的指引',
    })
    expect(created).toEqual({ name: 'my-skill', location: 'skills/my-skill/SKILL.md', created: true })
    expect(skills.get('my-skill')?.content).toBe('加载后的指引')

    // The new skill shows up as deletable; bundled and plugin skills do not.
    const listed = (await manager.handleRpc('skill.list', {}))!.skills as Array<Record<string, unknown>>
    expect(listed.find(skill => skill.name === 'my-skill')).toMatchObject({
      source: 'user',
      deletable: true,
      enabled: true,
      description: '何时使用',
    })
    expect(listed.find(skill => skill.name === 'plugin-manager')).toMatchObject({ deletable: false })

    // Host-side validation reaches the panel instead of being swallowed.
    await expect(manager.handleRpc('skill.create', { name: 'bad name', description: 'd', content: 'c' }))
      .rejects.toThrow('技能名只允许字母/数字')
    await expect(manager.handleRpc('skill.create', { name: 'other', description: '', content: 'c' }))
      .rejects.toThrow('描述（description）是必填的')
    await expect(manager.handleRpc('skill.create', { name: 'my-skill', description: 'd', content: 'c' }))
      .rejects.toThrow('已存在')

    // A bundled skill cannot be deleted through this path.
    await expect(manager.handleRpc('skill.delete', { name: 'plugin-manager' }))
      .rejects.toThrow('只允许删除自建技能')
    expect(await manager.handleRpc('skill.delete', { name: 'my-skill' }))
      .toEqual({ name: 'my-skill', location: 'skills/my-skill/SKILL.md', deleted: true })
    expect((await manager.handleRpc('skill.list', {}))!.skills)
      .not.toEqual(expect.arrayContaining([expect.objectContaining({ name: 'my-skill' })]))
  })

  it('forgets a disabled flag when the skill is deleted and recreated', async () => {
    vi.stubGlobal('window', { __TAURI_INTERNALS__: {} })
    userSkillHost()
    const manager = store()
    await manager.handleRpc('skill.create', { name: 'flakey', description: 'd', content: 'c' })
    await manager.handleRpc('skill.disable', { name: 'flakey' })
    expect((await manager.handleRpc('skill.list', {}))!.skills).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'flakey', enabled: false }),
    ]))
    await manager.handleRpc('skill.delete', { name: 'flakey' })
    await manager.handleRpc('skill.create', { name: 'flakey', description: 'd2', content: 'c2' })
    // A stale "disabled" entry would make a fresh skill invisible to the model.
    expect((await manager.handleRpc('skill.list', {}))!.skills).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: 'flakey', enabled: true }),
    ]))
  })
})
