import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'

const TABLE = `| 学院 | 专业 | 毕业人数 |
| --- | --- | ---: |
| 机电工程 | 车辆工程 | 9 |`

afterEach(() => {
  document.body.innerHTML = ''
})

describe('MarkdownRenderer tables', () => {
  it('keeps the header and body in one native table', () => {
    const wrapper = mount(MarkdownRenderer, { props: { content: TABLE } })
    const shell = wrapper.get('.markdown-table-shell')
    const table = shell.get('table')

    expect(table.element.parentElement?.classList.contains('markdown-table-viewport')).toBe(true)
    expect(table.find('thead').exists()).toBe(true)
    expect(table.find('tbody').exists()).toBe(true)
    expect(shell.findAll('table')).toHaveLength(1)
  })

  it('shows a top scrollbar only when the table overflows and syncs its position', async () => {
    const wrapper = mount(MarkdownRenderer, {
      attachTo: document.body,
      props: { content: TABLE },
    })
    const table = wrapper.get('table').element as HTMLTableElement
    const viewport = wrapper.get('.markdown-table-viewport').element as HTMLElement
    const scrollbar = wrapper.get('.markdown-table-scrollbar').element as HTMLElement

    Object.defineProperty(table, 'scrollWidth', { configurable: true, value: 900 })
    Object.defineProperty(viewport, 'clientWidth', { configurable: true, value: 400 })
    window.dispatchEvent(new Event('resize'))
    await nextTick()

    expect(scrollbar.hidden).toBe(false)
    expect(wrapper.get('.markdown-table-shell').classes()).toContain('markdown-table-shell--overflowing')
    expect(wrapper.get('.markdown-table-scroll-track').attributes('style')).toContain('width: 900px')

    scrollbar.scrollLeft = 120
    scrollbar.dispatchEvent(new Event('scroll'))
    expect(table.style.transform).toBe('translate3d(-120px, 0, 0)')
  })

  // user:"md自动渲染可能存在bug，会出现被胶囊形边线包裹的空行"
  // user:"全出来之后会消失，消失后就正常了"
  // 流式逐块喂表格时，每一帧都会重建尾部分段；表格壳是插在表格前面的兄弟
  // 节点，不随分段节点一起回收，会留下一叠空心圆角空壳，流完整体重渲染才
  // 消失。验收：流式全程壳的数量不超出现存的表格数，结束后恰好一个壳。
  it('does not leak empty table shells while a table streams in chunks', async () => {
    const rows = ['| 工具 | 分类 |', '| --- | --- |']
    for (let i = 1; i <= 6; i += 1) rows.push(`| tool_${i} | file_read |`)
    const wrapper = mount(MarkdownRenderer, { props: { content: '', streaming: true } })
    await wrapper.vm.$nextTick()

    let content = '分类如下：\n\n'
    for (const row of rows) {
      content += `${row}\n`
      await wrapper.setProps({ content })
      await wrapper.vm.$nextTick()
      expect(wrapper.findAll('.markdown-table-shell').length, `after chunk: ${row}`).toBeLessThanOrEqual(1)
    }

    // 表格段收口后再来一段普通文字：旧尾部连同壳一起回收，新段只有一个壳。
    content += '\n\n收尾说明。'
    await wrapper.setProps({ content })
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('.markdown-table-shell')).toHaveLength(1)

    // 流结束整体重渲染：恰好一个壳，壳里有完整表格。
    await wrapper.setProps({ streaming: false })
    await wrapper.vm.$nextTick()
    const shells = wrapper.findAll('.markdown-table-shell')
    expect(shells).toHaveLength(1)
    expect(shells[0].findAll('tbody tr')).toHaveLength(6)
    wrapper.unmount()
  })
})
