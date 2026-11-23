import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { nextTick, ref } from 'vue'
import CoreRunModeCapsule from '../src/components/CoreRunModeCapsule.vue'
import {
  CORE_RUN_MODES,
  isHiddenCoreRunMode,
  normalizeCoreRunMode,
} from '../src/composer/runMode'
import {
  migrateSessionRunModeMetadata,
  readSessionComposerControls,
} from '../src/composer/sessionComposer'
import {
  CORE_EXECUTION_CONTROLS_STORAGE_KEYS,
  useCoreExecutionControlsState,
} from '../src/composables/useCoreExecutionControlsState'

// user:“把智能模式隐藏掉，从下个版本开始，仅聊天和工作模式”+(先立验收：选择器只渲染
// 聊天/工作；读入历史 auto 的会话按工作显示，并把本地存储与会话存档都写成 work；
// 后端仍然接受 auto，这条只做兼容说明，不改后端)。

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    data,
    getItem: (key: string) => (data.has(key) ? String(data.get(key)) : null),
    setItem: (key: string, value: string) => { data.set(key, value) },
  }
}

function controlsState(storage = memoryStorage()) {
  const models = ref([{ id: 'model-1', provider_id: 'provider-1', thinking_supported: true }])
  const state = useCoreExecutionControlsState({
    models,
    providers: ref([{ id: 'provider-1', name: 'Provider 1' }]),
    defaultModel: ref(models.value[0]),
    storage,
    initial: { thinkingMode: 'high' },
  })
  return { state, storage }
}

describe('hidden auto run mode', () => {
  it('offers only chat and work as run modes', () => {
    expect([...CORE_RUN_MODES]).toEqual(['chat', 'work'])
    expect(normalizeCoreRunMode('auto')).toBe('work')
    expect(normalizeCoreRunMode('superagent')).toBe('work')
    expect(normalizeCoreRunMode('consider')).toBe('chat')
    expect(normalizeCoreRunMode('execute')).toBe('work')
    expect(isHiddenCoreRunMode('auto')).toBe(true)
    expect(isHiddenCoreRunMode('superagent')).toBe(true)
    expect(isHiddenCoreRunMode('work')).toBe(false)
  })

  it('renders the capsule with exactly two options and never an auto pill', () => {
    const wrapper = mount(CoreRunModeCapsule, { props: { modelValue: 'work' } })
    const pills = wrapper.findAll('[data-run-mode-option]')
    expect(pills.map(pill => pill.attributes('data-run-mode-option'))).toEqual(['chat', 'work'])
    expect(wrapper.text()).not.toContain('智能')
    wrapper.unmount()
  })

  it('shows a legacy auto session as work instead of rendering an auto pill', () => {
    const wrapper = mount(CoreRunModeCapsule, { props: { modelValue: 'auto' } })
    const pills = wrapper.findAll('[data-run-mode-option]')
    expect(pills.map(pill => pill.attributes('data-run-mode-option'))).toEqual(['chat', 'work'])
    expect(wrapper.get('[data-run-mode-option="work"]').classes()).toContain('is-active')
    wrapper.unmount()
  })

  it('rewrites a stored auto into work and keeps the payload on work', async () => {
    const storage = memoryStorage({ [CORE_EXECUTION_CONTROLS_STORAGE_KEYS.activeMode]: 'auto' })
    const { state } = controlsState(storage)

    expect(state.activeMode.value).toBe('work')
    expect(storage.data.get(CORE_EXECUTION_CONTROLS_STORAGE_KEYS.activeMode)).toBe('work')
    expect(state.turnOptions()).toMatchObject({ active_mode: 'work' })
    await nextTick()
  })

  it('restores a session stored as auto as work and persists work locally', async () => {
    const { state, storage } = controlsState()
    state.restoreControls({ activeMode: 'auto' })

    expect(state.controls().activeMode).toBe('work')
    expect(storage.data.get(CORE_EXECUTION_CONTROLS_STORAGE_KEYS.activeMode)).toBe('work')
    await nextTick()
  })

  it('keeps the raw stored session mode readable so the host can migrate it', () => {
    const controls = readSessionComposerControls(
      { composer_state: { active_mode: 'auto', model_id: 'model-1' } },
      { defaultPermissionPreset: 'ask', availableModelIds: ['model-1'] },
    )
    // 宿主需要看到"存档里确实是 auto"，才能决定要发一次迁移写入。
    expect(controls.activeMode).toBe('auto')
  })

  it('builds the migrated session metadata for an archived auto session', () => {
    const metadata = migrateSessionRunModeMetadata({
      composer_state: { active_mode: 'auto', model_id: 'model-1', reasoning_level: 'high' },
      runtime_preferences: { permission_preset: 'ask' },
    })

    expect(metadata).not.toBeNull()
    expect(metadata!.composer_state).toEqual({
      active_mode: 'work',
      model_id: 'model-1',
      reasoning_level: 'high',
    })
    expect(metadata!.runtime_preferences).toEqual({ permission_preset: 'ask' })
  })

  it('leaves sessions that already use a visible mode untouched', () => {
    expect(migrateSessionRunModeMetadata({
      composer_state: { active_mode: 'chat' },
    })).toBeNull()
    expect(migrateSessionRunModeMetadata({ composer_state: {} })).toBeNull()
    expect(migrateSessionRunModeMetadata({})).toBeNull()
    expect(migrateSessionRunModeMetadata(null)).toBeNull()
  })
})
