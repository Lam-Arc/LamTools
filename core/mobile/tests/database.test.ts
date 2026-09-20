import { describe, expect, it } from 'vitest'
import { createLocalDatabase } from '../src/storage/Database'

describe('memory local database recovery', () => {
  it('reads the active scoped state after reopening', async () => {
    const name = `memory-recovery-${crypto.randomUUID()}`
    const first = createLocalDatabase<Record<string, unknown>>(name)
    await first.open()
    const firstState = { workspaceId: 'workspace-a', value: 'A' }
    const secondState = { workspaceId: 'workspace-b', value: 'B' }
    await first.writeScope?.('workspace:workspace-a', firstState)
    await first.writeScope?.('workspace:workspace-b', secondState)

    expect(await first.read()).toEqual(secondState)
    await first.close()

    const reopened = createLocalDatabase<Record<string, unknown>>(name)
    await reopened.open()
    await expect(reopened.read()).resolves.toEqual(secondState)
    expect(await reopened.readScope?.('workspace:workspace-a')).toEqual(firstState)
    expect(await reopened.readScope?.('workspace:workspace-b')).toEqual(secondState)
    await reopened.close()
  })
})
