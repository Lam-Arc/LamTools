import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import DocumentEditor from '../src/components/DocumentEditor.vue'

/**
 * 文档编辑器：阅读与编辑是同一份文档的两种状态。
 *
 * 这里验三件会直接影响写东西手感的事——工具条作用在选中文字上、行首标记整行
 * 进出、回车续列表 / Tab 缩进；预览栏由宿主塞插槽，这里只确认它拿到了当前源文。
 */

function mountEditor(modelValue = '') {
  const wrapper = mount(DocumentEditor, {
    props: { idPrefix: 'library-editor', title: '提纲', modelValue },
    slots: { preview: '<p class="preview-body">{{ content }}</p>' },
  })
  const input = wrapper.get('textarea').element as HTMLTextAreaElement
  return { wrapper, input }
}

function select(input: HTMLTextAreaElement, start: number, end = start): void {
  input.setSelectionRange(start, end)
  input.dispatchEvent(new Event('keyup'))
}

describe('DocumentEditor', () => {
  it('wraps the selected text with the toolbar action', async () => {
    const { wrapper, input } = mountEditor('重点')
    select(input, 0, 2)
    await wrapper.vm.$nextTick()
    const bold = wrapper.get('[data-doc-editor-action="bold"]')
    expect((bold.element as HTMLButtonElement).disabled, '选了字之后格式键该可用').toBe(false)
    await bold.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['**重点**'])
    wrapper.unmount()
  })

  it('toggles a line marker on and off for the whole line', async () => {
    const { wrapper, input } = mountEditor('第一条')
    select(input, 2)
    await wrapper.get('[data-doc-editor-action="list"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['- 第一条'])

    const second = mountEditor('- 第一条')
    select(second.input, 2)
    await second.wrapper.get('[data-doc-editor-action="list"]').trigger('click')
    expect(second.wrapper.emitted('update:modelValue')?.[0]).toEqual(['第一条'])
    wrapper.unmount()
    second.wrapper.unmount()
  })

  it('continues a list on Enter and ends it on an empty item', async () => {
    const { wrapper, input } = mountEditor('- 第一条')
    input.setSelectionRange(5, 5)
    await wrapper.get('textarea').trigger('keydown', { key: 'Enter' })

    const empty = mountEditor('- ')
    empty.input.setSelectionRange(2, 2)
    await empty.wrapper.get('textarea').trigger('keydown', { key: 'Enter' })
    expect(empty.wrapper.emitted('update:modelValue')?.[0]).toEqual([''])
    wrapper.unmount()
    empty.wrapper.unmount()
  })

  it('indents with Tab and shows the rendered preview only after toggling it on', async () => {
    const { wrapper, input } = mountEditor('正文')
    input.setSelectionRange(2, 2)
    await wrapper.get('textarea').trigger('keydown', { key: 'Tab' })
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual(['正文  '])

    // 单栏二态：默认写源文，切到预览才渲染，切回编辑源文原样还在。
    expect(wrapper.find('.preview-body').exists()).toBe(false)
    await wrapper.get('[data-library-editor-preview-toggle]').trigger('click')
    expect(wrapper.get('.preview-body').text()).toBe('正文')
    expect(wrapper.find('textarea').exists()).toBe(false)

    await wrapper.get('[data-library-editor-preview-toggle]').trigger('click')
    expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('正文')
    expect(wrapper.find('.preview-body').exists()).toBe(false)
    wrapper.unmount()
  })
})
