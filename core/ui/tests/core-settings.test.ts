import { flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import CoreSettings from '../src/components/CoreSettings.vue'
import { DEFAULT_THEME } from '../src/helpers/theme'

const models = [{
  id: 'model-1',
  provider_id: 'provider-1',
  model_id: 'gpt-test',
  display_name: 'GPT Test',
}]

const providers = [{
  id: 'provider-1',
  name: 'OpenAI',
  api_type: 'openai',
  base_url: 'https://api.openai.com/v1',
  api_key: 'sk...live',
  has_api_key: true,
}]

function mountSettings(
  requestRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>,
  overrides: {
    models?: typeof models
    providers?: typeof providers
    modelGroups?: Array<{ id: string; name: string; model_ids: string[] }>
    catalogView?: 'group' | 'provider'
    commandShellPlatform?: 'windows' | 'linux' | 'mobile' | 'web' | 'other'
  } = {},
) {
  return mount(CoreSettings, {
    props: {
      models: overrides.models ?? models,
      providers: overrides.providers ?? providers,
      modelGroups: overrides.modelGroups ?? [],
      catalogView: overrides.catalogView ?? 'provider',
      commandShellPlatform: overrides.commandShellPlatform ?? 'other',
      density: 'standard',
      theme: structuredClone(DEFAULT_THEME),
      requestRpc,
    },
    // CoreSettings teleports its whole content to body; stub Teleport so
    // wrapper queries hit the rendered tree (see core-project-components.test.ts)
    global: { stubs: { Teleport: true } },
  })
}

/** 原生 select 已收敛为 UiSelect：点开触发器 → 按选项 label 点击。 */
async function selectUiOption(wrapper: ReturnType<typeof mountSettings>, selector: string, label: string) {
  await wrapper.get(selector).find('.ui-select-trigger').trigger('click')
  const option = wrapper.findAll('.ui-select-option').find(button => button.text() === label)
  expect(option).toBeTruthy()
  await option!.trigger('click')
}

describe('CoreSettings', () => {
  it('shows Core model and provider state without exposing an API key', () => {
    const wrapper = mountSettings()

    expect(wrapper.text()).toContain('模型与供应商')
    expect(wrapper.text()).toContain('GPT Test')
    expect(wrapper.text()).toContain('OpenAI')
    expect(wrapper.text()).toContain('已配置密钥')
    expect(wrapper.text()).not.toContain('sk...live')
    expect(wrapper.text()).not.toContain('Writer')
  })

  it('keeps contextual create actions and filters providers and models', async () => {
    const wrapper = mountSettings()

    expect(wrapper.find('.models-overview-bar').exists()).toBe(false)
    expect(wrapper.find('.provider-rail-footer [data-provider-create]').exists()).toBe(true)
    expect(wrapper.find('.model-section-head [data-model-create]').exists()).toBe(true)

    await wrapper.get('.provider-search input').setValue('missing')
    expect(wrapper.text()).toContain('没有匹配的供应商')
    await wrapper.get('.provider-search input').setValue('open')
    expect(wrapper.text()).not.toContain('没有匹配的供应商')

    await wrapper.get('.model-search input').setValue('missing')
    expect(wrapper.text()).toContain('没有匹配的模型')
  })

  it('keeps provider and model empty-state create actions', () => {
    const emptyProviders = mountSettings(undefined, { providers: [] })
    expect(emptyProviders.find('.models-overview-bar').exists()).toBe(false)
    expect(emptyProviders.find('.models-empty-state--full [data-provider-create]').exists()).toBe(true)
    emptyProviders.unmount()

    const emptyModels = mountSettings(undefined, { models: [] })
    expect(emptyModels.find('.models-overview-bar').exists()).toBe(false)
    expect(emptyModels.find('.provider-rail-footer [data-provider-create]').exists()).toBe(true)
    expect(emptyModels.find('.model-section-head [data-model-create]').exists()).toBe(true)
    expect(emptyModels.find('.model-empty .small-btn').exists()).toBe(true)
    emptyModels.unmount()
  })

  it('emits provider create and update contracts without replaying a stored API key', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-provider-create]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('New provider')
    await selectUiOption(wrapper, '[data-provider-api-type]', 'Anthropic')
    await wrapper.get('[data-provider-base-url]').setValue('https://api.anthropic.com/v1')
    await wrapper.get('[data-provider-api-key]').setValue('new-secret')
    await wrapper.get('[data-provider-form="create"]').trigger('submit')

    expect(wrapper.emitted('create-provider')).toEqual([[
      {
        name: 'New provider',
        api_type: 'anthropic',
        base_url: 'https://api.anthropic.com/v1',
        api_key: 'new-secret',
        extra: {},
      },
    ]])

    await wrapper.get('[data-provider-edit="provider-1"]').trigger('click')
    expect((wrapper.get('[data-provider-api-key]').element as HTMLInputElement).value).toBe('')
    await wrapper.get('[data-provider-name]').setValue('Renamed provider')
    await wrapper.get('[data-provider-form="update"]').trigger('submit')

    expect(wrapper.emitted('update-provider')).toEqual([[
      {
        provider_id: 'provider-1',
        name: 'Renamed provider',
        api_type: 'openai',
        base_url: 'https://api.openai.com/v1',
        extra: {},
      },
    ]])
  })

  it('emits model create, update, and delete contracts', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-model-create]').trigger('click')
    await selectUiOption(wrapper, '[data-model-provider-id]', 'OpenAI')
    await wrapper.get('[data-model-id]').setValue('gpt-new')
    await wrapper.get('[data-model-display-name]').setValue('GPT New')
    await wrapper.get('[data-model-form="create"]').trigger('submit')

    expect(wrapper.emitted('create-model')?.[0]).toEqual([expect.objectContaining({
      provider_id: 'provider-1',
      model_id: 'gpt-new',
      display_name: 'GPT New',
    })])

    await wrapper.get('[data-model-edit="model-1"]').trigger('click')
    await wrapper.get('[data-model-display-name]').setValue('GPT Renamed')
    await wrapper.get('[data-model-form="update"]').trigger('submit')
    await wrapper.get('[data-model-delete="model-1"]').trigger('click')

    expect(wrapper.emitted('update-model')?.[0]).toEqual([expect.objectContaining({
      model_record_id: 'model-1',
      display_name: 'GPT Renamed',
    })])
    expect(wrapper.emitted('delete-model')).toEqual([['model-1']])
  })

  it('opens ThemeEditor and emits appearance settings changes', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-settings-section="appearance"]').trigger('click')

    expect(wrapper.findComponent({ name: 'ThemeEditor' }).exists()).toBe(true)
    await wrapper.get('.theme-advanced > summary').trigger('click')
    await wrapper.get('[data-density="loose"]').trigger('click')
    await wrapper.get('[data-theme-mode="dark"]').trigger('click')
    await wrapper.get('[data-theme-process-icon-color]').setValue('#6755e8')

    expect(wrapper.emitted('update:density')).toEqual([['loose']])
    expect(wrapper.emitted('update:theme-mode')).toEqual([['dark']])
    expect(wrapper.emitted('update-process-icon-color')).toEqual([['#6755e8']])
  })

  it('marks free presets for the durable Free group and opens the API key page externally', async () => {
    const openUrl = vi.fn(async () => true)
    window.__LAMTOOLS_OPEN_URL__ = openUrl
    const wrapper = mountSettings()
    await wrapper.get('[data-provider-create]').trigger('click')
    await selectUiOption(wrapper, '[data-provider-preset]', 'OpenCode Free')
    await wrapper.get('[data-provider-api-key-link]').trigger('click')
    expect(openUrl).toHaveBeenCalledWith('https://opencode.ai/auth')
    await wrapper.get('[data-provider-api-key]').setValue('test-key')
    await wrapper.get('[data-provider-form="create"]').trigger('submit')
    expect(wrapper.emitted('create-provider')?.[0]?.[0]).toMatchObject({ model_group_name: 'Free' })
    delete window.__LAMTOOLS_OPEN_URL__
  })

  it('manages group membership and creates a grouped model with a required provider URL', async () => {
    const wrapper = mountSettings(undefined, {
      catalogView: 'group',
      modelGroups: [{ id: 'free', name: 'Free', model_ids: ['model-1'] }],
    })

    expect(wrapper.get('[data-model-catalog-view="group"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.text()).toContain('Free')
    expect(wrapper.text()).toContain('GPT Test')

    await wrapper.get('[data-model-group-remove="model-1"]').trigger('click')
    expect(wrapper.emitted('set-model-group-members')).toContainEqual([{ group_id: 'free', model_ids: [] }])

    await wrapper.get('[data-model-group-members]').trigger('click')
    expect(wrapper.find('[data-model-group-members-form]').exists()).toBe(true)
    await wrapper.get('[data-model-group-members-form]').trigger('submit')
    expect(wrapper.emitted('set-model-group-members')).toContainEqual([{ group_id: 'free', model_ids: ['model-1'] }])

    await wrapper.get('[data-group-model-create]').trigger('click')
    expect((wrapper.get('[data-model-base-url]').element as HTMLInputElement).value).toBe('https://api.openai.com/v1')
    await wrapper.get('[data-model-id]').setValue('upstream/new')
    await wrapper.get('[data-model-display-name]').setValue('New')
    await wrapper.get('[data-model-form="create"]').trigger('submit')
    expect(wrapper.emitted('create-model-with-provider')?.[0]?.[0]).toMatchObject({
      group_id: 'free',
      model: { model_id: 'upstream/new' },
      provider: { mode: 'existing', provider_id: 'provider-1', base_url: 'https://api.openai.com/v1' },
    })
  })

  it('emits group CRUD and catalog classification changes', async () => {
    const wrapper = mountSettings(undefined, { catalogView: 'group' })
    await wrapper.get('[data-model-catalog-view="provider"]').trigger('click')
    expect(wrapper.emitted('update:catalogView')).toEqual([['provider']])

    await wrapper.get('[data-model-group-create]').trigger('click')
    await wrapper.get('[data-model-group-name]').setValue('Coding')
    await wrapper.get('[data-model-group-form]').trigger('submit')
    expect(wrapper.emitted('create-model-group')).toEqual([[{ name: 'Coding' }]])
  })

  it('opens the matching floating editor from the theme preview', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-settings-section="appearance"]').trigger('click')
    await wrapper.get('[data-theme-preview-area="composer"]').trigger('click')

    expect(wrapper.findAll('.theme-area-popover')).toHaveLength(1)
    expect(wrapper.get('.theme-area-popover').text()).toContain('输入栏')

    await wrapper.get('[data-theme-area="control"]').trigger('click')
    expect(wrapper.findAll('.theme-area-popover')).toHaveLength(1)
    expect(wrapper.get('[data-theme-area="composer"]').attributes('aria-expanded')).toBe('false')
    expect(wrapper.get('[data-theme-area="control"]').attributes('aria-expanded')).toBe('true')
  })

  it('forwards theme area angle changes from the floating editor', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-settings-section="appearance"]').trigger('click')
    await wrapper.get('[data-theme-preview-area="backdrop"]').trigger('click')
    await wrapper.get('.theme-area-popover input[type="range"]').setValue(45)

    expect(wrapper.emitted('update-angle')).toContainEqual(['backdrop', 45])
  })

  it('uses the same three permission presets as the composer', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-settings-section="permissions"]').trigger('click')

    expect(wrapper.text()).toContain('权限审批')
    expect(wrapper.text()).not.toContain('只读调查')
    expect(wrapper.text()).not.toContain('有限编辑')
    expect(wrapper.findAll('input, select, textarea').length).toBe(0)
    expect(wrapper.findAll('[data-default-permission-preset]')).toHaveLength(3)
    await wrapper.get('[data-default-permission-preset="full_access"]').trigger('click')
    expect(wrapper.emitted('update-permission-preset')).toEqual([['full_access']])
    await wrapper.get('[data-allow-outside-workdir]').trigger('click')
    expect(wrapper.emitted('update-allow-outside-workdir')).toEqual([[true]])
  })

  it('toggles and persists button-based settings controls', async () => {
    localStorage.clear()
    const rpc = vi.fn(async (method: string) => {
      if (method === 'settings.get') return { value: { enabled: false, min_turns: 3 } }
      return {}
    })
    const wrapper = mountSettings(rpc)
    await flushPromises()

    await wrapper.get('[data-settings-section="about"]').trigger('click')
    const updateToggle = wrapper.get('[data-update-auto-check]')
    expect(updateToggle.attributes('aria-pressed')).toBe('true')
    await updateToggle.trigger('click')
    expect(updateToggle.attributes('aria-pressed')).toBe('false')
    expect(localStorage.getItem('lamtools.update.autoCheck')).toBe('false')

    await wrapper.get('[data-settings-section="agents"]').trigger('click')
    const dreamingToggle = wrapper.get('[aria-label="自动记忆整理"]')
    await dreamingToggle.trigger('click')
    await flushPromises()
    expect(dreamingToggle.attributes('aria-pressed')).toBe('true')
    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.dreaming',
      value: { enabled: true, min_turns: 3 },
    })

    wrapper.unmount()
    localStorage.clear()
  })

  it('loads the context compaction default and explains Step retention', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'settings.get' && params?.namespace === 'core.contextCompaction') return { value: {} }
      if (method === 'settings.get') return { value: { enabled: false, min_turns: 3 } }
      return {}
    })
    const wrapper = mountSettings(rpc)
    await flushPromises()
    await wrapper.get('[data-settings-section="agents"]').trigger('click')

    const input = wrapper.get('[data-context-compaction-retained-steps]')
    expect((input.element as HTMLInputElement).value).toBe('0')
    expect(input.attributes('min')).toBe('0')
    expect(input.attributes('max')).toBe('100')
    expect(wrapper.text()).toContain('一个 Step 是一次模型响应及其后续工具结果')
    expect(wrapper.text()).toContain('默认保留 0 个 Step，历史会全部汇总')
    expect(wrapper.text()).toContain('最新 20 条用户指令')
    expect(wrapper.text()).toContain('原文追加为编号的“Recent user messages”段落')
    expect(wrapper.text()).toContain('令牌预算不足时较早条目会静默丢弃')

    wrapper.unmount()
  })

  it('normalizes invalid context compaction values and clamps before saving', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'settings.get' && params?.namespace === 'core.contextCompaction') {
        return { value: { retained_steps: 'not-a-number' } }
      }
      if (method === 'settings.get') return { value: { enabled: false, min_turns: 3 } }
      return {}
    })
    const wrapper = mountSettings(rpc)
    await flushPromises()
    await wrapper.get('[data-settings-section="agents"]').trigger('click')
    const input = wrapper.get('[data-context-compaction-retained-steps]')
    const save = wrapper.get('[data-context-compaction-save]')

    expect((input.element as HTMLInputElement).value).toBe('0')
    await input.setValue('999')
    await save.trigger('click')
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe('100')
    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.contextCompaction',
      value: { retained_steps: 100 },
    })

    await input.setValue('0')
    await save.trigger('click')
    await flushPromises()
    expect((input.element as HTMLInputElement).value).toBe('0')
    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.contextCompaction',
      value: { retained_steps: 0 },
    })

    wrapper.unmount()
  })

  it('saves the context compaction retained_steps payload', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'settings.get' && params?.namespace === 'core.contextCompaction') {
        return { value: { retained_steps: 6 } }
      }
      if (method === 'settings.get') return { value: { enabled: false, min_turns: 3 } }
      return {}
    })
    const wrapper = mountSettings(rpc)
    await flushPromises()
    await wrapper.get('[data-settings-section="agents"]').trigger('click')

    rpc.mockClear()
    await wrapper.get('[data-context-compaction-refresh]').trigger('click')
    await flushPromises()
    expect(rpc).toHaveBeenCalledWith('settings.get', { namespace: 'core.contextCompaction' })

    await wrapper.get('[data-context-compaction-retained-steps]').setValue('18')
    await wrapper.get('[data-context-compaction-save]').trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.contextCompaction',
      value: { retained_steps: 18 },
    })

    wrapper.unmount()
  })

  it('loads and persists the Windows command shell preference', async () => {
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'settings.get' && params?.namespace === 'core.commandShell') {
        return { value: { preference: 'git-bash' } }
      }
      return {}
    })
    const wrapper = mountSettings(rpc, { commandShellPlatform: 'windows' })
    await flushPromises()
    await wrapper.get('[data-settings-section="loadtools"]').trigger('click')

    expect(rpc).toHaveBeenCalledWith('settings.get', { namespace: 'core.commandShell' })
    const select = wrapper.get('[data-command-shell-card] .ui-select-trigger')
    expect(select.text()).toContain('Git Bash')
    await select.trigger('click')
    const option = wrapper.findAll('.ui-select-option').find(item => item.text() === 'WSL')
    expect(option).toBeTruthy()
    await option!.trigger('click')
    await flushPromises()

    expect(rpc).toHaveBeenCalledWith('settings.update', {
      namespace: 'core.commandShell',
      value: { preference: 'wsl' },
    })
    expect(wrapper.get('[data-command-shell-card] .ui-select-trigger').text()).toContain('WSL')
    expect(wrapper.text()).toContain('WSL → Git Bash → PowerShell')
    expect(wrapper.text()).toContain('手动选择的 shell 不可用时也会按此顺序回退')
    wrapper.unmount()
  })

  it('reverts a failed shell save and shows platform-specific visibility', async () => {
    const failingRpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'settings.get' && params?.namespace === 'core.commandShell') {
        return { value: { preference: 'powershell' } }
      }
      if (method === 'settings.update' && params?.namespace === 'core.commandShell') {
        throw new Error('write failed')
      }
      return {}
    })
    const windows = mountSettings(failingRpc, { commandShellPlatform: 'windows' })
    await flushPromises()
    await windows.get('[data-settings-section="loadtools"]').trigger('click')
    await windows.get('[data-command-shell-card] .ui-select-trigger').trigger('click')
    const wslOption = windows.findAll('.ui-select-option').find(item => item.text() === 'WSL')
    await wslOption!.trigger('click')
    await flushPromises()
    expect(windows.get('[data-command-shell-card] .ui-select-trigger').text()).toContain('PowerShell')
    expect(windows.get('[data-command-shell-error]').text()).toContain('write failed')
    windows.unmount()

    const linux = mountSettings(undefined, { commandShellPlatform: 'linux' })
    await linux.get('[data-settings-section="loadtools"]').trigger('click')
    expect(linux.find('[data-command-shell-card]').text()).toContain('Linux 直接运行本机命令')
    expect(linux.find('[data-command-shell-card] .ui-select-trigger').exists()).toBe(false)
    linux.unmount()

    const mobile = mountSettings(undefined, { commandShellPlatform: 'mobile' })
    await mobile.get('[data-settings-section="loadtools"]').trigger('click')
    expect(mobile.find('[data-command-shell-card]').exists()).toBe(false)
    mobile.unmount()
  })

  it('shows mobile-local context storage copy and keeps desktop paths and CLI guidance', async () => {
    const mobile = mountSettings(undefined, { commandShellPlatform: 'mobile' })
    await mobile.get('[data-settings-section="agents"]').trigger('click')
    const mobileCopy = mobile.get('.settings-panel').text()
    expect(mobileCopy).toContain('应用私有 SQLite 配置')
    expect(mobileCopy).not.toContain('.lam/core/config')
    expect(mobileCopy).not.toContain('CLI：')
    mobile.unmount()

    const desktop = mountSettings(undefined, { commandShellPlatform: 'windows' })
    await desktop.get('[data-settings-section="agents"]').trigger('click')
    const desktopCopy = desktop.get('.settings-panel').text()
    expect(desktopCopy).toContain('.lam/core/config/AGENTS.md')
    expect(desktopCopy).toContain('core memory get/set')
    expect(desktopCopy).toContain('core load-context get/set')
    expect(desktopCopy).toContain('core memory dream show/config')
    desktop.unmount()
  })
})

