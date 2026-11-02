import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { gsap } from 'gsap'
import Menu from '../src/components/CoreModelThinkingMenu.vue'
import Slider from '../src/components/ThinkingIntensitySlider.vue'

/**
 * 思考等级悬浮条与开卡飞入编排。
 *
 * user:“悬浮条是你要实现的”“我不建议你单独做一个悬浮条，而是直接用卡片右侧的那个思考等级把它给放倒”
 * +(悬浮条就是卡片里那条思考强度滑条本身：悬浮触发按钮的思考等级时卡片隐藏、滑条放倒在按钮上方，可直接调级；
 *   点击后滑条先逆时针转正、再向右滑回卡内原位，滑动过程中把卡片划出来)。
 *
 * jsdom 没有排版引擎，getBoundingClientRect 全是 0，所以用原型级 mock 摆出真实几何：
 * 触发按钮在窗口右下、卡片在上方居中、竖向滑轨在卡片右列。
 */

const TRIGGER = { left: 820, top: 600, width: 200, height: 28 }
const SPAN = { left: 930, top: 600, width: 70, height: 28 }
const CARD = { left: 640, top: 300, width: 384, height: 312 }
// 卡片右列里滑轨的排版位置（未加悬浮位移时的原始布局）。
const RAIL_LAYOUT = { left: 986, top: 346, width: 30, height: 258 }
// 放倒后的滑轨（宽高互换），供横向取值单测使用。
const RAIL_LAID = { left: 860, top: 560, width: 260, height: 30 }

const VIEW_WIDTH = 1024

function rect({ left, top, width, height }: { left: number; top: number; width: number; height: number }): DOMRect {
  return { left, top, right: left + width, bottom: top + height, width, height, x: left, y: top, toJSON: () => undefined } as DOMRect
}

function spyOnLayout(): void {
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function mock(this: Element) {
    const el = this as Element
    if (el.classList.contains('sunday-thinking-slider__rail')) return rect(RAIL_LAYOUT)
    // 轨道胶囊比滑轨窄 2px×2，端头圆心在其底端上方 13px（半径 13）。
    if (el.classList.contains('sunday-thinking-slider__track')) {
      return rect({ left: RAIL_LAYOUT.left + 2, top: RAIL_LAYOUT.top, width: 26, height: RAIL_LAYOUT.height })
    }
    if (el.classList.contains('core-model-thinking-menu__thinking')) return rect(SPAN)
    if (el.classList.contains('core-model-thinking-menu__trigger')) return rect(TRIGGER)
    if (el.hasAttribute('data-core-model-thinking-menu')) return rect(TRIGGER)
    if (el.hasAttribute('data-model-thinking-card')) return rect(CARD)
    if (el.classList.contains('core-model-thinking-menu__panel')) return rect(CARD)
    return rect({ left: 0, top: 0, width: 0, height: 0 })
  })
}

function mediaQuery(matches: boolean): MediaQueryList {
  return {
    matches,
    media: '(prefers-reduced-motion: reduce)',
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  } as unknown as MediaQueryList
}

const wrappers: Array<VueWrapper<InstanceType<typeof Menu> | InstanceType<typeof Slider>>> = []

