import { mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

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

function mountSettings() {
  return mount(CoreSettings, {
    props: {
      models,
      providers,
      density: 'standard',
      theme: structuredClone(DEFAULT_THEME),
    },
  })
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

  it('emits provider create and update contracts without replaying a stored API key', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-provider-create]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('New provider')
    await wrapper.get('[data-provider-api-type]').setValue('anthropic')
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
    await wrapper.get('[data-model-provider-id]').setValue('provider-1')
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

  it('reuses ThemeEditor and emits density changes', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-settings-section="appearance"]').trigger('click')

    expect(wrapper.findComponent({ name: 'ThemeEditor' }).exists()).toBe(true)
    await wrapper.get('[data-density="loose"]').trigger('click')

    expect(wrapper.emitted('update:density')).toEqual([['loose']])
  })

  it('owns writable command permission policy controls', async () => {
    const wrapper = mountSettings()

    await wrapper.get('[data-settings-section="permissions"]').trigger('click')

    expect(wrapper.text()).toContain('权限策略')
    expect(wrapper.text()).toContain('常规命令')
    expect(wrapper.findAll('input, select, textarea').length).toBe(0)
    const askButtons = wrapper.findAll('button').filter(button => button.text() === '需要审批')
    await askButtons[0].trigger('click')
    expect(wrapper.emitted('update-command-policy')).toEqual([['regular', 'ask_user']])
  })
})

describe('Core demo settings entry', () => {
  it('connects the WorkspaceShell settings action to Core config operations', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/demo/App.vue'), 'utf8')

    expect(source).toContain('@settings="showSettings = true"')
    expect(source).toContain('<CoreSettings')
    expect(source).toContain('useCoreUiPreferences(settingsStorageKey)')
    expect(source).toContain(':content-width="contentWidth"')
    expect(source).toContain('@update:content-width="uiPreferences.setContentWidth"')
    expect(source).toContain("@import '../styles/theme-editor.css';")
    expect(source).toContain("'config.provider.create'")
    expect(source).toContain("'config.provider.update'")
    expect(source).toContain("'config.provider.delete'")
    expect(source).toContain("'config.model.create'")
    expect(source).toContain("'config.model.update'")
    expect(source).toContain("'config.model.delete'")
  })
})
