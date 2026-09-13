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
})
