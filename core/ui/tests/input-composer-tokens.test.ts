import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

interface CssRule {
  selector: string
  body: string
}

const packageRoot = resolve(import.meta.dirname, '..')
const workflowUiRoot = resolve(packageRoot, '..', 'src/lamtools_core/plugins/bundled/workflow/ui')

function filesUnder(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(root, entry.name)
    return entry.isDirectory() ? filesUnder(path) : [path]
  })
}

function styleRules(source: string): CssRule[] {
  const fragments = source.match(/<style\b[^>]*>([\s\S]*?)<\/style>/gi)?.map((block) => (
    block
      .replace(/^<style\b[^>]*>/i, '')
      .replace(/<\/style>\s*$/i, '')
  )) || [source]
  return fragments.flatMap((fragment) => {
    const clean = fragment.replace(/\/\*[\s\S]*?\*\//g, '')
    return [...clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
      selector: match[1].trim(),
      body: match[2].trim(),
    }))
  })
}

function readRules(path: string): CssRule[] {
  return styleRules(readFileSync(path, 'utf8'))
}

function findRule(path: string, selector: RegExp): CssRule {
  const rule = readRules(path).find((candidate) => selector.test(candidate.selector))
  if (!rule) throw new Error(`Missing CSS rule ${selector} in ${path}`)
  return rule
}

const basePath = resolve(packageRoot, 'src/styles/base.css')
const layoutPath = resolve(packageRoot, 'src/styles/layout.css')
const sessionSidebarPath = resolve(packageRoot, 'src/styles/session-sidebar.css')
const themeEditorPath = resolve(packageRoot, 'src/styles/theme-editor.css')
const subAgentEditorPath = resolve(packageRoot, 'src/components/CoreSubAgentEditor.vue')
const uiSelectPath = resolve(packageRoot, 'src/components/UiSelect.vue')

const componentPaths = [
  ...filesUnder(resolve(packageRoot, 'src/app')).filter((path) => path.endsWith('.vue')),
  ...filesUnder(resolve(packageRoot, 'src/components')).filter((path) => path.endsWith('.vue')),
  ...filesUnder(workflowUiRoot).filter((path) => path.endsWith('.vue')),
  ...[basePath, layoutPath, sessionSidebarPath, themeEditorPath],
]

