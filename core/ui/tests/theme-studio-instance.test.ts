import { beforeEach, describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import ThemeStudio from '../src/components/ThemeStudio.vue'
import { createStudioStore } from '../src/themeStudio/store.ts'
import {
  compileStudioDocument,
  createEmptyStudioDocument,
  instanceSelectorFor,
  migrateStudioDocument,
  templateSelectorFor,
  validateStudioDocument,
  type StudioDocument,
} from '../src/themeStudio/index.ts'
import { STUDIO_PREVIEW_STYLE_ID } from '../src/themeStudio/runtime.ts'

/**
 * user:“写好清单，逐项打勾”“模板之上允许单个实例覆盖”+
 * (模板改一处影响全部；实例只改这一条消息或这一个会话。
 *  实例规则排在模板之后靠书写顺序取胜，校验不许指向没登记的模板，
 *  编辑器点中某一条时只能写这一条，不许悄悄改到模板上。)
 */
const empty = (): StudioDocument => createEmptyStudioDocument('studio', new Date('2026-10-29T00:00:00.000Z'))
const previewStyle = () => document.querySelector<HTMLStyleElement>(`style[data-ui-theme-studio="${STUDIO_PREVIEW_STYLE_ID}"]`)

function stageNode(templateId: string, instanceKey: string): HTMLElement {
  const node = document.createElement('div')
  node.dataset.uiTemplate = templateId
  node.dataset.uiInstance = instanceKey
  node.getBoundingClientRect = () => ({
    left: 20, top: 30, width: 200, height: 60, right: 220, bottom: 90, x: 20, y: 30, toJSON: () => ({}),
  }) as DOMRect
  document.body.append(node)
  return node
}

describe('实例级覆盖', () => {
  it('实例规则排在模板之后，靠书写顺序压过模板', () => {
    const document = empty()
    document.templates = { 'template.message': { color: '#111111' } }
    document.instances = { 'message:m1': { templateId: 'template.message', style: { color: '#222222' } } }

    const css = compileStudioDocument(document)
    const templateAt = css.indexOf(templateSelectorFor('template.message'))
    const instanceAt = css.indexOf(instanceSelectorFor('message:m1'))

    expect(instanceSelectorFor('message:m1')).toBe('[data-ui-instance="message:m1"][data-ui-instance]')
    expect(templateAt).toBeGreaterThan(-1)
    expect(instanceAt).toBeGreaterThan(templateAt)
    expect(css).toContain('color: #222222')
  })

  it('实例指向没登记的模板时被校验拒绝', () => {
    const document = empty()
    document.instances = { 'message:m1': { templateId: 'template.ghost', style: { color: '#222222' } } }

    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.path === 'instances.message:m1.templateId')).toBe(true)
  })

  it('实例不能改模板不允许的属性', () => {
    const document = empty()
    // 消息行开放了拖动/尺寸等属性，但仍不允许隐藏；用 visibility 验证越权拒绝。
    document.instances = { 'message:m1': { templateId: 'template.message', style: { visibility: false } } }

    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.path === 'instances.message:m1.style.visibility')).toBe(true)
  })

  it('实例样式缺失时报错而不是静默跳过', () => {
    const document = empty()
    document.instances = { 'message:m1': { templateId: 'template.message' } as never }

    const result = validateStudioDocument(document)
    expect(result.ok).toBe(false)
    expect(result.errors.some((issue) => issue.path === 'instances.message:m1.style')).toBe(true)
  })

  it('合法实例通过校验并随发布落到运行样式', () => {
    const root = document.createElement('div')
    const store = createStudioStore({ applyOptions: { container: root } })
    store.setInstanceNode('message:m1', 'template.message', { color: '#334455' })

    expect(store.draft.value.instances?.['message:m1']?.templateId).toBe('template.message')
    expect(store.dirty.value).toBe(true)
    expect(store.publish().ok).toBe(true)
    expect(root.querySelector('style')?.textContent).toContain('[data-ui-instance="message:m1"][data-ui-instance]')
    store.dispose()
  })

  it('撤销退回实例覆盖', () => {
    const root = document.createElement('div')
    const store = createStudioStore({ applyOptions: { container: root } })
    store.setInstanceNode('conversation:c1', 'template.conversation', { color: '#445566' })
    expect(store.draft.value.instances?.['conversation:c1']).toBeTruthy()

    store.undo()
    expect(store.draft.value.instances?.['conversation:c1']).toBeUndefined()
    store.dispose()
  })

  it('旧文档迁移后保留实例表', () => {
    const migrated = migrateStudioDocument({
      themeId: 'legacy',
      nodes: {},
      instances: { 'conversation:c1': { templateId: 'template.conversation', style: { color: '#445566' } } },
    })

    expect(migrated.ok).toBe(true)
    if (!migrated.ok) return
    expect(migrated.from).toBe(0)
    expect(migrated.document.instances?.['conversation:c1']?.style.color).toBe('#445566')
  })
})

