import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import ChatThread from '../src/components/ChatThread.vue'
import { createFakeTransport } from './fake-transport'

const testTransport = createFakeTransport()

function mountChatThread(options: any = {}) {
  return mount(ChatThread, {
    ...options,
    props: { transport: testTransport, ...(options.props ?? {}) },
  })
}

const appSource = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
const layoutSource = readFileSync(resolve(process.cwd(), 'src/styles/layout.css'), 'utf8')
const workspaceSource = readFileSync(resolve(process.cwd(), 'src/components/WorkspaceShell.vue'), 'utf8')

describe('Core empty-session host wiring', () => {
  it('separates no-session, empty-session, and populated-thread branches', () => {
    expect(appSource).toMatch(/const isEmptySession = computed\(\(\) => \([\s\S]*messages\.value\.length === 0/)
    expect(appSource).toContain(':empty-session="isEmptySession"')
    expect(appSource).toContain('data-empty-session-hero')
    expect(appSource).toMatch(/<ChatThread\s+v-else/)
    expect(appSource).toContain('v-if="!isEmptySession && !threadScroll.autoFollow.value"')
    expect(appSource).toContain(':hide-composer="shouldHideComposer"')
  })

  it('keeps the empty-session layout opt-in to the Core shell state', () => {
    expect(workspaceSource).toContain("'workspace-shell--empty-session': emptySession")
    expect(workspaceSource).toContain("'composer-root--empty-session': emptySession")
    expect(layoutSource).toContain('.thread.thread--empty-session')
    expect(layoutSource).toContain('.workspace-shell--empty-session .floating-composer')
    expect(layoutSource).toMatch(/\.empty-session-hero\s*\{[\s\S]*?top:\s*calc\(var\(--empty-session-composer-top/)
    expect(layoutSource).toContain(
      '.workspace-shell--empty-session.workspace-shell--composer-center .floating-composer',
    )
    expect(layoutSource).toContain('calc(var(--space-6) * 2)')
    expect(appSource).toContain('<SundayLogo class="empty-session-logo" :size="136" animated')
    expect(layoutSource).toContain('font-size: clamp(20px, 2.2vw, 26px)')
    expect(appSource).toContain('就当给自己放个假')
    expect(appSource).toContain('芜湖，我来帮忙咯!')
    expect(appSource).not.toContain('描述你想完成的事情')
  })
})

describe('Reusable ChatThread empty slot', () => {
  it('keeps the generic empty timeline fallback unchanged', () => {
    const wrapper = mountChatThread({ props: { messages: [] } })

    expect(wrapper.find('[data-empty-session-hero]').exists()).toBe(false)
    expect(wrapper.get('.sidebar-empty').text()).toContain('暂无消息，发送一个任务。')
  })
})
