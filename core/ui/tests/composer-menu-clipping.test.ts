import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import Menu from '../src/components/CoreModelThinkingMenu.vue'
vi.mock('../src/motion/composerMenu.ts', () => ({ useComposerMenuMotion: () => ({ animatePrimaryCard: vi.fn(), animateSubmenuCard: vi.fn(), animateProviderOptions: vi.fn(), cancel: vi.fn() }) }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.restoreAllMocks() })
function fixture() {
  const wrapper = mount(Menu, { attachTo: document.body, props: { modelValue: 'model', modelOptions: [{ value: 'model', label: '模型' }], thinkingMode: 'high', thinkingModeOptions: [{ value: 'high', label: '高' }, { value: 'max', label: '极高' }] } })
  wrappers.push(wrapper)
  let y = 400
  vi.spyOn(wrapper.element, 'getBoundingClientRect').mockImplementation(() => ({ left: 1000, right: 1028, top: y, bottom: y + 28, width: 28, height: 28 } as DOMRect))
  return { wrapper, move: (top: number) => { y = top } }
}
// user:“把选择模型和思考强度那块样式也给我重构了”+(单一卡片、模型与纵向思考强度共存、外部关闭与视口翻转)。
it('keeps model and thinking in one card and closes only on outside press', async () => {
  const { wrapper } = fixture()
  await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
  const panel = wrapper.get('[popover="manual"]')
  expect(panel.attributes('style')).toContain('--composer-menu-left:')
  const card = panel.get('[data-model-thinking-card]')
  expect(card.findAll('[data-model-thinking-model-option]')).toHaveLength(1)
  expect(card.find('[data-core-thinking-slider]').exists()).toBe(true)
  expect(wrapper.find('[data-model-thinking-section]').exists()).toBe(false)
  expect(wrapper.find('[data-model-thinking-submenu]').exists()).toBe(false)

  await wrapper.get('[data-model-thinking-model-option="model"]').trigger('click')
  expect(wrapper.emitted('update:modelValue')).toEqual([['model']])
  expect(wrapper.find('[popover]').exists()).toBe(true)

  await wrapper.get('[data-model-thinking-level-option="max"]').trigger('click')
  expect(wrapper.emitted('update:thinkingMode')).toEqual([['max']])
  expect(wrapper.find('[popover]').exists()).toBe(true)

  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await flushPromises()
  expect(wrapper.find('[popover]').exists()).toBe(false)

  await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
  document.body.dispatchEvent(new Event('pointerdown', { bubbles: true }))
  await flushPromises()
  expect(wrapper.find('[popover]').exists()).toBe(false)
})
it('filters models by the group chosen in the top bar dropdown', async () => {
  const wrapper = mount(Menu, { attachTo: document.body, props: {
    modelValue: 'model-b',
    catalogView: 'group',
    modelOptions: [
      { value: 'model-a', label: 'Model A', group: 'Alpha', groupKey: 'group:alpha' },
      { value: 'model-b', label: 'Model B', group: 'Beta', groupKey: 'group:beta' },
      { value: 'model-b2', label: 'Model B2', group: 'Beta', groupKey: 'group:beta' },
    ],
    thinkingMode: 'high',
    thinkingModeOptions: [{ value: 'high', label: '高' }],
  } })
  wrappers.push(wrapper)
  await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')

  expect(wrapper.get('.core-model-thinking-menu__group-trigger').text()).toContain('Beta')
  expect(wrapper.findAll('[data-model-thinking-model-option]')).toHaveLength(2)

  await wrapper.get('.core-model-thinking-menu__group-trigger').trigger('click')
  expect(wrapper.findAll('[data-model-thinking-group-option]')).toHaveLength(4)
  expect(wrapper.find('[data-model-thinking-group-option="__all__"]').text()).toContain('全部')
  expect(wrapper.find('[data-model-thinking-group-option="__other__"]').text()).toContain('其他')
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await flushPromises()
  expect(wrapper.find('.core-model-thinking-menu__group-menu').exists()).toBe(false)
  expect(wrapper.find('[popover]').exists()).toBe(true)

  await wrapper.get('.core-model-thinking-menu__group-trigger').trigger('click')
  await wrapper.get('[data-model-thinking-group-option="group:alpha"]').trigger('click')
  await flushPromises()
  expect(wrapper.get('.core-model-thinking-menu__group-trigger').text()).toContain('Alpha')
  expect(wrapper.findAll('[data-model-thinking-model-option]')).toHaveLength(1)
  expect(wrapper.find('[data-model-thinking-model-option="model-a"]').exists()).toBe(true)
  expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  expect(wrapper.find('[popover]').exists()).toBe(true)
})

