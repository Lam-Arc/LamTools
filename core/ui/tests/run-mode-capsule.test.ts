import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import CoreRunModeCapsule from '../src/components/CoreRunModeCapsule.vue'
import { RUN_MODE_TIER_COMPACT_MIN, RUN_MODE_TIER_FULL_MIN, runModeTier } from '../src/composer/runModeTier'

const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); document.body.innerHTML = ''; vi.unstubAllGlobals(); vi.restoreAllMocks() })

async function mountWithWidth(width: number, props: Record<string, unknown> = {}) {
  const wrapper = mount(CoreRunModeCapsule, { props: { modelValue: 'work', containerWidth: width, ...props }, attachTo: document.body })
  wrappers.push(wrapper)
  await wrapper.vm.$nextTick()
  return wrapper
}

const tierOf = (wrapper: ReturnType<typeof mount>): string | undefined =>
  wrapper.get('[data-run-mode-capsule]').attributes('data-run-mode-tier')

// user:“这个空间怎么看也不像会互相挤”“为什么有那个小竖杠”+
// (档位按“胶囊自己需要多宽”判定：一档 274px（原来的 132px 等宽两格）放得下就保持原样，
//  只有真的放不下时才收紧成二档，再窄才收成一个按钮。)
describe('胶囊三档：可用宽度决定结构', () => {
  it('纯函数按“需要的宽度”分档（274 / 122 为界）', async () => {
    expect(RUN_MODE_TIER_FULL_MIN).toBe(274)
    expect(RUN_MODE_TIER_COMPACT_MIN).toBe(122)
    // 空间够：保持改造前的原样（哪怕只剩 360px，两格等宽 132px 也放得下）
    expect(runModeTier(560)).toBe('full')
    expect(runModeTier(420)).toBe('full')
    expect(runModeTier(360)).toBe('full')
    expect(runModeTier(RUN_MODE_TIER_FULL_MIN)).toBe('full')
    // 放不下原样 → 两格收紧
    expect(runModeTier(RUN_MODE_TIER_FULL_MIN - 1)).toBe('compact')
    expect(runModeTier(200)).toBe('compact')
    expect(runModeTier(RUN_MODE_TIER_COMPACT_MIN)).toBe('compact')
    // 连收紧的两格都放不下 → 单按钮
    expect(runModeTier(RUN_MODE_TIER_COMPACT_MIN - 1)).toBe('icon')
    expect(runModeTier(100)).toBe('icon')
    // 还没量到布局：先按完整显示，不要一上来就闪成按钮
    expect(runModeTier(0)).toBe('full')
  })

  it('空间够（560 / 420 / 360）：两格并排、完整文案、当前项有 aria-checked 与 is-active', async () => {
    for (const width of [560, 420, 360]) {
      const wrapper = await mountWithWidth(width)
      const root = wrapper.get('[data-run-mode-capsule]')
      expect(root.attributes('data-run-mode-tier')).toBe('full')
      expect(root.classes()).toContain('core-run-mode--full')
      const options = wrapper.findAll('[data-run-mode-option]')
      expect(options).toHaveLength(2)
      expect(wrapper.find('[data-run-mode-trigger]').exists()).toBe(false)
      const active = options.find(option => option.attributes('aria-checked') === 'true')!
      expect(active.attributes('data-run-mode-option')).toBe('work')
      expect(active.classes()).toContain('is-active')
      expect(wrapper.findAll('.core-run-mode__label').length).toBe(2)
      wrapper.unmount()
    }
  })

  it('200：放不下原样，两格收紧但仍是两格', async () => {
    const wrapper = await mountWithWidth(200)
    expect(tierOf(wrapper)).toBe('compact')
    expect(wrapper.get('[data-run-mode-capsule]').classes()).toContain('core-run-mode--compact')
    expect(wrapper.findAll('[data-run-mode-option]')).toHaveLength(2)
    expect(wrapper.find('[data-run-mode-trigger]').exists()).toBe(false)
  })

  it('100：收成图标 + 当前项，点开菜单才能切，菜单项仍能改模式', async () => {
    const wrapper = await mountWithWidth(100)
    expect(tierOf(wrapper)).toBe('icon')
    expect(wrapper.find('.core-run-mode__bar').exists()).toBe(false)
    const trigger = wrapper.get('[data-run-mode-trigger]')
    expect(trigger.attributes('aria-label')).toBeTruthy()
    expect(trigger.attributes('aria-haspopup')).toBe('listbox')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(trigger.text().length).toBeGreaterThan(0)
    expect(wrapper.find('[data-run-mode-menu]').exists()).toBe(false)

    await trigger.trigger('click')
    expect(wrapper.get('[data-run-mode-trigger]').attributes('aria-expanded')).toBe('true')
    const menu = wrapper.get('[data-run-mode-menu]')
    expect(menu.attributes('role')).toBe('listbox')
    const items = menu.findAll('[data-run-mode-option]')
    expect(items).toHaveLength(2)
    await items.find(item => item.attributes('data-run-mode-option') === 'chat')!.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['chat'])
    expect(wrapper.find('[data-run-mode-menu]').exists()).toBe(false)
  })

  it('窄档 + 锁定态：只留静态当前项，不给可点的展开按钮', async () => {
    const wrapper = await mountWithWidth(100, { selectable: false })
    expect(wrapper.find('[data-run-mode-locked]').exists()).toBe(true)
    expect(wrapper.find('[data-run-mode-trigger]').exists()).toBe(false)
  })

  it('历史存档里的 auto：按工作显示，并且那一格确实点亮（不再“两格都不亮”）', async () => {
    const wrapper = await mountWithWidth(560, { modelValue: 'auto' })
    const active = wrapper.findAll('[data-run-mode-option]').filter(option => option.attributes('aria-checked') === 'true')
    expect(active).toHaveLength(1)
    expect(active[0].attributes('data-run-mode-option')).toBe('work')
  })
})

