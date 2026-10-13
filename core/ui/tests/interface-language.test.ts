import { afterEach, describe, expect, it, vi } from 'vitest'
import { computed, nextTick } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { t, uiLanguage, setUiLanguage, saveUiLanguage, loadUiLanguage, defaultUiText, UI_LANGUAGES } from '../src/i18n'
import { CORE_SETTINGS_SECTIONS } from '../src/components/settingsSections'
import { CORE_PERMISSION_PRESET_LABELS } from '../src/composer/execution'
import CoreGeneralEditor from '../src/components/CoreGeneralEditor.vue'
import MarkdownRenderer from '../src/components/MarkdownRenderer.vue'
import { WorkflowNodeCatalog } from '@lamtools/bundled-workflow-ui'
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, join } from 'node:path'
import ts from 'typescript'
import { parse } from '@vue/compiler-sfc'
import { parse as parseTemplate } from '@vue/compiler-dom'
import UiSelect from '../src/components/UiSelect.vue'
import zh from '../src/i18n/locales/zh-CN.json'
import tw from '../src/i18n/locales/zh-TW.json'
import ja from '../src/i18n/locales/ja.json'
import en from '../src/i18n/locales/en.json'

afterEach(() => setUiLanguage('zh-CN'))

describe('interface language', () => {
  it('includes every static translation key used by Core and Workflow', () => {
    const keys = new Set<string>()
    function scan(text: string) {
      const ast = ts.createSourceFile('copy.ts', text, ts.ScriptTarget.Latest, true)
      function visit(node: ts.Node) {
        if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
          const argument = node.arguments[node.expression.text === 't' ? 0 : node.expression.text === 'defaultUiText' ? 1 : -1]
          if (argument && ts.isStringLiteral(argument)) keys.add(argument.text)
        }
        ts.forEachChild(node, visit)
      }
      visit(ast)
    }
    function walk(dir: string) {
      for (const file of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, file.name)
        if (file.isDirectory()) {
          if (!['archived', 'demo', 'i18n'].includes(file.name)) walk(path)
        } else if (path.endsWith('.ts')) scan(readFileSync(path, 'utf8'))
        else if (path.endsWith('.vue')) {
          const { descriptor } = parse(readFileSync(path, 'utf8'))
          if (descriptor.scriptSetup) scan(descriptor.scriptSetup.content)
          if (descriptor.script) scan(descriptor.script.content)
          if (descriptor.template) {
            function visit(node: any) {
              if (node.type === 5) scan(node.content.content)
              for (const prop of node.props ?? []) if (prop.type === 7 && prop.exp) scan(prop.exp.content)
              for (const child of node.children ?? []) visit(child)
            }
            visit(parseTemplate(descriptor.template.content))
          }
        }
      }
    }
    walk(resolve(import.meta.dirname, '../src'))
    walk(resolve(import.meta.dirname, '../../src/lamtools_core/plugins/bundled/workflow/ui'))
    expect([...keys].filter(key => !Object.hasOwn(zh, key)).sort()).toEqual([])
  })
  it('ships matching nonempty catalogs for all four languages', () => {
    for (const catalog of [tw, ja, en]) {
      expect(Object.keys(catalog).sort()).toEqual(Object.keys(zh).sort())
      for (const [key, value] of Object.entries(catalog)) {
        expect(value.trim(), key).not.toBe('')
        expect([...value.matchAll(/\{\w+\}/g)].map(m => m[0]).sort(), key)
          .toEqual([...key.matchAll(/\{\w+\}/g)].map(m => m[0]).sort())
      }
    }
  })
  it('reactively updates copy, module-level labels and document language', () => {
    const label = computed(() => CORE_SETTINGS_SECTIONS.find(s => s.id === 'general')!.label)
    expect(label.value).toBe('通用')
    setUiLanguage('en')
    expect(label.value).toBe('General')
    expect(t('保存')).toBe('Save')
    expect(CORE_PERMISSION_PRESET_LABELS.ask).toBe('Ask')
    expect(document.documentElement.lang).toBe('en')
    expect(t('Unknown key')).toBe('Unknown key')
  })
  it('loads the saved setting and falls back for invalid configuration', async () => {
    await loadUiLanguage(vi.fn().mockResolvedValue({ value: { locale: 'ja' } }))
    expect(uiLanguage.value).toBe('ja')
    await loadUiLanguage(vi.fn().mockResolvedValue({ value: { locale: 'fr' } }))
    expect(uiLanguage.value).toBe('zh-CN')
  })
  it('does not let a delayed startup read overwrite a newer language choice', async () => {
    let finish!: (value: Record<string, unknown>) => void
    const loading = loadUiLanguage(() => new Promise(resolve => { finish = resolve }))
    await saveUiLanguage(vi.fn().mockResolvedValue({}), 'en')
    finish({ value: { locale: 'zh-CN' } })
    await loading
    expect(uiLanguage.value).toBe('en')
  })
  it('preserves custom copy and interpolated user/model content verbatim', () => {
    setUiLanguage('en')
    expect(defaultUiText('My model 保存', '保存')).toBe('My model 保存')
    expect(defaultUiText('保存', '保存')).toBe('Save')
    expect(t('未找到：{0}', { 0: '项目/保存.md' })).toContain('项目/保存.md')
    expect(t('未知 {0}', { 0: null })).toBe('未知 null')
  })
  it('persists before switching and retains the old language on failure', async () => {
    const rpc = vi.fn().mockRejectedValue(new Error('Save failed'))
    await expect(saveUiLanguage(rpc, 'en')).rejects.toThrow('Save failed')
    expect(uiLanguage.value).toBe('zh-CN')
    await expect(saveUiLanguage(rpc, 'fr')).rejects.toThrow('Unsupported')
    expect(rpc).toHaveBeenCalledTimes(1)
    rpc.mockResolvedValue({ value: { locale: 'en' } })
    await saveUiLanguage(rpc, 'en')
    expect(rpc).toHaveBeenLastCalledWith('settings.update', { namespace: 'core.language', value: { locale: 'en' } })
    expect(uiLanguage.value).toBe('en')
  })
  it('switches all four languages in place without losing a settings draft', async () => {
    const rpc = vi.fn().mockResolvedValue({ value: {} })
    const wrapper = mount(CoreGeneralEditor, { props: { requestRpc: rpc, platform: 'web' } })
    await flushPromises()
    const input = wrapper.get('input')
    await input.setValue('http://unsaved.example:7890')
    for (const language of UI_LANGUAGES) {
      wrapper.getComponent(UiSelect).vm.$emit('update:modelValue', language.value)
      await flushPromises()
      await nextTick()
      expect(uiLanguage.value).toBe(language.value)
      expect((input.element as HTMLInputElement).value).toBe('http://unsaved.example:7890')
      expect(wrapper.text()).toContain(t('界面语言'))
    }
    wrapper.unmount()
  })
  it('keeps workflow category ids stable when switching languages', async () => {
    const wrapper = mount(WorkflowNodeCatalog, { props: {
      schemas: {
        model: { name: 'model', category: 'ai', input: {}, output: {} },
        command: { name: 'command', category: 'runtime', input: {}, output: {} },
      },
      onAdd: vi.fn(),
    } })
    for (const language of UI_LANGUAGES) {
      setUiLanguage(language.value)
      await nextTick()
      const buttons = wrapper.findAll('.wf-category-btn')
      await buttons[1].trigger('click')
      expect(wrapper.findAll('.wf-catalog-item')).toHaveLength(1)
      await buttons[0].trigger('click')
      expect(wrapper.findAll('.wf-catalog-item')).toHaveLength(2)
    }
    wrapper.unmount()
  })
  it.each([false, true])('refreshes cached Markdown controls without translating code (streaming=%s)', async (streaming) => {
    const source = '```js\nconst message = "保存";\n```\n\nunfinished'
    const wrapper = mount(MarkdownRenderer, { props: { content: source, streaming } })
    await flushPromises()
    expect(wrapper.get('.code-copy').attributes('aria-label')).toBe('复制代码')
    for (const language of UI_LANGUAGES) {
      setUiLanguage(language.value)
      await flushPromises()
      expect(wrapper.get('.code-copy').attributes('aria-label')).toBe(t('复制代码'))
      expect(wrapper.get('.code-source').text()).toBe('const message = "保存";')
    }
    wrapper.unmount()
  })
})