describe('Core settings permission contract', () => {
  // The permissions panel mounts inside SettingsShell and the existing test
  // environment cannot render it reliably (pre-existing recursive-update issue
  // on this branch); assert the toggle contract against the source instead.
  it('wires the allow-access-outside-workdir toggle in CoreSettings', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/CoreSettings.vue'), 'utf8')
    expect(source).toContain('allowAccessOutsideWorkdir?: boolean')
    expect(source).toContain("'update-allow-outside-workdir': [value: boolean]")
    expect(source).toContain('data-allow-outside-workdir')
    expect(source).toContain('允许访问工作目录以外')
    expect(source).toContain("emit('update-allow-outside-workdir', !Boolean(props.allowAccessOutsideWorkdir))")
    expect(source).toContain("['ask', 'auto', 'full_access']")
    expect(source).not.toContain("'update-permission-mode'")
  })

  it('describes the approval-instead-of-block boundary copy', () => {
    const settings = readFileSync(resolve(process.cwd(), 'src/components/CoreSettings.vue'), 'utf8')
    const presets = readFileSync(resolve(process.cwd(), 'src/composer/execution.ts'), 'utf8')
    expect(settings).toContain('工作目录外的读写与命令行访问会先征求你的确认，批准后本次执行。')
    expect(settings).toContain('工作目录外需确认')
    expect(presets).toContain('在当前能力范围内自动批准（工作目录外仍会确认）')
  })

  it('binds the toggle state in the Shared Core App', () => {
const source = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
    expect(source).toContain(':allow-access-outside-workdir="allowAccessOutsideWorkdir"')
    expect(source).toContain('@update-allow-outside-workdir="updateAllowAccessOutsideWorkdir"')
    expect(source).toContain("allow_access_outside_workdir")
  })
})