describe('实例级覆盖的工作台行为', () => {
  beforeEach(() => {
    localStorage.clear()
    document.querySelectorAll('style[data-ui-theme-studio]').forEach((node) => node.remove())
  })

  it('点中某条消息默认编辑共享模板；显式切“此实例”才只写这一条', async () => {
    const node = stageNode('template.message', 'message:m1')
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    // user:“我编辑了一个会话行，所有的会话行都会被应用成一样的东西”+默认模板作用域。
    expect(wrapper.get('[data-studio-scope]').element.value).toBe('base')
    await wrapper.get('[data-studio-field="color"]').setValue('#123456')
    await flushPromises()
    const templateCss = previewStyle()?.textContent || ''
    expect(templateCss).toContain('[data-ui-template="template.message"][data-ui-template]')
    expect(templateCss).not.toContain('[data-ui-instance="message:m1"]')

    // 显式切到“此实例”后，才只写这一条。
    await wrapper.get('[data-studio-scope]').setValue('instance')
    await wrapper.get('[data-studio-field="color"]').setValue('#0a0b0c')
    await flushPromises()
    const css = previewStyle()?.textContent || ''
    expect(css).toContain('[data-ui-instance="message:m1"][data-ui-instance]')
    expect(css).toContain('color: #0a0b0c')

    wrapper.unmount()
    node.remove()
  })

  it('清除实例改动只删这一条，不碰模板', async () => {
    const node = stageNode('template.message', 'message:m1')
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    await wrapper.get('[data-studio-scope]').setValue('instance')
    await wrapper.get('[data-studio-field="color"]').setValue('#0a0b0c')
    await flushPromises()

    const clear = wrapper.findAll('button').find((item) => item.text() === '清除这个组件的修改')
    expect(clear).toBeTruthy()
    await clear!.trigger('click')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).not.toContain('[data-ui-instance="message:m1"][data-ui-instance]')
    expect(css).not.toContain('#0a0b0c')

    wrapper.unmount()
    node.remove()
  })

  it('从实例切回普通元素后不再写实例', async () => {
    const node = stageNode('template.message', 'message:m1')
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    await wrapper.get('[data-studio-scope]').setValue('instance')
    expect(wrapper.get('[data-studio-scope]').element.value).toBe('instance')

    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-studio-scope]').element.value).toBe('base')

    await wrapper.get('[data-studio-field="color"]').setValue('#776655')
    await flushPromises()

    const css = previewStyle()?.textContent || ''
    expect(css).toContain('[data-ui-id="shell.sidebar"][data-ui-id]')
    expect(css).toContain('color: #776655')
    expect(css).not.toContain('[data-ui-instance="message:m1"][data-ui-instance]')

    wrapper.unmount()
    node.remove()
  })

  it('选中实例时退出多选，不显示对齐条', async () => {
    const node = stageNode('template.message', 'message:m1')
    const wrapper = mount(ThemeStudio, { attachTo: document.body, global: { stubs: { teleport: true } } })
    await flushPromises()

    await wrapper.get('[data-studio-node="shell.app-rail"]').trigger('click')
    await wrapper.get('[data-studio-node="shell.sidebar"]').trigger('click', { ctrlKey: true })
    await flushPromises()
    expect(wrapper.find('[data-studio-align="left"]').exists()).toBe(true)

    node.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    await flushPromises()
    expect(wrapper.find('[data-studio-align="left"]').exists()).toBe(false)

    wrapper.unmount()
    node.remove()
  })
})