// user:“焦点与可达性不能退化：Tab 能进、Enter/Space 能切、窄档图标按钮要有 aria-label”+
// (两格并排用 radiogroup+radio 的互斥语义；窄档是单个展开按钮，用 aria-haspopup + aria-expanded)。
describe('可访问性', () => {
  it('两格是原生 button（Tab 可达、Enter/Space 天然激活）+ radio 语义', async () => {
    const wrapper = await mountWithWidth(560)
    const group = wrapper.get('[role="radiogroup"]')
    expect(group.attributes('aria-label')).toBeTruthy()
    for (const option of wrapper.findAll('[data-run-mode-option]')) {
      expect(option.element.tagName).toBe('BUTTON')
      expect(option.attributes('type')).toBe('button')
      expect(option.attributes('role')).toBe('radio')
      expect(['true', 'false']).toContain(option.attributes('aria-checked'))
    }
  })
})

// user:“为什么要改样式”“为什么有那个小竖杠”+
// (空间够时必须和改造前一致：两格等宽 132px、字号 15px、选中只靠底色块，没有额外竖条)。
describe('一档 = 改造前的原样（回归锁）', () => {
  const source = readFileSync(resolve(__dirname, '../src/components/CoreRunModeCapsule.vue'), 'utf8')

  it('两格恢复 132px 等宽 + 15px 字号（不再按内容缩到最小）', () => {
    expect(source).toMatch(/\.core-run-mode__pill \{[^}]*flex: 0 0 132px/)
    expect(source).toMatch(/\.core-run-mode__pill \{[^}]*font-size: 15px/)
  })

  it('选中态只有底色块，没有任何竖条/指示条', () => {
    expect(source).not.toContain('.core-run-mode__pill.is-active::before')
    expect(source).not.toContain('.core-run-mode__trigger::before')
    expect(source).toMatch(/\.core-run-mode__pill\.is-active \{[^}]*background: color-mix\(in srgb, var\(--text\) 16%/)
  })

  it('根节点不再有按档位写的硬下限（9em / 7.5em / 4.5em 全部删除）', () => {
    expect(source).not.toMatch(/\.core-run-mode \{[^}]*min-width:/)
    expect(source).not.toMatch(/\.core-run-mode--compact \{\s*min-width/)
    expect(source).not.toMatch(/\.core-run-mode--icon \{\s*min-width/)
  })

  it('二档才允许收缩：每格 4em 起、字号收紧、文字可省略', () => {
    expect(source).toMatch(/\.core-run-mode--compact \.core-run-mode__pill \{[^}]*min-width: 4em/)
    expect(source).toMatch(/\.core-run-mode--compact \.core-run-mode__pill \{[^}]*flex: 1 1 0/)
    expect(source).toContain('text-overflow: ellipsis')
  })

  it('外层仍有 max-width: 100%，不会撑破宿主', () => {
    expect(source).toMatch(/\.core-run-mode \{[^}]*max-width: 100%/)
  })
})

// user:“这个空间怎么看也不像会互相挤”+
// (胶囊的真实宿主是空会话引导块 `.empty-session-hero`，不是输入栏那一行；
//  量宿主宽度而不是量自己，并且 ResizeObserver 也要观察宿主)。
async function mountIn(className: string, width: number, props: Record<string, unknown> = {}) {
  const host = document.createElement('div')
  host.className = className
  Object.defineProperty(host, 'clientWidth', { configurable: true, value: width })
  document.body.appendChild(host)
  const wrapper = mount(CoreRunModeCapsule, { props: { modelValue: 'work', ...props }, attachTo: host })
  wrappers.push(wrapper)
  await wrapper.vm.$nextTick()
  return { wrapper, host }
}

describe('量的是真正装它的那块（不是胶囊自己）', () => {
  it('空会话引导块 560 / 250 / 100 → full / compact / icon', async () => {
    const wide = await mountIn('empty-session-hero', 560)
    expect(tierOf(wide.wrapper)).toBe('full')
    // 274 是“原样两格”需要的宽度：300 还放得下，250 放不下才收紧
    const mid = await mountIn('empty-session-hero', 250)
    expect(tierOf(mid.wrapper)).toBe('compact')
    const narrow = await mountIn('empty-session-hero', 100)
    expect(tierOf(narrow.wrapper)).toBe('icon')
  })

  it('胶囊挪进输入栏时，仍能按 composer 容器判定（向后兼容）', async () => {
    const { wrapper } = await mountIn('composer-bottom', 200)
    expect(tierOf(wrapper)).toBe('compact')
  })

  it('ResizeObserver 观察的是宿主，而不是胶囊自身', async () => {
    const observed: Element[] = []
    class FakeResizeObserver {
      constructor(_callback: unknown) {}
      observe(element: Element) { observed.push(element) }
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    const { wrapper, host } = await mountIn('empty-session-hero', 560)
    expect(observed.length).toBeGreaterThan(0)
    expect(observed[0]).toBe(host)
    expect(observed[0]).not.toBe(wrapper.element)
    expect(observed[0].className).toContain('empty-session-hero')
  })

  it('宿主变窄再变宽能回到一档：档位不会被“自己现在很窄”粘住', async () => {
    const { wrapper, host } = await mountIn('empty-session-hero', 560)
    expect(tierOf(wrapper)).toBe('full')

    // 变窄 → 单按钮
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 100 })
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(tierOf(wrapper)).toBe('icon')

    // 再变宽 → 必须回到一档（上一版会卡在窄档出不来）
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 560 })
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(tierOf(wrapper)).toBe('full')
    expect(wrapper.findAll('[data-run-mode-option]')).toHaveLength(2)
  })

  it('宿主量不到宽度（0）时保持当前档位，不凭 0 猜', async () => {
    const { wrapper, host } = await mountIn('empty-session-hero', 250)
    expect(tierOf(wrapper)).toBe('compact')
    Object.defineProperty(host, 'clientWidth', { configurable: true, value: 0 })
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    expect(tierOf(wrapper)).toBe('compact')
  })
})
