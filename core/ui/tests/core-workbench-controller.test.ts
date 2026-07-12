import { describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import { useCoreWorkbenchController, type CoreWorkbenchApi } from '../src/composables/useCoreWorkbenchController'
import type { CoreMessage, CoreRuntimeEvent } from '../src/types'

describe('useCoreWorkbenchController', () => {
  it('starts a Core turn when sending a message and refreshes runtime state', async () => {
    const afterTurnMessages: CoreMessage[] = [{
      id: 'user-1',
      role: 'user',
      content: '写一个文档',
      timestamp: '2026-07-09T00:00:00.000Z',
    }, {
      id: 'assistant-1',
      role: 'assistant',
      content: '已写入 inspiration.md',
      timestamp: '2026-07-09T00:00:01.000Z',
      parts: [{
        id: 'tool-1',
        partType: 'tool_call',
        status: 'completed',
        content: '',
        toolName: 'sub_agent',
      }],
    }]
    const afterTurnEvents: CoreRuntimeEvent[] = [{
      id: 'evt-1',
      type: 'core.run_item',
      timestamp: '2026-07-09T00:00:01.000Z',
      data: { kind: 'tool_call' },
    }]
    const startedTurns: Array<{ sessionId: string; content: string }> = []
    let turnStarted = false
    const api: CoreWorkbenchApi = {
      async listSessions() {
        return [{
          id: 's1',
          title: 'Core',
          createdAt: '2026-07-09T00:00:00.000Z',
          status: 'idle',
        }]
      },
      async createSession() {
        throw new Error('not used')
      },
      async getMessages() {
        return turnStarted ? afterTurnMessages : []
      },
      async getEvents() {
        return turnStarted ? afterTurnEvents : []
      },
      async startTurn(sessionId, content) {
        startedTurns.push({ sessionId, content })
        turnStarted = true
      },
    }
    const controller = useCoreWorkbenchController({ api })

    await controller.loadInitialData()
    controller.composerText.value = '写一个文档'
    await controller.sendMessage()

    expect(startedTurns).toEqual([{ sessionId: 's1', content: '写一个文档' }])
    expect(controller.composerText.value).toBe('')
    expect(controller.messages.value).toEqual(afterTurnMessages)
    expect(controller.events.value).toEqual(afterTurnEvents)
  })

  it('shows optimistic user and assistant waiting messages while a Core turn is running', async () => {
    let resolveTurn: ((value?: unknown) => void) | null = null
    const api: CoreWorkbenchApi = {
      async listSessions() {
        return [{
          id: 's1',
          title: 'Core',
          createdAt: '2026-07-09T00:00:00.000Z',
          status: 'idle',
        }]
      },
      async createSession() {
        throw new Error('not used')
      },
      async getMessages() {
        return []
      },
      async getEvents() {
        return []
      },
      async startTurn() {
        await new Promise((resolve) => { resolveTurn = resolve })
        return {
          messages: [{
            id: 'user-real',
            role: 'user',
            content: '写一个文档',
            timestamp: '2026-07-09T00:00:00.000Z',
          }, {
            id: 'assistant-real',
            role: 'assistant',
            content: '已完成',
            timestamp: '2026-07-09T00:00:01.000Z',
          }],
          events: [],
        }
      },
    }
    const controller = useCoreWorkbenchController({ api })

    await controller.loadInitialData()
    controller.composerText.value = '写一个文档'
    const pending = controller.sendMessage()
    await nextTick()

    expect(controller.loading.value).toBe(true)
    expect(controller.messages.value).toMatchObject([
      { role: 'user', content: '写一个文档' },
      { role: 'assistant', content: '', metadata: { live: true, initialWaiting: true } },
    ])

    resolveTurn?.()
    await pending
    expect(controller.loading.value).toBe(false)
    expect(controller.messages.value.map((message) => message.id)).toEqual(['user-real', 'assistant-real'])
  })
})
