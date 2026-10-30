import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import CoreSettings from '../src/components/CoreSettings.vue'
import CoreProjectSettings from '../src/components/CoreProjectSettings.vue'
import CoreConfirmDialog from '../src/components/CoreConfirmDialog.vue'
import CoreSubAgentEditor from '../src/components/CoreSubAgentEditor.vue'
import UiSelect from '../src/components/UiSelect.vue'
import { DEFAULT_THEME } from '../src/helpers/theme'
import { createSettingsDraftGuard, useSettingsDraft } from '../src/composables/useSettingsDraftGuard'

const mounted: VueWrapper[] = []
afterEach(() => { for (const wrapper of mounted.splice(0)) wrapper.unmount() })
const providers = [{ id: 'p1', name: 'Provider', api_type: 'openai', base_url: 'https://example.com', has_api_key: true }]
const models = [{ id: 'm1', provider_id: 'p1', model_id: 'model', display_name: 'Model', capability: 'multimodal' }]
const groups = [{ id: 'g1', name: 'Group', model_ids: ['m1'] }]
type Rpc = (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>

function rpcFixture(): Rpc {
  const settings: Record<string, Record<string, unknown>> = {
    'core.contextCompaction': { retained_steps: 6 }, 'core.network': { proxy: 'http://original:8080', no_proxy: '', ca_cert: '' },
    'core.memoryResume': { enabled: true, threshold_gb: 4 },
  }
  let agents = '# Saved rules'
  let modes = { execute: { description: 'Saved mode', tools: ['read_file'] } }
  let subagent: Record<string, unknown> = { default_multimodal_model: '', delegation_strategy: 'medium', role_assignments: [] }
  return vi.fn(async (method: string, params?: Record<string, unknown>) => {
    if (method === 'settings.get') return { value: settings[String(params?.namespace)] || {} }
    if (method === 'settings.update') {
      settings[String(params?.namespace)] = { ...settings[String(params?.namespace)], ...(params?.value as object) }
      return { value: settings[String(params?.namespace)] }
    }
    if (method === 'config.agents_md.get') return { agents_md: { content: agents } }
    if (method === 'config.agents_md.set') { agents = String(params?.content); return {} }
    if (method === 'config.load_context.get') return { addition: [], except: [] }
    if (method === 'config.loadtools.get') return { modes, catalog: [{ name: 'read_file', category: 'file_read' }] }
    if (method === 'config.loadtools.set') { modes = params?.modes as typeof modes; return { modes } }
    if (method === 'config.subagent.guide.get') return { content: '# Saved guide' }
    if (method === 'config.subagent.settings.get') return { settings: subagent, effective_delegation_strategy: subagent.delegation_strategy }
    if (method === 'config.subagent.settings.set') { subagent = { ...subagent, ...(params?.settings as object) }; return {} }
    return {}
  })
}

async function settings(overrides: Record<string, unknown> = {}, rpc = rpcFixture()) {
  const wrapper = mount(CoreSettings, {
    attachTo: document.body,
    props: { providers, models, modelGroups: groups, density: 'standard', theme: structuredClone(DEFAULT_THEME), requestRpc: rpc, ...overrides },
    global: { stubs: { Teleport: true } },
  })
  mounted.push(wrapper)
  await flushPromises()
  return wrapper
}
function decision(wrapper: VueWrapper) { return wrapper.getComponent(CoreConfirmDialog) }
async function choose(wrapper: VueWrapper, action: 'cancel' | 'discard' | 'save') {
  await flushPromises()
  const dialog = decision(wrapper)
  if (action === 'save') await dialog.get('.core-confirm__submit').trigger('click')
  else await dialog.findAll('.core-confirm__cancel')[action === 'cancel' ? 0 : 1].trigger('click')
  await flushPromises()
}

describe('settings draft protection', () => {
  it('does not confirm an untouched editor or an edit restored to its initial value', async () => {
    const wrapper = await settings()
    await wrapper.get('[data-provider-edit="p1"]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('Changed')
    await wrapper.get('[data-provider-name]').setValue('Provider')
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    expect(navigate).toHaveBeenCalledOnce()
    expect(decision(wrapper).props('open')).toBe(false)
    await wrapper.get('.editor-popover-close').trigger('click')
    expect(wrapper.find('.editor-overlay').exists()).toBe(false)
  })

  it('guards changed group names on navigation and supports cancel and discard', async () => {
    const wrapper = await settings({ catalogView: 'group' })
    await wrapper.get('[data-model-group-edit="g1"]').trigger('click')
    await wrapper.get('[data-model-group-name]').setValue('Renamed')
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    await flushPromises()
    expect(navigate).not.toHaveBeenCalled()
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'cancel')
    expect(wrapper.get('[data-model-group-name]').element).toHaveProperty('value', 'Renamed')
    wrapper.vm.requestNavigation(navigate)
    await choose(wrapper, 'discard')
    expect(navigate).toHaveBeenCalledOnce()
    expect(wrapper.get('[data-model-group-name]').element).toHaveProperty('value', 'Group')
  })

  it('treats membership as a set and detects checkbox changes without input-event bookkeeping', async () => {
    const wrapper = await settings({ catalogView: 'group' })
    await wrapper.get('[data-model-group-members]').trigger('click')
    const checkbox = wrapper.get('[data-model-group-members-form] input[type="checkbox"]')
    await checkbox.setValue(false)
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    await flushPromises()
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'cancel')
    await checkbox.setValue(true)
    wrapper.vm.requestNavigation(navigate)
    expect(navigate).toHaveBeenCalledOnce()
  })

  it('saves group membership before switching settings sections', async () => {
    const persist = vi.fn(async () => {})
    const wrapper = await settings({ catalogView: 'group', persistCatalog: persist })
    await wrapper.get('[data-model-group-members]').trigger('click')
    await wrapper.get('[data-model-group-members-form] input[type="checkbox"]').setValue(false)
    await wrapper.get('[data-settings-section="agents"]').trigger('click')
    expect(wrapper.find('[data-context-compaction-retained-steps]').exists()).toBe(false)
    await choose(wrapper, 'save')
    expect(persist).toHaveBeenCalledWith('set-model-group-members', { group_id: 'g1', model_ids: [] })
    expect(wrapper.find('[data-context-compaction-retained-steps]').exists()).toBe(true)
    expect(wrapper.find('.editor-overlay').exists()).toBe(false)
  })

  it('keeps the provider draft and destination unchanged after a failed save, then retries', async () => {
    const persist = vi.fn().mockRejectedValueOnce(new Error('Provider write failed')).mockResolvedValue(undefined)
    const wrapper = await settings({ persistCatalog: persist })
    await wrapper.get('[data-provider-edit="p1"]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('Renamed')
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    await choose(wrapper, 'save')
    expect(navigate).not.toHaveBeenCalled()
    expect(wrapper.get('[data-provider-name]').element).toHaveProperty('value', 'Renamed')
    expect(wrapper.get('.editor-error').text()).toBe('Provider write failed')
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'save')
    expect(navigate).toHaveBeenCalledOnce()
    expect(wrapper.find('.editor-overlay').exists()).toBe(false)
  })

  it('protects a provider draft from backdrop dismissal and editor replacement', async () => {
    const wrapper = await settings()
    await wrapper.get('[data-provider-edit="p1"]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('Draft')
    for (const type of ['pointerdown', 'pointerup']) {
      const event = new MouseEvent(type, { bubbles: true, button: 0 })
      Object.defineProperty(event, 'pointerId', { value: 1 })
      wrapper.get('.editor-overlay').element.dispatchEvent(event)
    }
    await flushPromises()
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'cancel')
    await wrapper.get('[data-model-create]').trigger('click')
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'discard')
    expect(wrapper.find('[data-model-form="create"]').exists()).toBe(true)
  })

  it('tracks custom select changes and closes an unchanged model editor without prompting', async () => {
    const wrapper = await settings()
    await wrapper.get('[data-model-edit="m1"]').trigger('click')
    const capability = wrapper.get('[data-model-form="update"]').findAllComponents(UiSelect).find((select: VueWrapper) => {
      const props = select.props() as { options: Array<{ value: string }> }
      return props.options.some(option => option.value === 'multimodal')
    })!
    capability.vm.$emit('update:modelValue', 'text')
    await flushPromises()
    await wrapper.get('.editor-popover-close').trigger('click')
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'cancel')
    capability.vm.$emit('update:modelValue', 'multimodal')
    await flushPromises()
    await wrapper.get('.editor-popover-close').trigger('click')
    expect(wrapper.find('.editor-overlay').exists()).toBe(false)
  })

  it('retains drafts while saving and navigates after an in-flight write succeeds', async () => {
    let resolveWrite!: () => void
    const persist = vi.fn(() => new Promise<void>(resolve => { resolveWrite = resolve }))
    const wrapper = await settings({ persistCatalog: persist })
    await wrapper.get('[data-provider-edit="p1"]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('Renamed')
    await wrapper.get('[data-provider-form="update"]').trigger('submit')
    expect(wrapper.find('.editor-overlay').exists()).toBe(true)
    expect(wrapper.get('.settings-editor-fields').attributes('disabled')).toBeDefined()
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    expect(navigate).not.toHaveBeenCalled()
    resolveWrite()
    await flushPromises()
    expect(navigate).toHaveBeenCalledOnce()
    expect(decision(wrapper).props('open')).toBe(false)
  })

  it('guards external controlled-section requests and leaves the current section on cancel', async () => {
    const wrapper = await settings({ activeSection: 'models', hideNav: true, catalogView: 'group' })
    await wrapper.get('[data-model-group-edit="g1"]').trigger('click')
    await wrapper.get('[data-model-group-name]').setValue('Draft')
    await wrapper.setProps({ activeSection: 'agents' })
    expect(wrapper.find('[data-context-compaction-retained-steps]').exists()).toBe(false)
    await choose(wrapper, 'cancel')
    wrapper.vm.requestSection('agents')
    await choose(wrapper, 'discard')
    expect(wrapper.find('[data-context-compaction-retained-steps]').exists()).toBe(true)
  })

  it('saving one configuration does not clear other drafts, including failed saves', async () => {
    const fixture = rpcFixture()
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'config.agents_md.set') throw new Error('Rules write failed')
      return fixture(method, params)
    })
    const wrapper = await settings({}, rpc)
    await wrapper.get('[data-settings-section="agents"]').trigger('click')
    await wrapper.get('textarea').setValue('# Changed rules')
    await wrapper.get('[data-context-compaction-retained-steps]').setValue('12')
    await wrapper.get('[data-context-compaction-save]').trigger('click')
    await flushPromises()
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    await choose(wrapper, 'save')
    expect(navigate).not.toHaveBeenCalled()
    expect(wrapper.get('textarea').element).toHaveProperty('value', '# Changed rules')
    expect(rpc.mock.calls.filter(([method, params]) => method === 'settings.update' && params?.namespace === 'core.contextCompaction')).toHaveLength(1)
    await choose(wrapper, 'discard')
    expect(wrapper.get('textarea').element).toHaveProperty('value', '# Saved rules')
    expect(wrapper.get('[data-context-compaction-retained-steps]').element).toHaveProperty('value', '12')
  })

  it('protects refresh, including context additions and an unsubmitted exclusion', async () => {
    const rpc = rpcFixture()
    const wrapper = await settings({}, rpc)
    await wrapper.get('[data-settings-section="agents"]').trigger('click')
    const context = wrapper.findAll('.setting-card').find(card => card.text().includes('全局上下文加载'))!
    await context.get('.btn--quiet').trigger('click')
    await context.get('.lc-row input').setValue('project.md')
    await context.get('input[placeholder="如 AGENTS.md / CONTEXT.md"]').setValue('secret.md')
    await wrapper.get('[data-settings-section="about"]').trigger('click')
    await choose(wrapper, 'save')
    expect(rpc).toHaveBeenCalledWith('config.load_context.set', expect.objectContaining({
      addition: [{ name: 'project.md', priority: 50, kind: 'system' }], except: ['secret.md'],
    }))
    await wrapper.get('[data-settings-section="agents"]').trigger('click')
    await wrapper.get('textarea').setValue('# Unsaved rules')
    const rules = wrapper.findAll('.setting-card')[0]
    const refresh = rules.findAll('button').find(button => button.text() === '刷新')!
    await refresh.trigger('click')
    expect(decision(wrapper).props('open')).toBe(true)
    await choose(wrapper, 'cancel')
    expect(wrapper.get('textarea').element).toHaveProperty('value', '# Unsaved rules')
  })

  it('protects network drafts when their child editor would be unmounted', async () => {
    const wrapper = await settings()
    await wrapper.get('[data-settings-section="general"]').trigger('click')
    await flushPromises()
    const proxy = wrapper.get('input[placeholder*="127.0.0.1"]')
    await proxy.setValue('http://changed:8080')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'cancel')
    expect(proxy.element).toHaveProperty('value', 'http://changed:8080')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'discard')
    await wrapper.get('[data-settings-section="general"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('input[placeholder*="127.0.0.1"]').element).toHaveProperty('value', 'http://original:8080')
  })

  it('does not prompt after restoring tool-mode values and saves changed modes before leaving', async () => {
    const rpc = rpcFixture()
    const wrapper = await settings({}, rpc)
    await wrapper.get('[data-settings-section="loadtools"]').trigger('click')
    await flushPromises()
    await wrapper.get('.mode-description-input').setValue('Changed')
    await wrapper.get('.mode-description-input').setValue('Saved mode')
    expect(wrapper.find('.loadtools-dirty').exists()).toBe(false)
    await wrapper.get('.mode-description-input').setValue('Changed')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'save')
    expect(rpc).toHaveBeenCalledWith('config.loadtools.set', { modes: { execute: { description: 'Changed', tools: ['read_file'] } } })
    expect(wrapper.find('[data-model-create]').exists()).toBe(true)
  })

  it('preserves an invalid tool-mode draft when save validation blocks navigation', async () => {
    const wrapper = await settings()
    await wrapper.get('[data-settings-section="loadtools"]').trigger('click')
    await flushPromises()
    await wrapper.get('.mode-name-input').setValue('')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'save')
    expect(decision(wrapper).props('open')).toBe(true)
    expect(wrapper.get('.mode-name-input').element).toHaveProperty('value', '')
    expect(wrapper.get('.skill-error').text()).toContain('不能为空')
  })

  it('saves independent sub-agent drafts without resetting the other fields', async () => {
    const rpc = rpcFixture()
    const wrapper = await settings({}, rpc)
    await wrapper.get('[data-settings-section="subagent"]').trigger('click')
    await flushPromises()
    const editor = wrapper.getComponent(CoreSubAgentEditor)
    editor.get('.mm-select').getComponent(UiSelect).vm.$emit('update:modelValue', 'model')
    editor.get('.delegation-strategy-select').getComponent(UiSelect).vm.$emit('update:modelValue', 'high')
    await editor.get('.guide-editor').setValue('# Changed guide')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'save')
    expect(rpc).toHaveBeenCalledWith('config.subagent.guide.set', { scope: 'global', content: '# Changed guide' })
    expect(rpc).toHaveBeenCalledWith('config.subagent.settings.set', { scope: 'global', settings: { default_multimodal_model: 'model' } })
    expect(rpc).toHaveBeenCalledWith('config.subagent.settings.set', { scope: 'global', settings: { delegation_strategy: 'high' } })
    expect(wrapper.find('[data-model-create]').exists()).toBe(true)
  })

  it('keeps project rules after a failed save and supports a guarded project section switch', async () => {
    const persist = vi.fn().mockResolvedValueOnce(false).mockResolvedValue(true)
    const wrapper = mount(CoreProjectSettings, {
      props: { project: { id: 'p1', name: 'Project', workRoot: 'E:/work', iconKey: 'folder', colorKey: 'gray' },
        theme: structuredClone(DEFAULT_THEME), requestRpc: rpcFixture(), projectNameDraft: 'Project', agentsContent: '# Saved',
        agentsLoading: false, agentsError: '', projectActionLoading: false, projectActionError: '', persistAgents: persist },
      global: { stubs: { Teleport: true } },
    })
    mounted.push(wrapper)
    await wrapper.get('textarea').setValue('# Draft')
    await wrapper.get('[data-settings-section="subagent"]').trigger('click')
    await choose(wrapper, 'save')
    expect(wrapper.findComponent(CoreSubAgentEditor).exists()).toBe(false)
    expect(wrapper.get('textarea').element).toHaveProperty('value', '# Draft')
    await choose(wrapper, 'save')
    expect(wrapper.findComponent(CoreSubAgentEditor).exists()).toBe(true)
    expect(persist).toHaveBeenNthCalledWith(2, '# Draft')
  })

  it('can save and close through both the settings close control and the host navigation guard', async () => {
    const navigate = vi.fn()
    const persist = vi.fn(async () => {})
    const wrapper = await settings({ persistCatalog: persist, onClose: () => wrapper.vm.requestNavigation(navigate) })
    await wrapper.get('[data-provider-edit="p1"]').trigger('click')
    await wrapper.get('[data-provider-name]').setValue('Renamed')
    await wrapper.get('.settings-entry').trigger('click')
    await choose(wrapper, 'save')
    expect(navigate).toHaveBeenCalledOnce()
    expect(persist).toHaveBeenCalledOnce()
    expect(decision(wrapper).props('open')).toBe(false)
  })

  it('retains a model editor after direct persistence failure and validates advanced JSON before saving', async () => {
    const persist = vi.fn().mockRejectedValue(new Error('Model write failed'))
    const wrapper = await settings({ persistCatalog: persist })
    await wrapper.get('[data-model-edit="m1"]').trigger('click')
    await wrapper.get('[data-model-display-name]').setValue('Draft model')
    await wrapper.get('[data-model-form="update"]').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[data-model-display-name]').element).toHaveProperty('value', 'Draft model')
    expect(wrapper.get('.editor-error').text()).toBe('Model write failed')
    const extra = wrapper.get('[data-model-form="update"] textarea[placeholder="{}"]')
    await extra.setValue('[]')
    const navigate = vi.fn()
    wrapper.vm.requestNavigation(navigate)
    await choose(wrapper, 'save')
    expect(navigate).not.toHaveBeenCalled()
    expect(persist).toHaveBeenCalledOnce()
    expect(decision(wrapper).props('error')).toContain('JSON 必须是对象')
  })

  it('keeps an invalid memory threshold and network draft when saving fails', async () => {
    const fixture = rpcFixture()
    const rpc = vi.fn(async (method: string, params?: Record<string, unknown>) => {
      if (method === 'settings.update' && params?.namespace === 'core.network') throw new Error('Invalid proxy')
      return fixture(method, params)
    })
    const wrapper = await settings({ commandShellPlatform: 'windows' }, rpc)
    await wrapper.get('[data-settings-section="general"]').trigger('click')
    await flushPromises()
    await wrapper.get('input[placeholder*="http://127.0.0.1"]').setValue('bad proxy')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'save')
    expect(decision(wrapper).props('error')).toBe('Invalid proxy')
    await choose(wrapper, 'cancel')
    expect(wrapper.get('input[placeholder*="http://127.0.0.1"]').element).toHaveProperty('value', 'bad proxy')
    await wrapper.get('input[placeholder*="http://127.0.0.1"]').setValue('http://original:8080')
    const threshold = wrapper.get('input[type="number"][min="0.5"]')
    await threshold.setValue('0.1')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'save')
    expect(decision(wrapper).props('error')).toContain('0.5')
    await choose(wrapper, 'cancel')
    const memoryCard = wrapper.findAll('.setting-card').find(card => card.find('input[min="0.5"]').exists())!
    await memoryCard.findAll('button')[0].trigger('click')
    await choose(wrapper, 'cancel')
    expect(threshold.element).toHaveProperty('value', '0.1')
    await threshold.setValue('4')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    expect(decision(wrapper).props('open')).toBe(false)
  })

  it('guards network refresh against changes in any network field', async () => {
    const wrapper = await settings()
    await wrapper.get('[data-settings-section="general"]').trigger('click')
    await flushPromises()
    const bypass = wrapper.get('input[placeholder*="localhost,"]')
    await bypass.setValue('*.internal')
    const proxyCard = wrapper.findAll('.setting-card').find(card => card.find('input[aria-label="HTTP 代理"]').exists())!
    await proxyCard.findAll('button')[0].trigger('click')
    await choose(wrapper, 'cancel')
    expect(bypass.element).toHaveProperty('value', '*.internal')
    await proxyCard.findAll('button')[0].trigger('click')
    await choose(wrapper, 'discard')
    expect(bypass.element).toHaveProperty('value', '')
  })

  it('validates role assignments without dropping the draft or switching sections', async () => {
    const rpc = rpcFixture()
    const wrapper = await settings({}, rpc)
    await wrapper.get('[data-settings-section="subagent"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-role-assignment-add]').trigger('click')
    await wrapper.get('[data-settings-section="models"]').trigger('click')
    await choose(wrapper, 'save')
    expect(decision(wrapper).props('open')).toBe(true)
    expect(wrapper.find('[data-role-assignment-row="0"]').exists()).toBe(true)
    expect(rpc).not.toHaveBeenCalledWith('config.subagent.settings.set', expect.anything())
    expect(decision(wrapper).props('error')).toBeTruthy()
  })
})

