import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'
import { setUiLanguage } from '../src/i18n'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); setUiLanguage('zh-CN'); delete (navigator as { clipboard?: unknown }).clipboard })

// user:“辅助说明块呢？总的来说就是样式块”+(辅助说明、折叠详情与可编辑成稿共用消息渲染链)。
describe('message style blocks', () => {
  it.each(['note', 'info', 'tip', 'warning', 'danger', 'success'])('renders %s with a label and nested Markdown', async kind => {
    const wrapper = mount(MarkdownRenderer, { props: { content: `:::${kind} 标题\n**内容**\n\n- 项目\n:::` } })
    await flushPromises()
    const block = wrapper.find(`[data-style-block="${kind}"]`)
    expect(block.exists()).toBe(true)
    expect(block.find('strong').text()).toBe('标题')
    expect(block.find('li').text()).toBe('项目')
    wrapper.unmount()
  })

  it('supports GitHub alerts and native keyboard-accessible collapsible details', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: '> [!NOTE]\n> 辅助说明\n\n:::details 展开依据\n依据 **正文**\n:::' } })
    await flushPromises()
    expect(wrapper.find('[data-style-block="note"]').text()).toContain('辅助说明')
    expect(wrapper.find('details summary').text()).toBe('展开依据')
    expect(wrapper.find('details').attributes('open')).toBeUndefined()
    wrapper.unmount()
  })

  it('edits and copies the latest writing draft without submitting anything', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
    const wrapper = mount(MarkdownRenderer, { props: { interactive: true, content: ':::writing{variant="email" id="12345" subject="周报" recipient="test@example.com"}\n原稿 **正文**\n:::' } })
    await vi.waitFor(() => expect(wrapper.find('.writing-block').exists(), wrapper.html()).toBe(true))
    expect(wrapper.find('.writing-block').text()).toContain('周报')
    await wrapper.find('[data-writing-edit]').trigger('click')
    await wrapper.find('textarea').setValue('修改后的正文')
    await wrapper.find('[data-writing-copy]').trigger('click')
    expect(writeText).toHaveBeenCalledWith('修改后的正文')
    expect(wrapper.find('form').exists()).toBe(false)
    wrapper.unmount()
    vi.unstubAllGlobals()
  })

  it('does not interpret style markers inside fenced code or execute malicious titles', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: '```text\n:::warning 提示\n代码\n:::\n```\n\n:::note <img src=x onerror=alert(1)>\n<script>alert(1)</script>\n:::' } })
    await flushPromises()
    expect(wrapper.findAll('[data-style-block]')).toHaveLength(1)
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('[onerror]').exists()).toBe(false)
    expect(wrapper.find('pre').text()).toContain(':::warning')
    wrapper.unmount()
  })

  it('keeps unclosed blocks readable and does not mount writing tools while streaming', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { interactive: true, streaming: true, content: ':::writing{variant="document"}\n尚未完成' } })
    await flushPromises()
    expect(wrapper.text()).toContain('尚未完成')
    expect(wrapper.find('[data-writing-edit]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('localizes default labels and keeps writing paths intact', async () => {
    setUiLanguage('en')
    const wrapper = mount(MarkdownRenderer, { props: { interactive: true, content: ':::note\nBody\n:::\n\n:::writing{variant="document"}\nOpen E:/project/notes.md\n:::' } })
    await vi.waitFor(() => expect(wrapper.find('.writing-block').exists()).toBe(true))
    expect(wrapper.find('.message-style-title').text()).toBe('Note')
    await wrapper.find('[data-writing-edit]').trigger('click')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('Open E:/project/notes.md')
    wrapper.unmount()
  })

  it('preserves draft math as editable source rather than rendered formula text', async () => {
    const body = '公式 $x + y$，显示公式：\n\n$$z^2$$'
    const wrapper = mount(MarkdownRenderer, { props: { interactive: true, content: `:::writing{variant="document"}\n${body}\n:::` } })
    await vi.waitFor(() => expect(wrapper.find('.writing-block').exists()).toBe(true))
    await wrapper.find('[data-writing-edit]').trigger('click')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe(body)
    wrapper.unmount()
  })

  it('keeps formulas in writing titles as plain text attributes', async () => {
    const wrapper = mount(MarkdownRenderer, { props: { interactive: true, content: ':::writing{title="解释 $x+y$"}\n正文\n:::' } })
    await vi.waitFor(() => expect(wrapper.find('.writing-block').exists()).toBe(true))
    expect(wrapper.find('.writing-block header strong').text()).toBe('解释 $x+y$')
    wrapper.unmount()
  })
})
