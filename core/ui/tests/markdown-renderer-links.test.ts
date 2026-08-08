import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

describe('MarkdownRenderer link click interception', () => {
  let openUrl: ReturnType<typeof vi.fn>

  beforeEach(() => {
    openUrl = vi.fn().mockResolvedValue(true)
    ;(window as any).__LAMTOOLS_OPEN_URL__ = openUrl
  })

  afterEach(() => {
    delete (window as any).__LAMTOOLS_OPEN_URL__
  })

  it('routes an external http link to the OS browser and blocks in-app navigation', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '[LamTools](https://example.com)' },
    })
    await wrapper.vm.$nextTick()

    const link = wrapper.find('a')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('https://example.com')

    const spy = vi.spyOn(Event.prototype, 'preventDefault')

    await link.trigger('click')

    expect(openUrl).toHaveBeenCalledTimes(1)
    expect(openUrl).toHaveBeenCalledWith('https://example.com')
    expect(spy).toHaveBeenCalled()
  })

  it('does not intercept relative / non-http links', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '[jump](#section)' },
    })
    await wrapper.vm.$nextTick()

    const link = wrapper.find('a')
    expect(link.attributes('href')).toBe('#section')

    await link.trigger('click')

    expect(openUrl).not.toHaveBeenCalled()
  })

  it('renders external anchors with safe rel attributes', async () => {
    const wrapper = mount(MarkdownRenderer, {
      props: { content: '[link](https://example.com)' },
    })
    await wrapper.vm.$nextTick()

    const link = wrapper.find('a')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
    expect(link.attributes('rel')).toContain('noreferrer')
  })
})