const titleInputClasses = [
  'core-session-title-input',
  'session-name-input',
  'wf-title-input',
  'wf-decoration-title',
  'wf-decoration-text',
  'mode-name-input',
  'mode-description-input',
] as const
const nativeControlSelector = /input\s*\[[^\]]*type\s*=\s*['"]?(?:checkbox|radio|range|color|file|hidden|button|submit|reset|image)\b/i
const nativeControlClasses = [
  'wf-schema-toggle',
  'wf-policy-toggle',
  'wf-run-input-toggle',
  'wf-trigger-checkbox-control',
  'unlimited-toggle',
  'tool-row',
  'artifact-check',
  'right-sidebar-layout-editor-item',
] as const

function hasExactClass(selector: string, className: string): boolean {
  const escaped = className.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?:^|[\\s>+~,(])\\.${escaped}(?=$|[\\s.:#[>+~,(])`, 'i').test(selector)
}

function isNativeControl(selector: string): boolean {
  return nativeControlSelector.test(selector)
    || nativeControlClasses.some((className) => hasExactClass(selector, className))
    || /:is\(select\)/i.test(selector)
}

function isTitleInput(selector: string): boolean {
  return titleInputClasses.some((className) => hasExactClass(selector, className))
}

function assertComposerRule(path: string, selector: RegExp): void {
  const rule = findRule(path, selector)
  expect(rule.body, `${path} ${rule.selector}`).toMatch(/--theme-composer-background/)
  expect(rule.body, `${path} ${rule.selector}`).toMatch(/--theme-composer-text/)
  expect(rule.body, `${path} ${rule.selector}`).not.toMatch(/--(?:theme-control|settings-control)/)
}

function assertComposerTextRule(path: string, selector: RegExp): void {
  const rule = findRule(path, selector)
  expect(rule.body, `${path} ${rule.selector}`).toMatch(/--theme-composer-text/)
  expect(rule.body, `${path} ${rule.selector}`).not.toMatch(/--(?:theme-control|settings-control)/)
}

describe('input surfaces use the composer area recipe', () => {
  it('keeps the global text-like input recipe on composer tokens while native controls and selects stay control-scoped', () => {
    const textInputs = findRule(basePath, /input:not\([\s\S]*textarea/)
    // `:where()` contributes zero specificity. Keep this selector contract
    // explicit so a class-scoped title rule can override the shared recipe;
    // the previous bare input:not(...) selector made title backgrounds opaque.
    const normalizedTextInputSelector = textInputs.selector
      .replace(/\s+/g, ' ')
      .replace(/\(\s+/g, '(')
      .replace(/\s+\)/g, ')')
      .trim()
    expect(normalizedTextInputSelector).toBe(
      ":where(input:not([type='checkbox']):not([type='radio']):not([type='range']):not([type='color']):not([type='file']):not([type='hidden']):not([type='button']):not([type='submit']):not([type='reset']):not([type='image']), textarea)",
    )
    expect(textInputs.body).toMatch(/border:\s*1px solid color-mix\([\s\S]*--theme-composer-text/)
    expect(textInputs.body).toMatch(/background:\s*color-mix\([\s\S]*--theme-composer-background/)
    expect(textInputs.body).toMatch(/color:\s*var\(--theme-composer-text/)
    expect(textInputs.body).toMatch(/caret-color:\s*var\(--theme-composer-text/)
    expect(textInputs.body).not.toMatch(/--theme-control/)

    const select = findRule(basePath, /^select$/)
    expect(select.body).toMatch(/--theme-control-background/)
    expect(select.body).toMatch(/--theme-control-text/)
    const baseCss = readFileSync(basePath, 'utf8')
    expect(baseCss).toMatch(/input:not\(\[type='checkbox'\]\)/)
    expect(baseCss).toMatch(/input:not\(\[type='checkbox'\]\)[\s\S]*not\(\[type='radio'\]\)/)
  })

  it('keeps migrated component and workflow input rules on composer tokens', () => {
    const cases: Array<[string, RegExp]> = [
      [basePath, /input:not\([\s\S]*textarea/],
      [layoutPath, /\.field input/],
      [layoutPath, /\.field-input/],
      [resolve(packageRoot, 'src/components/AutoTextarea.vue'), /\.auto-textarea/],
      [resolve(packageRoot, 'src/components/CoreProjectSettings.vue'), /\.field-input/],
      [resolve(packageRoot, 'src/components/CoreSettings.vue'), /\.config-form input[\s\S]*\.config-form textarea/],
      [resolve(packageRoot, 'src/components/OnboardingWizard.vue'), /\.onboarding-form input/],
      [resolve(packageRoot, 'src/components/RightSidebarRag.vue'), /\.right-sidebar-rag-search input/],
      [resolve(workflowUiRoot, 'NodeEditCard.vue'), /\.wf-edit-card[\s\S]*\.field input/],
      [resolve(workflowUiRoot, 'WorkflowRunInputForm.vue'), /\.wf-run-input-field input/],
      [resolve(workflowUiRoot, 'WorkflowTriggersPanel.vue'), /\.wf-trigger-panel input:not/],
    ]
    for (const [path, selector] of cases) assertComposerRule(path, selector)
    assertComposerTextRule(resolve(packageRoot, 'src/components/CoreLoadToolsEditor.vue'), /\.loadtools-search input/)
  })

  it('does not leave control-area tokens in styled text-like inputs', () => {
    const violations: string[] = []
    for (const path of componentPaths) {
      for (const rule of readRules(path)) {
        if (!/(?:^|[\s>+~,(:])(?:input|textarea)\b/i.test(rule.selector)) continue
        if (/^button,\s*input,\s*select,\s*textarea$/i.test(rule.selector)) continue
        if (!/\b(?:background|border(?:-[\w-]+)?|color|caret-color)\s*:/.test(rule.body)) continue
        if (isTitleInput(rule.selector) || isNativeControl(rule.selector)) continue
        // Composer descendants inherit the already-tokenized composer surface;
        // a transparent/background or semantic-color override is intentional.
        if (/(?:floating-composer|composer-input-wrap)/i.test(rule.selector)) {
          if (/--(?:theme-control|settings-control)/.test(rule.body)) violations.push(`${path}: ${rule.selector} (control token)`)
          continue
        }
        if (!/--theme-composer-(?:background|text)/.test(rule.body)) violations.push(`${path}: ${rule.selector} (missing composer token)`)
        if (/--(?:theme-control|settings-control)/.test(rule.body)) violations.push(`${path}: ${rule.selector} (control token)`)
      }
    }
    expect(violations).toEqual([])
  })
})

describe('settings and select text tokens stay in their semantic areas', () => {
  it('derives sub-agent secondary text from the settings main-area preview token', () => {
    const source = readFileSync(subAgentEditorPath, 'utf8')
    expect(source.match(/--text:\s*var\(--settings-main-text,\s*var\(--theme-main-text\)\);/g)).toHaveLength(2)

    const hookMeta = findRule(subAgentEditorPath, /\.hook-meta/)
    expect(hookMeta.body).toMatch(/color-mix\([\s\S]*--settings-main-text[\s\S]*--theme-main-text/)
    expect(hookMeta.body).not.toMatch(/var\(--muted\)/)
  })

  it('keeps UiSelect menu background and text on control-area tokens', () => {
    const trigger = findRule(uiSelectPath, /\.ui-select-trigger$/)
    expect(trigger.body).toMatch(/background:\s*color-mix\([\s\S]*--settings-control-solid[\s\S]*--theme-control-solid/)
    expect(trigger.body).toMatch(/color:\s*var\(--settings-control-text,\s*var\(--theme-control-text/)
    expect(trigger.body).not.toMatch(/background:[^;]*currentColor/)

    const menu = findRule(uiSelectPath, /\.ui-select-menu$/)
    expect(menu.body).toMatch(/background:\s*var\(--settings-control-solid,\s*var\(--theme-control-background/)
    expect(menu.body).toMatch(/color:\s*var\(--settings-control-text,\s*var\(--theme-control-text/)
    expect(menu.body).not.toMatch(/--theme-composer-(?:background|text)|--settings-card-text/)
  })
})

describe('transparent title input exceptions', () => {
  it('keeps title and inline text editors transparent with local area text/caret colors', () => {
    const cases: Array<[string, RegExp]> = [
      [resolve(packageRoot, 'src/components/CoreSessionTitleEditor.vue'), /\.core-session-title-input/],
      [sessionSidebarPath, /\.session-name-input/],
      [resolve(workflowUiRoot, 'WorkflowNode.vue'), /\.wf-title-input/],
      [resolve(workflowUiRoot, 'WorkflowCanvasElement.vue'), /\.wf-decoration-title/],
      [resolve(workflowUiRoot, 'WorkflowCanvasElement.vue'), /\.wf-decoration-text/],
      [resolve(packageRoot, 'src/components/CoreLoadToolsEditor.vue'), /\.mode-name-input/],
      [resolve(packageRoot, 'src/components/CoreLoadToolsEditor.vue'), /\.mode-description-input/],
    ]
    for (const [path, selector] of cases) {
      const rule = findRule(path, selector)
      expect(rule.body, `${path} ${rule.selector}`).toMatch(/border:\s*0/)
      expect(rule.body, `${path} ${rule.selector}`).toMatch(/background:\s*transparent/)
      expect(rule.body, `${path} ${rule.selector}`).toMatch(/color\s*:/)
      expect(rule.body, `${path} ${rule.selector}`).toMatch(/caret-color\s*:/)
    }
  })

  it('lets every title exception outrank the zero-specificity global recipe', () => {
    const globalRule = findRule(basePath, /input:not\([\s\S]*textarea/)
    const normalizedGlobalSelector = globalRule.selector
      .replace(/\s+/g, ' ')
      .replace(/\(\s+/g, '(')
      .replace(/\s+\)/g, ')')
      .trim()
    expect(normalizedGlobalSelector.startsWith(':where(')).toBe(true)
    expect(normalizedGlobalSelector.endsWith(')')).toBe(true)

    const exceptionCases: Array<[string, RegExp]> = [
      [resolve(packageRoot, 'src/components/CoreSessionTitleEditor.vue'), /\.core-session-title-input/],
      [sessionSidebarPath, /\.session-name-input/],
      [resolve(workflowUiRoot, 'WorkflowNode.vue'), /\.wf-title-input/],
      [resolve(workflowUiRoot, 'WorkflowCanvasElement.vue'), /\.wf-decoration-title/],
      [resolve(workflowUiRoot, 'WorkflowCanvasElement.vue'), /\.wf-decoration-text/],
      [resolve(packageRoot, 'src/components/CoreLoadToolsEditor.vue'), /\.mode-name-input/],
      [resolve(packageRoot, 'src/components/CoreLoadToolsEditor.vue'), /\.mode-description-input/],
    ]
    for (const [path, selector] of exceptionCases) {
      const rule = findRule(path, selector)
      expect(rule.selector, `${path} ${rule.selector}`).toMatch(/\.[\w-]+/)
      expect(rule.body, `${path} ${rule.selector}`).toMatch(/border:\s*0/)
      expect(rule.body, `${path} ${rule.selector}`).toMatch(/background:\s*transparent/)
    }
  })
})
