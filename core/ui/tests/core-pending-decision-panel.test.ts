import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { describe, expect, it } from 'vitest'

import CorePendingDecisionPanel from '../src/components/CorePendingDecisionPanel.vue'
import { selectPendingCoreDecisions, type CorePendingDecision } from '../src/appServer'
import { useCoreApprovalController } from '../src/composables'
import { TEXTAREA_MAX_ROWS } from '../src/helpers/autoGrowTextarea'
import type { CoreMessage, MessagePart } from '../src/types'

const appSource = readFileSync(resolve(import.meta.dirname, '../src/app/LamToolsApp.vue'), 'utf8')
const panelSource = readFileSync(resolve(import.meta.dirname, '../src/components/CorePendingDecisionPanel.vue'), 'utf8')

const APPROVAL_OPTIONS = [
  { id: 'approve', label: '批准执行', description: '允许后端继续执行这个工具调用。', response: 'approve' },
  { id: 'deny', label: '拒绝执行', description: '不执行这个工具调用，本轮停在等待点。', response: 'deny' },
]

/** Projection-shaped permission request awaiting the user. */
function approvalPart(id: string, requestId: string, message = '需要授权后才能执行命令：npm test'): MessagePart {
  return {
    id,
    partType: 'decision',
    status: 'pending',
    content: message,
    label: 'approval',
    toolName: 'run_command',
    toolArgs: { options: APPROVAL_OPTIONS },
    metadata: {
      message,
      tool_name: 'run_command',
      options: APPROVAL_OPTIONS,
      request_id: requestId,
      approval: { tier: 'full_edit', reason: 'requires approval', requires_approval: true, outside_workdir: false },
      waitingRequest: { kind: 'permission', request_id: requestId, options: APPROVAL_OPTIONS },
    },
  } as MessagePart
}

function questionPart(id: string, requestId: string, question: string): MessagePart {
  const options = [
    { id: 'A', label: '先做后端', description: '先把接口做通', response: '先做后端' },
    { id: 'B', label: '先做前端', description: '先看界面效果', response: '先做前端' },
  ]
  return {
    id,
    partType: 'decision',
    status: 'pending',
    content: question,
    label: 'approval',
    toolName: 'question',
    toolArgs: { options },
    metadata: {
      message: question,
      tool_name: 'question',
      options,
      request_id: requestId,
      waitingRequest: { kind: 'permission', request_id: requestId, options },
    },
  } as MessagePart
}

function assistantMessage(id: string, parts: MessagePart[]): CoreMessage {
  return { id, role: 'assistant', content: '', timestamp: '2026-09-28T00:00:00Z', parts }
}

function decisionsFor(parts: MessagePart[]): CorePendingDecision[] {
  return selectPendingCoreDecisions([assistantMessage('a1', parts)])
}

function mountPanel(items: CorePendingDecision[], props: Record<string, unknown> = {}) {
  return mount(CorePendingDecisionPanel, { props: { items, ...props } })
}