afterEach(() => {
  wrappers.splice(0).forEach((wrapper) => wrapper.unmount())
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function mountMenu(reducedMotion = false) {
  if (reducedMotion) vi.stubGlobal('matchMedia', (query: string) => mediaQuery(query.includes('reduce')))
  const wrapper = mount(Menu, {
    attachTo: document.body,
    props: {
      modelValue: 'model',
      modelOptions: [{ value: 'model', label: '模型' }],
      thinkingMode: 'medium',
      thinkingModeOptions: [
        { value: 'off', label: '关闭' },
        { value: 'medium', label: '中' },
        { value: 'max', label: '极高' },
      ],
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('思考等级悬浮条（卡片滑条放倒）', () => {
  it('悬浮思考等级时，卡片隐藏、卡片滑条放倒在触发按钮上方', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(false)

    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()

    const panel = wrapper.get('.core-model-thinking-menu__panel')
    expect(panel.classes()).toContain('is-hover-preview')
    // user:“悬浮状态下调小一点”+(悬浮态滑条挂 is-laid 收短，落位后还原)。
    const wrapEl = wrapper.get('.core-model-thinking-menu__slider-wrap')
    expect(wrapEl.classes()).toContain('is-laid')
    // 卡片本体已挂载（滑条就住在里面），但处于悬浮预览态，卡片不可见。
    expect(wrapper.find('[data-model-thinking-card]').exists()).toBe(true)
    expect(wrapper.get('.core-model-thinking-menu__trigger').attributes('aria-expanded')).toBe('false')

    const wrap = wrapper.get('.core-model-thinking-menu__slider-wrap').element
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(90)
    const dx = Number(gsap.getProperty(wrap, 'x'))
    const dy = Number(gsap.getProperty(wrap, 'y'))
    // user:“旋转的圆心应该是绕着那个条最左侧，也就是左边或者竖着下边的那个圆的圆心，而不是绝对的圆心”
    // +(位移以端头圆心为基准摆放：条的可见中心 = 端头圆心位置 + 半长偏移；
    //   轨道胶囊端头半径 13px，端头圆心在滑轨底端上方 13px 处)。
    const CAP_RADIUS = 13
    const barCenterX = RAIL_LAYOUT.left + RAIL_LAYOUT.width / 2 + dx + RAIL_LAYOUT.height / 2 - CAP_RADIUS
    const barCenterY = RAIL_LAYOUT.top + RAIL_LAYOUT.height - CAP_RADIUS + dy
    // 放倒的条悬浮在触发按钮上方，且整体留在窗口内。
    expect(barCenterY).toBeLessThan(TRIGGER.top)
    expect(barCenterY).toBeGreaterThan(TRIGGER.top - 80)
    expect(barCenterX).toBeGreaterThan(0)
    expect(barCenterX).toBeLessThan(VIEW_WIDTH)
  })

  it('悬浮模型名时不出现悬浮条', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__model').trigger('pointerenter')
    await flushPromises()
    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(false)
  })

  it('放倒的悬浮条可以直接调整思考等级', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()
    // 放倒后滑条最高档在右端，点刻度即调级（事件照常从卡片滑条发出）。
    await wrapper.get('[data-model-thinking-level-option="max"]').trigger('click')
    expect(wrapper.emitted('update:thinkingMode')).toEqual([['max']])
  })

  it('放倒状态下指针沿横向取值：右端最高、左端关闭', async () => {
    const wrapper = mount(Slider, {
      attachTo: document.body,
      props: {
        // 初始值取中间档，保证右端/左端取值都会真实发出变更事件。
        modelValue: 'light',
        options: [
          { value: 'off', label: '关闭' },
          { value: 'light', label: '轻' },
          { value: 'medium', label: '中' },
          { value: 'max', label: '极高' },
        ],
        label: '思考强度',
      },
    })
    wrappers.push(wrapper)
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function mock(this: Element) {
      if (this.classList.contains('sunday-thinking-slider__rail')) return rect(RAIL_LAID)
      return rect({ left: 0, top: 0, width: 0, height: 0 })
    })
    const body = wrapper.get('.sunday-thinking-slider__body').element
    // jsdom 的 PointerEvent clientX 只读，改用 MouseEvent 构造器携带坐标派发。
    body.dispatchEvent(new MouseEvent('pointerdown', { clientX: RAIL_LAID.left + RAIL_LAID.width - 16, bubbles: true }))
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['max'])
    body.dispatchEvent(new MouseEvent('pointermove', { clientX: RAIL_LAID.left + RAIL_LAID.width / 2, bubbles: true }))
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['medium'])
    body.dispatchEvent(new MouseEvent('pointermove', { clientX: RAIL_LAID.left + 16, bubbles: true }))
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['off'])
    body.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }))
  })
})

