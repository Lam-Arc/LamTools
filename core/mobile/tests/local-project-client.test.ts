import { describe, expect, it } from 'vitest'
import type { CoreProjectClient } from '@lamtools/ui'
import { createLocalFirstProjectClient, type LocalRepository } from '../src/storage'

describe('createLocalFirstProjectClient', () => {
  it('preserves valid project visuals and defaults invalid cached values', async () => {
    const repository = {
      listProjects: async () => [
        {
          id: 'valid', name: 'Valid', path: '', workRoot: '/valid', iconKey: 'rocket', colorKey: 'aurora',
          revision: 1, createdAt: '', updatedAt: '', deleted: false,
        },
        {
          id: 'legacy', name: 'Legacy', path: '/legacy', workRoot: '', iconKey: '', colorKey: 'unknown',
          revision: 1, createdAt: '', updatedAt: '', deleted: false,
        },
      ],
      listSessions: async () => [],
    } as unknown as LocalRepository
    const client = createLocalFirstProjectClient({} as CoreProjectClient, repository)

    await expect(client.list()).resolves.toMatchObject([
      { id: 'valid', workRoot: '/valid', iconKey: 'rocket', colorKey: 'aurora' },
      { id: 'legacy', workRoot: '/legacy', iconKey: 'folder', colorKey: 'gray' },
    ])
  })
})
