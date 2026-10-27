import { normalizeCorePermissionPreset } from '@/composer/execution.ts'
import type { CoreComposerControls } from '@/composables/useCoreExecutionControlsState.ts'

/**
 * Session-scoped Composer parameter group helpers.
 *
 * user:“架构调整，输入框的信息作为‘输入参数组’按会话持久化保存包括模式权限模型思考以及输入信息”
 * +(读写保持纯函数，宿主只负责发 RPC 和更新会话列表，便于测试与复用)。
 */

export interface ReadSessionComposerOptions {
  defaultPermissionPreset: string
  availableModelIds?: readonly string[]
}

export function readSessionComposerControls(
  metadata: Record<string, unknown> | null | undefined,
  options: ReadSessionComposerOptions,
): Partial<CoreComposerControls> {
  const source = metadata || {}
  const group: Partial<CoreComposerControls> = {}
  const stored = source.composer_state
  const storedGroup = stored && typeof stored === 'object' && !Array.isArray(stored)
    ? stored as Record<string, unknown>
    : null
  if (storedGroup) {
    if (typeof storedGroup.model_id === 'string') group.modelId = storedGroup.model_id
    if (typeof storedGroup.reasoning_level === 'string') {
      group.thinkingMode = storedGroup.reasoning_level as CoreComposerControls['thinkingMode']
    }
    if (typeof storedGroup.shallow_thinking_enabled === 'boolean') {
      group.shallowThinkingEnabled = storedGroup.shallow_thinking_enabled
    }
    if (typeof storedGroup.active_mode === 'string') group.activeMode = storedGroup.active_mode
    if (typeof storedGroup.permission_preset === 'string') {
      group.permissionPreset = storedGroup.permission_preset as CoreComposerControls['permissionPreset']
    }
  }

  // Legacy sessions predate the group: fall back to the keys each field used.
  if (group.modelId === undefined && typeof source.model_id === 'string') {
    group.modelId = source.model_id
  }
  if (group.permissionPreset === undefined) {
    const preferences = source.runtime_preferences
    const preset = preferences && typeof preferences === 'object' && !Array.isArray(preferences)
      ? (preferences as Record<string, unknown>).permission_preset
      : undefined
    group.permissionPreset = normalizeCorePermissionPreset(
      preset ?? options.defaultPermissionPreset,
    )
  }

  // A model that is no longer installed must fall back to the scene default
  // instead of leaking the previous session's model into this one.
  if (typeof group.modelId === 'string' && group.modelId) {
    const available = options.availableModelIds
    if (available && !available.includes(group.modelId)) group.modelId = ''
  }
  return group
}

export function sessionComposerParams(
  sessionId: string,
  controls: CoreComposerControls,
): Record<string, unknown> {
  return {
    thread_id: sessionId,
    active_mode: controls.activeMode,
    model_id: controls.modelId,
    reasoning_level: controls.thinkingMode,
    shallow_thinking_enabled: controls.shallowThinkingEnabled,
    permission_preset: controls.permissionPreset,
    // The backend persists the group and, when a turn is running, applies the
    // live dimensions at its next step.
    apply_to_running: true,
  }
}