describe('CorePendingDecisionPanel', () => {
  it('replaces the composer input: the only text field is the panel guide', () => {
    const wrapper = mountPanel(decisionsFor([approvalPart('approval-1', 'req-1')]))

    expect(wrapper.find('[data-pending-decision-panel]').exists()).toBe(true)
    expect(wrapper.text()).toContain('需要你确认')
    expect(wrapper.find('[data-pending-decision-subject]').text()).toBe('需要授权后才能执行命令：npm test')
    // Exactly one textarea — the panel's own guidance field. No ordinary
    // composer textarea a user could mistake for the answer entry point.
    const textareas = wrapper.findAll('textarea')
    expect(textareas).toHaveLength(1)
    expect(textareas[0].attributes('data-pending-decision-guide')).toBeDefined()
    expect(wrapper.find('[data-pending-decision-guide]').exists()).toBe(true)
  })

  it('offers every option as a button with its consequence', () => {
    const wrapper = mountPanel(decisionsFor([approvalPart('approval-1', 'req-1')]))
    const buttons = wrapper.findAll('[data-decision-option-id]')

    expect(buttons.map(button => button.text())).toEqual(['批准执行', '拒绝执行'])
    expect(wrapper.text()).toContain('允许后端继续执行这个工具调用。')
    expect(wrapper.text()).toContain('不执行这个工具调用，本轮停在等待点。')
    // The permission facts are visible next to the choices.
    expect(wrapper.text()).toContain('命令')
    expect(wrapper.text()).toContain('npm test')
    expect(wrapper.text()).toContain('项目目录内')
  })

  it('sends an option click through the existing approval channel', async () => {
    const items = decisionsFor([approvalPart('approval-1', 'req-1')])
    const wrapper = mountPanel(items)

    await wrapper.find('[data-decision-option-id="deny"]').trigger('click')
    const payload = wrapper.emitted('decision-select')?.[0]?.[0] as {
      partId: string
      option: { id: string }
      response: string
    }
    expect(payload.partId).toBe('approval-1')
    expect(payload.option.id).toBe('deny')
    expect(payload.response).toBe('deny')

    // The very same payload the in-thread card produces is fed into the app's
    // decision handler — no protocol of its own.
    const calls: string[] = []
    const controller = useCoreApprovalController({
      messages: ref<CoreMessage[]>([assistantMessage('a1', [approvalPart('approval-1', 'req-1')])]),
      hasActiveThread: ref(true),
      canRespondApproval: ref(true),
      respondApproval: async (requestId, decision, guidance) => {
        calls.push(`${requestId}:${decision}:${guidance}`)
      },
      submitText: async () => {
        throw new Error('an approval must not become ordinary text')
      },
      deferText: () => {
        throw new Error('an approval must not be deferred')
      },
    })

    await expect(controller.handleDecision(payload)).resolves.toBe('approval')
    expect(calls).toEqual(['req-1:deny:deny'])
  })

  it('rests at one row and follows the length of the answer', async () => {
    const wrapper = mountPanel(decisionsFor([approvalPart('approval-1', 'req-1')]))
    const guide = wrapper.find<HTMLTextAreaElement>('[data-pending-decision-guide]')
    const field = guide.element

    // One row is the resting height; there is nothing to scroll until the
    // answer needs a second line.
    expect(guide.attributes('rows')).toBe('1')
    expect(field.style.height).toBe('')

    // jsdom has no stylesheet, so the helper measures with its fallbacks: 20px
    // line height and no padding.
    Object.defineProperty(field, 'scrollHeight', { configurable: true, value: 700 })
    await guide.setValue('第一行\n第二行\n第三行\n第四行\n第五行\n第六行')
    expect(field.style.height).toBe(`${20 * TEXTAREA_MAX_ROWS}px`)
    expect(field.style.overflowY).toBe('auto')

    // Escape clears the draft, and the field returns to its one row.
    Object.defineProperty(field, 'scrollHeight', { configurable: true, value: 20 })
    await guide.trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(field.style.height).toBe('20px')
    expect(field.style.overflowY).toBe('hidden')
  })

  it('submits free-form guidance from inside the panel', async () => {
    const items = decisionsFor([approvalPart('approval-1', 'req-1')])
    const wrapper = mountPanel(items)
    const guide = wrapper.find<HTMLTextAreaElement>('[data-pending-decision-guide]')

    // Nothing to send yet.
    expect(wrapper.find('[data-pending-decision-guide-submit]').attributes('disabled')).toBeDefined()

    await guide.setValue('换成只读命令，不要写文件')
    await guide.trigger('keydown', { key: 'Enter' })

    const payloads = wrapper.emitted('decision-select') || []
    expect(payloads).toHaveLength(1)
    const payload = payloads[0][0] as { partId: string; option: { id: string }; response: string }
    expect(payload.partId).toBe('approval-1')
    expect(payload.option.id).toBe('guide')
    expect(payload.response).toBe('换成只读命令，不要写文件')
    // The draft is consumed, so the same guidance cannot be sent twice by accident.
    expect(wrapper.find<HTMLTextAreaElement>('[data-pending-decision-guide]').element.value).toBe('')
  })

  it('does not treat Shift+Enter as a submit and clears the draft on Escape', async () => {
    const wrapper = mountPanel(decisionsFor([approvalPart('approval-1', 'req-1')]))
    const guide = wrapper.find<HTMLTextAreaElement>('[data-pending-decision-guide]')

    await guide.setValue('第一行')
    await guide.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(wrapper.emitted('decision-select')).toBeUndefined()

    await guide.setValue('第一行\n第二行')
    await guide.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('decision-select')).toBeUndefined()
    expect(wrapper.find<HTMLTextAreaElement>('[data-pending-decision-guide]').element.value).toBe('')

    // An IME composition confirm is not a submit either.
    await guide.setValue('输入法确认')
    await guide.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.emitted('decision-select')).toBeUndefined()
  })

  it('drains several waiting requests one at a time with visible state', async () => {
    const items = decisionsFor([
      approvalPart('approval-1', 'req-1', '需要授权后才能执行命令：npm test'),
      questionPart('question-1', 'req-2', '先做哪一端？'),
    ])
    const wrapper = mountPanel(items)

    expect(wrapper.text()).toContain('第 1 / 2 项')
    const queueButtons = wrapper.findAll('[data-pending-decision-item]')
    expect(queueButtons).toHaveLength(2)
    expect(queueButtons[0].attributes('aria-current')).toBe('true')
    // Each queue entry says which state it is in.
    expect(queueButtons[0].text()).toContain('待你选择')
    expect(queueButtons[1].text()).toContain('待处理')

    // The second request's own choices, facts and partId.
    await queueButtons[1].trigger('click')
    expect(wrapper.text()).toContain('第 2 / 2 项')
    expect(wrapper.find('[data-pending-decision-subject]').text()).toBe('先做哪一端？')
    expect(wrapper.findAll('[data-decision-option-id]').map(button => button.text())).toEqual(['先做后端', '先做前端'])

    await wrapper.find('[data-decision-option-id="B"]').trigger('click')
    const payload = wrapper.emitted('decision-select')?.[0]?.[0] as { partId: string; response: string }
    expect(payload.partId).toBe('question-1')
    expect(payload.response).toBe('先做前端')
  })

  it('advances to the next request when the selected one is answered', async () => {
    const items = decisionsFor([
      approvalPart('approval-1', 'req-1'),
      questionPart('question-1', 'req-2', '先做哪一端？'),
    ])
    const wrapper = mountPanel(items)

    await wrapper.setProps({ items: items.slice(1) })
    expect(wrapper.text()).toContain('等待你的选择')
    expect(wrapper.find('[data-pending-decision-subject]').text()).toBe('先做哪一端？')
  })

  it('renders nothing once every request is answered', async () => {
    const items = decisionsFor([approvalPart('approval-1', 'req-1')])
    const wrapper = mountPanel(items)
    expect(wrapper.find('[data-pending-decision-panel]').exists()).toBe(true)

    await wrapper.setProps({ items: [] })
    expect(wrapper.find('[data-pending-decision-panel]').exists()).toBe(false)
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).toBe('')
  })

  it('disables the choices and says so while the approval channel is down', async () => {
    const items = decisionsFor([approvalPart('approval-1', 'req-1')])
    const wrapper = mountPanel(items, { channelReady: false })

    expect(wrapper.findAll('[data-decision-option-id]').every(button => button.attributes('disabled') !== undefined)).toBe(true)

    await wrapper.find('[data-decision-option-id="approve"]').trigger('click')
    expect(wrapper.emitted('decision-select')).toBeUndefined()
    expect(wrapper.text()).toContain('确认通道已断开')
  })

  it('disables the choices while the decision is on the wire', async () => {
    const items = decisionsFor([approvalPart('approval-1', 'req-1')])
    items[0].submitting = true
    const wrapper = mountPanel(items)

    expect(wrapper.findAll('[data-decision-option-id]').every(button => button.attributes('disabled') !== undefined)).toBe(true)
    expect(wrapper.find('[data-pending-decision-guide]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-pending-decision-guide-submit]').attributes('disabled')).toBeDefined()
  })

  it('numbers every choice and leaves the answer field as the last row', () => {
    const wrapper = mountPanel(decisionsFor([approvalPart('approval-1', 'req-1')]))
    const indexes = wrapper.findAll('.pending-decision__option-index')

    // 1 and 2 are the offered choices; 3 is the free-form answer row.
    expect(indexes.map(index => index.text())).toEqual(['1', '2', '3'])
    expect(indexes.every(index => !index.element.closest('button'))).toBe(true)
    const answerRow = indexes[2].element.nextElementSibling
    expect(answerRow?.classList.contains('pending-decision__guide-row')).toBe(true)
    expect(answerRow?.querySelector('[data-pending-decision-guide]')).not.toBeNull()
    // The panel says once how it is operated instead of leaving the user to guess.
    expect(wrapper.find('.pending-decision__hint').text()).toContain('点击选项直接提交')
  })

  it('stays operable on a phone-width composer', () => {
    const mobile = panelSource.slice(panelSource.indexOf('@media (max-width: 640px)'))
    expect(mobile).not.toBe('')

    // Every choice starts its own row and the consequence drops under its label:
    // nothing is clipped or made unreachable at ≤640px.
    expect(mobile).toMatch(/\.pending-decision__action\s*\{\s*grid-template-columns:\s*auto minmax\(0, 1fr\);/)
    expect(mobile).toMatch(/\.pending-decision__option-desc\s*\{\s*grid-column:\s*2;/)
    expect(mobile).toMatch(/\.pending-decision__guide-row\s*\{\s*flex-direction:\s*column;/)
    expect(mobile).toMatch(/\.pending-decision__guide-submit\s*\{\s*width:\s*100%;/)
    // Long subjects and paths wrap instead of widening the composer column.
    expect(panelSource).toMatch(/\.pending-decision__subject\s*\{[^}]*overflow-wrap:\s*anywhere;/)
    expect(panelSource).toMatch(/\.pending-decision\s*\{[^}]*min-width:\s*0;/)
    // A long explanation scrolls inside the panel instead of being clipped by
    // the composer textarea height rules.
    expect(panelSource).toMatch(/\.pending-decision__guide-input\s*\{[^}]*max-height:[^}]*overflow-y:\s*auto;/)
    // No motion without a reduced-motion fallback.
    expect(panelSource).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
  })

  it('uses the composer theme area and its tokens', () => {
    expect(panelSource).toContain('--text: var(--theme-composer-text)')
    expect(panelSource).toContain('var(--theme-composer-background)')
    expect(panelSource).toContain('var(--alpha-hover)')
    expect(panelSource).toContain('var(--alpha-active)')
    expect(panelSource).toContain('var(--radius-sm)')
    expect(panelSource).toContain('var(--space-2)')
    // The answer field is a field, the send is the panel's one filled action.
    expect(panelSource).toMatch(/\.pending-decision__guide-input:focus-visible\s*\{\s*outline:\s*none;/)
    expect(panelSource).toMatch(/\.pending-decision__guide-submit\s*\{[^}]*background:\s*var\(--theme-control-background\);/)
    expect(panelSource).toMatch(/\.pending-decision__guide-submit:hover:not\(:disabled\)\s*\{\s*filter:\s*brightness\(\.94\);/)
    // Off-scale values and bespoke z-index are not allowed in on a panel that
    // sits inside the composer card.
    expect(panelSource).not.toMatch(/z-index:\s*\d/)
    expect(panelSource).not.toMatch(/border-radius:\s*\d+px/)
  })
})

describe('composer takeover wiring', () => {
  /** The `#composer-textarea` slot body, up to the next slot. */
  function composerTextareaSlot(): string {
    const start = appSource.indexOf('<template #composer-textarea>')
    expect(start).toBeGreaterThanOrEqual(0)
    const end = appSource.indexOf('<template #composer-tools>', start)
    expect(end).toBeGreaterThan(start)
    return appSource.slice(start, end)
  }

  it('replaces the composer input while a request waits', () => {
    const slot = composerTextareaSlot()
    expect(slot).toMatch(/<CorePendingDecisionPanel\s+v-if="composerTakenOver"/)
    expect(slot).toContain(':items="pendingDecisions"')
    expect(slot).toContain(':channel-ready="approvalChannelReady"')
    expect(slot).toContain('@decision-select="handlePendingDecisionSelect"')

    // The ordinary textarea only exists in the fallback branch.
    const fallbackStart = slot.indexOf('<template v-else>')
    expect(fallbackStart).toBeGreaterThan(slot.indexOf('</CorePendingDecisionPanel>'))
    expect(slot.slice(0, fallbackStart)).not.toMatch(/<textarea/)
    expect(slot.slice(fallbackStart)).toContain('ref="composerTextareaEl"')
  })

  it('derives the takeover from pending decisions in the message projection', () => {
    expect(appSource).toMatch(
      /const pendingDecisions = computed\(\(\) => \([\s\S]{0,120}selectPendingCoreDecisions\(workbench\.messages\.value\)/,
    )
    expect(appSource).toMatch(/const composerTakenOver = computed\(\(\) => pendingDecisions\.value\.length > 0\)/)
    // Plugin-owned surfaces keep their own composer.
    expect(appSource).toMatch(/selectPendingCoreDecisions\(workbench\.messages\.value\)[\s\S]{0,40}\)\)/)
    expect(appSource).toMatch(/activePluginMode\.value \? \[\] : selectPendingCoreDecisions/)
  })

  it('routes panel decisions into the single approval handler and blocks the composer send', () => {
    expect(appSource).toMatch(/async function handlePendingDecisionSelect\([\s\S]{0,320}await approvalController\.handleDecision\(payload\)/)
    expect(appSource).toMatch(/if \(composerTakenOver\.value\) return true[\s\S]{0,40}return composerInputDisabled\.value/)
  })

  it('leaves the queued-input tray and its guide actions untouched', () => {
    const preambleStart = appSource.indexOf('<template #composer-preamble>')
    const preambleEnd = appSource.indexOf('<template #composer-popover>', preambleStart)
    expect(preambleStart).toBeGreaterThanOrEqual(0)
    const preamble = appSource.slice(preambleStart, preambleEnd)
    expect(preamble).toContain('CoreQueuedInputTray')
    expect(preamble).toContain('@guide="(item) => queueController.guide(item as CoreQueuedInput)"')
    expect(appSource).toContain('v-model:draft="queuedInputDraft"')
  })
})