describe('开卡飞入编排', () => {
  it('点击后滑条绕端头圆心逆时针转正，同时平移进卡内槽位，卡片在运动中同步划出', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()
    const wrap = wrapper.get('.core-model-thinking-menu__slider-wrap').element
    const card = wrapper.get('[data-model-thinking-card]').element as HTMLElement
    const startX = Number(gsap.getProperty(wrap, 'x'))

    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    await flushPromises()

    expect(wrapper.get('.core-model-thinking-menu__trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('.core-model-thinking-menu__panel').classes()).not.toContain('is-hover-preview')
    // 落位后悬浮收短状态必须解除。
    expect(wrapper.get('.core-model-thinking-menu__slider-wrap').classes()).not.toContain('is-laid')

    // 中段：旋转角度在 0~90 之间，横向位置也已同步开始移动，卡片同步被划出——
    // 三点同时成立说明转正与平移是并行的一段，而不是先后两段。
    await sleep(90)
    const rotationMid = Number(gsap.getProperty(wrap, 'rotation'))
    expect(rotationMid).toBeGreaterThan(0)
    expect(rotationMid).toBeLessThan(90)
    const xMid = Number(gsap.getProperty(wrap, 'x'))
    expect(xMid).toBeGreaterThan(startX + 1)
    expect(xMid).toBeLessThan(-1)
    expect(Number(card.style.getPropertyValue('--thinking-card-reveal') || '0')).toBeGreaterThan(0)

    // 落位：滑条平移到卡内原位（transform 清空），卡片完全展开且无残留样式。
    await vi.waitFor(() => {
      expect(Number(gsap.getProperty(wrap, 'x'))).toBe(0)
      expect(card.style.getPropertyValue('--thinking-card-reveal')).toBe('')
    }, { timeout: 2500, interval: 40 })
    expect(Number(gsap.getProperty(wrap, 'y'))).toBe(0)
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(0)
    expect(Number(gsap.getProperty(wrap, 'autoAlpha'))).toBe(1)
    const modelColumn = card.querySelector<HTMLElement>('.core-model-thinking-menu__model-column')
    expect(modelColumn?.style.clipPath).toBe('')
  })

  it('max 粒子特效延后到滑条落位固定后才出现', async () => {
    const wrapper = mount(Menu, {
      attachTo: document.body,
      props: {
        modelValue: 'model',
        modelOptions: [{ value: 'model', label: '模型' }],
        thinkingMode: 'max',
        thinkingModeOptions: [
          { value: 'off', label: '关闭' },
          { value: 'max', label: '极高' },
        ],
      },
    })
    wrappers.push(wrapper)
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()
    // 悬浮条静止时粒子正常存在。
    expect(wrapper.find('.sunday-thinking-slider__max-dots').exists()).toBe(true)

    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    await flushPromises()
    // 飞入过程中粒子隐藏。
    expect(wrapper.find('.sunday-thinking-slider__max-dots').exists()).toBe(false)
    await sleep(120)
    expect(wrapper.find('.sunday-thinking-slider__max-dots').exists()).toBe(false)

    // 落位固定后粒子重新出现。
    await vi.waitFor(() => {
      expect(wrapper.find('.sunday-thinking-slider__max-dots').exists()).toBe(true)
    }, { timeout: 2500, interval: 40 })
    const wrap = wrapper.get('.core-model-thinking-menu__slider-wrap').element
    expect(Number(gsap.getProperty(wrap, 'x'))).toBe(0)
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(0)
  })

  it('指针离开思考等级后悬浮条收起，再次悬浮可重新出现', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    const span = wrapper.get('.core-model-thinking-menu__thinking')
    await span.trigger('pointerenter')
    await flushPromises()
    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(true)

    await span.trigger('pointerleave')
    await sleep(600)
    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(false)

    await span.trigger('pointerenter')
    await flushPromises()
    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(true)
    expect(Number(gsap.getProperty(wrapper.get('.core-model-thinking-menu__slider-wrap').element, 'rotation'))).toBe(90)
  })

  it('从滑条上划过时悬浮条保持不收', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()
    const wrapEl = wrapper.get('.core-model-thinking-menu__slider-wrap')

    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerleave')
    await sleep(60)
    await wrapEl.trigger('pointerenter')
    await sleep(500)

    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(true)
    const wrap = wrapEl.element
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(90)
  })

  it('减少动态效果时不做飞入，悬浮姿态即刻归位', async () => {
    const wrapper = mountMenu(true)
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()
    const wrap = wrapper.get('.core-model-thinking-menu__slider-wrap').element
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(90)

    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    await flushPromises()

    expect(wrapper.get('.core-model-thinking-menu__trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.core-model-thinking-menu__panel.is-hover-preview').exists()).toBe(false)
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(0)
    expect(Number(gsap.getProperty(wrap, 'x'))).toBe(0)
    const card = wrapper.get('[data-model-thinking-card]').element as HTMLElement
    expect(card.style.getPropertyValue('--thinking-card-reveal')).toBe('')
  })

  it('当前模型没有可调思考等级时不出现悬浮条', async () => {
    const wrapper = mount(Menu, {
      attachTo: document.body,
      props: {
        modelValue: 'model',
        modelOptions: [{ value: 'model', label: '模型' }],
        thinkingMode: 'off',
        thinkingModeOptions: [],
      },
    })
    wrappers.push(wrapper)
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__thinking').trigger('pointerenter')
    await flushPromises()
    expect(wrapper.find('.core-model-thinking-menu__panel').exists()).toBe(false)
  })

  it('不悬浮时开卡行为保持不变（回归）', async () => {
    const wrapper = mountMenu()
    spyOnLayout()
    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    await flushPromises()
    expect(wrapper.get('.core-model-thinking-menu__trigger').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.core-model-thinking-menu__panel.is-hover-preview').exists()).toBe(false)
    const wrap = wrapper.get('.core-model-thinking-menu__slider-wrap').element
    expect(Number(gsap.getProperty(wrap, 'rotation'))).toBe(0)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await sleep(500)
    expect(wrapper.find('[popover]').exists()).toBe(false)

    await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
    await flushPromises()
    expect(wrapper.find('[popover]').exists()).toBe(true)
  })
})
