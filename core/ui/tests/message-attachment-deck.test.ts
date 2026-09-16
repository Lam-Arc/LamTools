import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'
import MessageAttachmentDeck from '../src/components/MessageAttachmentDeck.vue'
import type { CoreAttachment, ToolArtifact } from '../src/types'
import { createFakeTransport } from './fake-transport'

const textAttachment: CoreAttachment = {
  id: 'att-text',
  filename: 'notes.md',
  label: 'notes.md',
  mime_type: 'text/markdown',
  size: 2048,
  preview_type: 'text',
  status: 'uploaded',
}

function mountDeck(options: any = {}) {
  return mount(MessageAttachmentDeck, {
    ...options,
    props: {
      transport: createFakeTransport(),
      ...(options.props ?? {}),
    },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('MessageAttachmentDeck', () => {
  it('keeps the intentional overlap with theme-aware neutral surfaces', () => {
    const source = readFileSync(resolve(import.meta.dirname, '../src/components/MessageAttachmentDeck.vue'), 'utf8')

    expect(source).toContain('const STACK_STEP = 36')
    expect(source).toMatch(/\.message-attachment-deck--left \.message-attachment-deck__card \+ \.message-attachment-deck__card\s*\{[\s\S]*?margin-left:\s*calc\(var\(--deck-item-step, var\(--deck-step\)\) - 72px\)/)
    expect(source).toMatch(/\.message-attachment-deck__preview\s*\{[\s\S]*?background:\s*var\(--theme-main-background\)/)
    expect(source).toMatch(/\.message-attachment-deck__visual\s*\{[\s\S]*?background:\s*var\(--theme-main-subtle-background\)/)
    expect(source).toMatch(/\.message-attachment-deck__track\s*\{[\s\S]*?min-height:\s*72px/)
    expect(source).toMatch(/\.message-attachment-deck__card--active\s*\{[\s\S]*?width:\s*220px;\s*\}/)
    expect(source).not.toContain('background: var(--theme-main-solid, #111111)')
    expect(source).not.toMatch(/\.message-attachment-deck__card--active\s*\{[\s\S]*?height:\s*112px/)
  })

  it('keeps a single element root so transition attributes are inherited', () => {
    const wrapper = mountDeck({
      attrs: { class: 'message-artifacts' },
      props: { attachments: [textAttachment] },
    })

    expect(wrapper.get('.message-attachment-deck').classes()).toContain('message-artifacts')
  })

  it('mirrors uploaded attachments to the right and expands only while hovered', async () => {
    const wrapper = mountDeck({ props: { attachments: [textAttachment], side: 'right' } })
    expect(wrapper.get('.message-attachment-deck').classes()).toContain('message-attachment-deck--right')
    const card = wrapper.get('.message-attachment-deck__card')
    expect(card.classes()).not.toContain('message-attachment-deck__card--active')

    await card.trigger('pointerenter')
    expect(card.classes()).toContain('message-attachment-deck__card--active')
    await card.trigger('pointerleave')
    await new Promise(resolve => setTimeout(resolve, 150))
    expect(card.classes()).not.toContain('message-attachment-deck__card--active')

    const preview = card.get('button')
    await preview.trigger('focus')
    expect(card.classes()).not.toContain('message-attachment-deck__card--active')
    await preview.trigger('click')
    await card.trigger('pointerleave')
    await new Promise(resolve => setTimeout(resolve, 150))
    expect(card.classes()).not.toContain('message-attachment-deck__card--active')
  })

  it('opens a text attachment on double click in a body-level plain text preview', async () => {
    const transport = createFakeTransport()
    const request = vi.spyOn(transport, 'request').mockResolvedValue({
      status: 200,
      headers: { 'content-type': 'text/markdown' },
      body: new TextEncoder().encode('# Notes\nPreview body'),
    } as never)
    const wrapper = mountDeck({ props: { attachments: [textAttachment], transport } })
    await flushPromises()
    request.mockClear()

    const preview = wrapper.get('.message-attachment-deck__preview')
    await preview.trigger('click')
    expect(wrapper.findComponent(CoreConfirmDialog).exists()).toBe(false)
    expect(request).not.toHaveBeenCalled()

    await preview.trigger('dblclick')
    await flushPromises()
    expect(wrapper.findComponent(CoreConfirmDialog).exists()).toBe(false)
    expect(request).toHaveBeenCalledWith({
      kind: 'http',
      method: 'GET',
      path: '/attachments/att-text/download',
    })
    const dialog = document.body.querySelector('[role="dialog"]')
    expect(dialog?.textContent).toContain('Preview body')
    expect(document.body.querySelector('.message-attachment-deck__text-overlay')).not.toBeNull()
  })

  it('keeps the attachment expanded when opening is cancelled', async () => {
    const transport = createFakeTransport()
    const request = vi.spyOn(transport, 'request')
    const wrapper = mountDeck({ props: { attachments: [{
      ...textAttachment,
      filename: 'report.pdf',
      label: 'report.pdf',
      mime_type: 'application/pdf',
      preview_type: 'external',
    }], transport } })
    await flushPromises()
    request.mockClear()

    const preview = wrapper.get('.message-attachment-deck__preview')
    await preview.trigger('dblclick')
    wrapper.getComponent(CoreConfirmDialog).vm.$emit('cancel')
    await wrapper.vm.$nextTick()

    expect(request).not.toHaveBeenCalled()
    expect(wrapper.findComponent(CoreConfirmDialog).exists()).toBe(false)
    expect(wrapper.get('.message-attachment-deck__card').classes()).not.toContain('message-attachment-deck__card--active')
  })

  it('reports an attachment open failure without collapsing the card', async () => {
    const transport = createFakeTransport()
    vi.spyOn(transport, 'request').mockImplementation(async request => {
      if (request.kind === 'http' && request.method === 'POST') {
        return { status: 500, headers: {}, body: new Uint8Array() } as never
      }
      return { status: 200, headers: {}, body: new Uint8Array() } as never
    })
    const wrapper = mountDeck({ props: { attachments: [{
      ...textAttachment,
      filename: 'report.pdf',
      label: 'report.pdf',
      mime_type: 'application/pdf',
      preview_type: 'external',
    }], transport } })
    await flushPromises()

    const preview = wrapper.get('.message-attachment-deck__preview')
    await preview.trigger('dblclick')
    wrapper.getComponent(CoreConfirmDialog).vm.$emit('confirm')
    await flushPromises()

    expect(wrapper.getComponent(CoreConfirmDialog).props('error')).toBe('无法打开：HTTP 500')
    expect(wrapper.getComponent(CoreConfirmDialog).props('open')).toBe(true)
    expect(wrapper.get('.message-attachment-deck__card').classes()).not.toContain('message-attachment-deck__card--active')
  })

  it('falls back to a project path when a historical artifact id is not registered', async () => {
    const transport = createFakeTransport()
    const request = vi.spyOn(transport, 'request')
    const artifact: ToolArtifact = {
      kind: 'file_change',
      uri: 'gui-run-01/p22.png',
      content: 'created',
    }
    const wrapper = mountDeck({ props: { artifacts: [artifact], projectId: 'project-1', transport } })
    await flushPromises()
    request.mockClear()

    const preview = wrapper.get('.message-attachment-deck__preview')
    await preview.trigger('dblclick')
    wrapper.getComponent(CoreConfirmDialog).vm.$emit('confirm')
    await flushPromises()

    expect(request).toHaveBeenCalledWith({
      method: 'artifact.open',
      params: {
        project_id: 'project-1',
        artifact_id: '',
        path: 'gui-run-01/p22.png',
      },
    })
  })

  it('hands hover directly to the next card and lightly scales adjacent cards', async () => {
    const attachments = Array.from({ length: 4 }, (_, index): CoreAttachment => ({
      ...textAttachment,
      id: `att-${index}`,
      filename: `notes-${index}.md`,
      label: `notes-${index}.md`,
    }))
    const wrapper = mountDeck({ props: { attachments } })
    const cards = wrapper.findAll('.message-attachment-deck__card')

    await cards[1].trigger('pointerenter')
    expect(cards[1].classes()).toContain('message-attachment-deck__card--active')
    expect(cards[0].classes()).toContain('message-attachment-deck__card--neighbor')
    expect(cards[2].classes()).toContain('message-attachment-deck__card--neighbor')
    expect(cards[2].classes()).toContain('message-attachment-deck__card--following')
    const nextStep = Number.parseFloat((cards[2].element as HTMLElement).style.getPropertyValue('--deck-item-step'))
    const tailStep = Number.parseFloat((cards[3].element as HTMLElement).style.getPropertyValue('--deck-item-step'))
    expect(nextStep).toBe(76)
    expect(tailStep).toBeLessThan(36)

    await cards[1].trigger('pointerleave')
    await cards[2].trigger('pointerenter')
    expect(cards[1].classes()).not.toContain('message-attachment-deck__card--active')
    expect(cards[2].classes()).toContain('message-attachment-deck__card--active')
  })

  it('loads text attachment excerpts from the preview endpoint', async () => {
    const transport = createFakeTransport({
      status: 200,
      headers: { 'content-type': 'application/json' },
      body: new TextEncoder().encode(JSON.stringify({ text: '# Notes\nPreview body' })),
    })
    const wrapper = mountDeck({ props: { attachments: [textAttachment], transport } })
    await flushPromises()
    expect(wrapper.text()).toContain('Notes · Preview body')
  })

  it('calculates a compact page from measured width and pages with side arrows', async () => {
    let observerCallback: ResizeObserverCallback | null = null
    class FakeResizeObserver {
      constructor(callback: ResizeObserverCallback) { observerCallback = callback }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    const artifacts: ToolArtifact[] = Array.from({ length: 9 }, (_, index) => ({
      kind: 'file_change',
      uri: `src/file-${index}.ts`,
      content: `+export const value${index} = ${index}`,
    }))
    const wrapper = mountDeck({ props: { artifacts } })
    const callback = observerCallback as ResizeObserverCallback | null
    callback?.([{ contentRect: { width: 356 } } as ResizeObserverEntry], {} as ResizeObserver)
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.message-attachment-deck__card')).toHaveLength(7)
    const track = wrapper.get('.message-attachment-deck__track')
    const trackElement = track.element as HTMLElement
    expect(track.classes()).toContain('message-attachment-deck__track--filled')
    const collapsedStep = Number.parseFloat(trackElement.style.getPropertyValue('--deck-step'))
    expect(collapsedStep).toBeGreaterThan(36)

    await wrapper.get('.message-attachment-deck__card').trigger('pointerenter')
    const expandedStep = Number.parseFloat(trackElement.style.getPropertyValue('--deck-step'))
    expect(expandedStep).toBeLessThan(collapsedStep)

    expect(wrapper.get('[aria-label="下一页附件"]').attributes('disabled')).toBeUndefined()
    await wrapper.get('[aria-label="下一页附件"]').trigger('click')
    await new Promise(resolve => setTimeout(resolve, 450))
    expect(wrapper.text()).toContain('file-7.ts')
  })
})
