import { describe, expect, it } from 'vitest'
import {
  readSessionComposerControls,
  sessionComposerParams,
} from '../src/composer/sessionComposer'

describe('sessionComposer', () => {
  it('reads the stored group and prefers it over legacy keys', () => {
    const controls = readSessionComposerControls(
      {
        model_id: 'legacy-model',
        composer_state: {
          active_mode: 'consider',
          model_id: 'model-b',
          reasoning_level: 'high',
          shallow_thinking_enabled: true,
          permission_preset: 'auto',
        },
        runtime_preferences: { permission_preset: 'ask' },
      },
      { defaultPermissionPreset: 'ask', availableModelIds: ['model-a', 'model-b'] },
    )

    expect(controls).toEqual({
      activeMode: 'consider',
      modelId: 'model-b',
      thinkingMode: 'high',
      shallowThinkingEnabled: true,
      permissionPreset: 'auto',
    })
  })

  it('falls back to legacy model and session permissions for old sessions', () => {
    const controls = readSessionComposerControls(
      {
        model_id: 'model-a',
        runtime_preferences: { permission_preset: 'full_access' },
      },
      { defaultPermissionPreset: 'ask', availableModelIds: ['model-a'] },
    )

    expect(controls.modelId).toBe('model-a')
    expect(controls.permissionPreset).toBe('full_access')
    expect(controls.thinkingMode).toBeUndefined()
    expect(controls.activeMode).toBeUndefined()
  })

  it('drops a stored model that is no longer installed', () => {
    const controls = readSessionComposerControls(
      { composer_state: { model_id: 'removed-model' } },
      { defaultPermissionPreset: 'ask', availableModelIds: ['model-a'] },
    )

    expect(controls.modelId).toBe('')
  })

  it('builds the RPC params with apply_to_running', () => {
    const params = sessionComposerParams('thread-1', {
      modelId: 'model-a',
      thinkingMode: 'light',
      shallowThinkingEnabled: false,
      activeMode: 'execute',
      permissionPreset: 'ask',
    })

    expect(params).toEqual({
      thread_id: 'thread-1',
      active_mode: 'execute',
      model_id: 'model-a',
      reasoning_level: 'light',
      shallow_thinking_enabled: false,
      permission_preset: 'ask',
      apply_to_running: true,
    })
  })
})