describe('draft guard sequencing', () => {
  it('keeps successful checkpoints clean when a later save fails, and does not replay them on retry', async () => {
    const saveFirst = vi.fn(async () => { first.accept() })
    const saveSecond = vi.fn().mockResolvedValueOnce(false).mockImplementation(async () => { second.accept() })
    const firstValue = ref('first'), secondValue = ref('second')
    let first!: ReturnType<typeof useSettingsDraft<string>>, second!: ReturnType<typeof useSettingsDraft<string>>
    let guard!: ReturnType<typeof createSettingsDraftGuard>
    const Child = defineComponent({ setup() {
      first = useSettingsDraft({ section: 's', label: () => 'First', read: () => firstValue.value, restore: value => { firstValue.value = value }, save: saveFirst })
      second = useSettingsDraft({ section: 's', label: () => 'Second', read: () => secondValue.value, restore: value => { secondValue.value = value }, save: saveSecond })
      return () => h('div')
    } })
    const wrapper = mount(defineComponent({ setup() { guard = createSettingsDraftGuard(); return () => h(Child) } }))
    mounted.push(wrapper)
    firstValue.value = 'changed first'; secondValue.value = 'changed second'
    const navigate = vi.fn()
    guard.requestNavigation(navigate)
    await guard.saveAndContinue()
    expect(first.dirty.value).toBe(false)
    expect(second.dirty.value).toBe(true)
    expect(navigate).not.toHaveBeenCalled()
    await guard.saveAndContinue()
    expect(saveFirst).toHaveBeenCalledOnce()
    expect(saveSecond).toHaveBeenCalledTimes(2)
    expect(navigate).toHaveBeenCalledOnce()
  })
})