describe('Shared Core App settings entry', () => {
  it('connects the WorkspaceShell settings action to Core config operations', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')

    expect(source).toContain('@settings="openSettings"')
    expect(source).toContain('<CoreSettings')
    // Preferences persist under a key split from the shell's (which also
    // stores stageOpen/stageHeight) so neither schema clobbers the other
    // (audit 19 S3).
    expect(source).toContain("useCoreUiPreferences('lamtools.core.ui.preferences')")
    expect(source).toContain(':content-width="contentWidth"')
    expect(source).toContain('@update:content-width="uiPreferences.setContentWidth"')
    expect(source).toContain("@import '../styles/theme-editor.css';")
    expect(source).toContain("'config.provider.create'")
    expect(source).toContain("'config.provider.update'")
    expect(source).toContain("'config.provider.delete'")
    expect(source).toContain("'config.models.upsert'")
    expect(source).toContain("'config.models.delete'")
    expect(source).toContain("'config.models.set_default'")
    expect(source).toContain("namespace: 'core.modelCatalog'")
    expect(source).toContain('@update:catalog-view="updateModelCatalogView"')
    expect(source).toContain("'config.model_group.members.set'")
  })

  it('keeps account-specific preset URLs editable', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/components/CoreSettings.vue'), 'utf8')
    expect(source).toContain("selectedProviderPreset?.baseUrlEditable")
    expect(source).toContain('data-provider-base-url')
  })

  it('passes the host command-shell platform to CoreSettings', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/LamToolsApp.vue'), 'utf8')
    expect(source).toContain(':command-shell-platform="commandShellPlatform"')
    expect(source).toContain("if (appRuntime.platform === 'mobile') return 'mobile'")
    expect(source).toContain("return 'windows' as const")
    expect(source).toContain("return 'linux' as const")
  })
})