it('offers all models and ungrouped models in the group view', async () => {
  const wrapper = mount(Menu, { attachTo: document.body, props: {
    modelValue: 'alpha-1',
    catalogView: 'group',
    modelOptions: [
      { value: '', label: 'Current: Default', group: '', groupKey: 'default' },
      { value: 'alpha-1', label: 'Alpha 1', group: 'Alpha', groupKey: 'group:alpha' },
      { value: 'loose', label: 'Loose', group: '未分组', groupKey: 'group:__ungrouped__' },
    ],
    thinkingMode: 'high',
    thinkingModeOptions: [{ value: 'high', label: '高' }],
  } })
  wrappers.push(wrapper)
  await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')

  expect(wrapper.get('.core-model-thinking-menu__group-trigger').text()).toContain('Alpha')
  await wrapper.get('.core-model-thinking-menu__group-trigger').trigger('click')
  expect(wrapper.findAll('[data-model-thinking-group-option]').map((option) => option.attributes('data-model-thinking-group-option'))).toEqual(['__all__', 'group:alpha', '__other__'])

  await wrapper.get('[data-model-thinking-group-option="__all__"]').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[data-model-thinking-model-option]')).toHaveLength(3)
  expect(wrapper.get('.core-model-thinking-menu__group-trigger').text()).toContain('全部')

  await wrapper.get('.core-model-thinking-menu__group-trigger').trigger('click')
  await wrapper.get('[data-model-thinking-group-option="__other__"]').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[data-model-thinking-model-option]').map((option) => option.attributes('data-model-thinking-model-option'))).toEqual(['', 'loose'])
  expect(wrapper.get('.core-model-thinking-menu__group-trigger').text()).toContain('其他')
})

it('offers only the all option outside the group dimension', async () => {
  const wrapper = mount(Menu, { attachTo: document.body, props: {
    modelValue: 'p1-model',
    catalogView: 'provider',
    modelOptions: [
      { value: 'p1-model', label: 'P1 Model', group: 'Provider One', groupKey: 'provider:p1' },
      { value: 'p2-model', label: 'P2 Model', group: 'Provider Two', groupKey: 'provider:p2' },
    ],
    thinkingMode: 'high',
    thinkingModeOptions: [{ value: 'high', label: '高' }],
  } })
  wrappers.push(wrapper)
  await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
  await wrapper.get('.core-model-thinking-menu__group-trigger').trigger('click')
  expect(wrapper.findAll('[data-model-thinking-group-option]').map((option) => option.attributes('data-model-thinking-group-option'))).toEqual(['__all__', 'provider:p1', 'provider:p2'])
  await wrapper.get('[data-model-thinking-group-option="__all__"]').trigger('click')
  await flushPromises()
  expect(wrapper.findAll('[data-model-thinking-model-option]')).toHaveLength(2)
})

it('repositions below an upper pane and follows scroll and resize', async () => {
  const { wrapper, move } = fixture()
  await wrapper.get('.core-model-thinking-menu__trigger').trigger('click')
  expect(wrapper.get('[popover]').attributes('data-placement')).toBe('above')
  move(20); window.dispatchEvent(new Event('resize')); await flushPromises()
  expect(wrapper.get('[popover]').attributes('data-placement')).toBe('below')
  expect(wrapper.get('[popover]').attributes('style')).toContain('--composer-menu-top: 56px')
  move(450); window.dispatchEvent(new Event('scroll')); await flushPromises()
  expect(wrapper.get('[popover]').attributes('data-placement')).toBe('above')
})
