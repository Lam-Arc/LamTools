<template>
  <section class="settings-panel settings-panel--editor">
    <header class="settings-title">
      <h1>Sub agent</h1>
      <p>配置 sub_agent 调用提示词，指导主 Agent 如何与何时委派子 Agent（model/mode 等）。</p>
    </header>

    <p v-if="error" class="skill-error">{{ error }}</p>

    <div class="settings-surface settings-surface--stack">
    <!-- Default multimodal model picker -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted">默认多模态解析模型</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="settingsLoading || settingsSaving" @click="saveSettings">保存</button>
        </div>
      </div>
      <UiSelect
        :model-value="defaultMmModel"
        class="mm-select"
        :options="mmModelOptions"
        :disabled="settingsLoading"
        aria-label="默认多模态解析模型"
        @update:model-value="defaultMmModel = $event"
      />
      <p class="hook-meta">
        当主模型为文本模型且需要理解图片/视频等附件时，能力提示词会引导主 Agent 用此模型委派 sub_agent 查看。仅显示已声明 <strong>多模态</strong> 能力的模型。保存到 <code>{{ settingsTargetPath }}</code>。
      </p>
    </article>

    <!-- Sub-agent delegation strategy -->
    <article class="setting-card delegation-strategy-card">
      <div class="subhead">
        <div>
          <strong>子代理委派策略</strong>
          <p class="delegation-strategy-summary">{{ delegationStrategySource }}</p>
        </div>
        <div class="subhead-actions">
          <button
            class="text-btn"
            type="button"
            :disabled="settingsLoading || delegationStrategySaving"
            data-delegation-strategy-save
            @click="saveDelegationStrategy"
          >{{ delegationStrategySaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
      <div class="delegation-strategy-body">
        <UiSelect
          v-model="delegationStrategy"
          class="delegation-strategy-select"
          :options="availableDelegationStrategyOptions"
          :disabled="settingsLoading || delegationStrategySaving"
          aria-label="子代理委派策略"
        />
        <p class="delegation-strategy-description">
          {{ delegationStrategyDescription }}
        </p>
      </div>
      <p class="hook-meta delegation-strategy-scope">
        {{ delegationStrategyScopeDescription }}
      </p>
    </article>

    <!-- Role assignment editor -->
    <article class="setting-card role-assignment-card">
      <div class="subhead">
        <div>
          <strong>角色分配</strong>
          <p class="role-assignment-summary">{{ roleAssignmentDescription }}</p>
        </div>
        <div class="subhead-actions">
          <button
            class="text-btn"
            type="button"
            :disabled="settingsLoading || roleAssignmentsSaving"
            data-role-assignment-add
            @click="addRoleAssignment"
          >新增</button>
          <button
            class="text-btn"
            type="button"
            :disabled="settingsLoading || roleAssignmentsSaving"
            data-role-assignment-save
            @click="saveRoleAssignments"
          >{{ roleAssignmentsSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>

      <p v-if="roleAssignmentError" class="role-assignment-error" role="alert">
        {{ roleAssignmentError }}
      </p>

      <div class="role-assignment-labels" aria-hidden="true">
        <span>任务类型</span>
        <span>类型</span>
        <span>建议模型</span>
        <span>最低思考强度</span>
        <span>最高思考强度</span>
        <span></span>
      </div>

      <TransitionGroup
        name="role-assignment"
        tag="div"
        class="role-assignment-list"
        data-role-assignment-list
      >
        <div
          v-for="(assignment, index) in roleAssignments"
          :key="assignment.key"
          class="role-assignment-row"
          :data-role-assignment-row="index"
        >
          <label class="role-assignment-field role-assignment-field--task">
            <span class="role-assignment-mobile-label">任务类型</span>
            <input
              v-model="assignment.task_type"
              class="role-assignment-input"
              type="text"
              autocomplete="off"
              :disabled="settingsLoading || roleAssignmentsSaving"
              :aria-label="`任务类型 ${index + 1}`"
              placeholder="例如：代码审查"
              @input="roleAssignmentError = ''"
            />
          </label>
          <label class="role-assignment-field">
            <span class="role-assignment-mobile-label">类型</span>
            <UiSelect
              v-model="assignment.type"
              :options="roleTypeOptions"
              :disabled="settingsLoading || roleAssignmentsSaving"
              :aria-label="`类型 ${index + 1}`"
            />
          </label>
          <label class="role-assignment-field role-assignment-field--model">
            <span class="role-assignment-mobile-label">建议模型</span>
            <UiSelect
              v-model="assignment.model"
              :options="modelOptionsFor(assignment.model)"
              :disabled="settingsLoading || roleAssignmentsSaving"
              :aria-label="`建议模型 ${index + 1}`"
              placeholder="选择模型"
            />
          </label>
          <label class="role-assignment-field">
            <span class="role-assignment-mobile-label">最低思考强度</span>
            <UiSelect
              v-model="assignment.reasoning_min"
              :options="reasoningOptions"
              :disabled="settingsLoading || roleAssignmentsSaving"
              :aria-label="`最低思考强度 ${index + 1}`"
            />
          </label>
          <label class="role-assignment-field">
            <span class="role-assignment-mobile-label">最高思考强度</span>
            <UiSelect
              v-model="assignment.reasoning_max"
              :options="reasoningOptions"
              :disabled="settingsLoading || roleAssignmentsSaving"
              :aria-label="`最高思考强度 ${index + 1}`"
            />
          </label>
          <button
            class="text-btn danger role-assignment-remove"
            type="button"
            :disabled="settingsLoading || roleAssignmentsSaving"
            :aria-label="`删除角色分配 ${index + 1}`"
            @click="removeRoleAssignment(index)"
          >删除</button>
        </div>
      </TransitionGroup>

      <button
        v-if="roleAssignments.length === 0"
        class="add-row role-assignment-empty"
        type="button"
        :disabled="settingsLoading || roleAssignmentsSaving"
        @click="addRoleAssignment"
      >新增第一条角色分配</button>

      <p class="hook-meta">
        规则会统一追加到 sub_agent 调用纪律之后。任务类型匹配时，为主 Agent 提供建议的子代理类型、模型与思考强度范围。
      </p>
    </article>

    <!-- Guide editor -->
    <article class="setting-card">
      <div class="subhead">
        <span class="muted">{{ loading ? '加载中…' : statusLabel }}</span>
        <div class="subhead-actions">
          <button class="text-btn" type="button" :disabled="loading" @click="fetchGuide">刷新</button>
          <button class="text-btn" type="button" :disabled="loading || saving" @click="saveGuide">保存</button>
        </div>
      </div>

      <textarea
        v-model="draft"
        class="guide-editor"
        rows="18"
        spellcheck="false"
        :disabled="loading || saving"
        placeholder="# Sub-agent 委派指南&#10;在此编写自然语言指令，将注入到主 Agent 系统提示词中…"
      />
      <p class="hook-meta">
        {{ guideDescription }}
      </p>
    </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import UiSelect from './UiSelect.vue'
import type { CoreSettingsModel } from './CoreSettings.vue'
import { CORE_THINKING_LABELS, type CoreThinkingMode } from '../composer/execution'

type RoleAssignmentType = 'consider' | 'execute'
type DelegationStrategy = 'forbidden' | 'low' | 'medium' | 'high'
type DelegationStrategySelection = DelegationStrategy | 'inherit'

interface RoleAssignmentDraft {
  key: number
  task_type: string
  type: RoleAssignmentType
  model: string
  reasoning_min: CoreThinkingMode
  reasoning_max: CoreThinkingMode
}

interface RoleAssignmentPayload {
  task_type: string
  type: RoleAssignmentType
  model: string
  reasoning_min: CoreThinkingMode
  reasoning_max: CoreThinkingMode
}

const props = withDefaults(defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  models?: CoreSettingsModel[]
  /** Config scope this editor reads/writes. 'global' (default) edits ~/.lam/core/config;
   *  'project' edits {workRoot}/.lam/config and falls back to global/builtin on read. */
  scope?: 'global' | 'project'
  /** Required when scope === 'project'. */
  workRoot?: string
}>(), {
  scope: 'global',
  workRoot: '',
})

// ── Guide state ──
const draft = ref('')
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const isBuiltin = ref(true)

/** Merge scope + work_root into an RPC params object so the backend reads/writes
 *  the correct tier (global → ~/.lam/core/config, project → {workRoot}/.lam/config). */
function withScope<T extends Record<string, unknown>>(extra: T): T {
  return { scope: props.scope, ...(props.workRoot ? { work_root: props.workRoot } : {}), ...extra } as T
}

const statusLabel = computed(() => {
  if (saving.value) return '保存中…'
  if (props.scope === 'project') {
    return isBuiltin.value
      ? '当前来源：继承全局 / 内置默认（未配置项目级 guide）'
      : '当前来源：项目配置'
  }
  return isBuiltin.value ? '当前来源：内置默认（未配置全局 guide）' : '当前来源：全局配置'
})

const settingsTargetPath = computed(() =>
  props.scope === 'project'
    ? `${props.workRoot || '(项目根)'}/.lam/config/subagent/settings.json`
    : '~/.lam/core/config/subagent/settings.json',
)

const guideDescription = computed(() => {
  if (props.scope === 'project') {
    return `保存到项目配置 ${props.workRoot || '(项目根)'}/.lam/config/subagent/guide.md。留空保存则移除项目级配置，回退到继承的全局 / 内置默认。CLI：core subagent guide show/set/edit --scope project --work-root <root>`
  }
  return '保存到全局配置 ~/.lam/core/config/subagent/guide.md。项目级配置请在项目设置内编辑。留空保存则恢复为内置默认。CLI：core subagent guide show/set/edit --scope global'
})

async function fetchGuide() {
  loading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.subagent.guide.get', withScope({}))
    draft.value = String(result.content ?? '')
    isBuiltin.value = result.is_builtin !== false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function saveGuide() {
  saving.value = true
  error.value = ''
  try {
    await props.requestRpc('config.subagent.guide.set', withScope({
      content: draft.value,
    }))
    await fetchGuide()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    saving.value = false
  }
}

// ── Default multimodal model state ──
const defaultMmModel = ref('')
const settingsLoading = ref(true)
const settingsSaving = ref(false)
const delegationStrategySaving = ref(false)
const delegationStrategy = ref<DelegationStrategySelection>('medium')
const effectiveDelegationStrategy = ref<DelegationStrategy>('medium')
const inheritedDelegationStrategy = ref<DelegationStrategy>('medium')
const delegationStrategyInherited = ref(true)
const roleAssignmentsSaving = ref(false)
const roleAssignmentError = ref('')
const roleAssignments = ref<RoleAssignmentDraft[]>([])
const effectiveRoleAssignments = ref<RoleAssignmentPayload[]>([])
const roleAssignmentsInherited = ref(false)
let nextRoleAssignmentKey = 1

const roleTypeOptions = [
  { value: 'consider', label: 'consider' },
  { value: 'execute', label: 'execute' },
]

const delegationStrategyOptions: Array<{ value: DelegationStrategy; label: string }> = [
  { value: 'forbidden', label: '禁止' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中（默认）' },
  { value: 'high', label: '高' },
]

const delegationStrategyLabels: Record<DelegationStrategy, string> = {
  forbidden: '禁止',
  low: '低',
  medium: '中',
  high: '高',
}

const delegationStrategyDescriptions: Record<DelegationStrategy, string> = {
  forbidden: '禁止委派子代理。',
  low: '仅在大范围调查、探索时委派子代理。',
  medium: '保持当前委派策略。',
  high: '必须先制定计划并由用户确认；确认后立即生成高中心化 Checklist，尽可能使用多个子代理并行推进，主 Agent 负责决策指挥、任务分配、依赖协调、冲突调解、结果整合与最终验收。',
}

const availableDelegationStrategyOptions = computed(() => {
  if (props.scope !== 'project') return delegationStrategyOptions
  return [
    {
      value: 'inherit',
      label: `继承全局（当前：${delegationStrategyLabels[inheritedDelegationStrategy.value]}）`,
    },
    ...delegationStrategyOptions,
  ]
})

const reasoningLevels: CoreThinkingMode[] = ['off', 'light', 'medium', 'high', 'xhigh', 'max']
const reasoningOptions = reasoningLevels.map(value => ({
  value,
  label: `${value}（${CORE_THINKING_LABELS[value]}）`,
}))

const multimodalModels = computed(() =>
  (props.models ?? []).filter(m => m.capability === 'multimodal')
)

const mmModelOptions = computed(() => [
  { value: '', label: `未配置（使用内置兜底：${fallbackLabel.value}）` },
  ...multimodalModels.value.map(m => ({
    value: m.display_name || m.model_id || m.id,
    label: m.display_name || m.model_id || m.id,
  })),
])

const roleModelOptions = computed(() => {
  const seen = new Set<string>()
  return (props.models ?? []).flatMap(model => {
    const modelId = String(model.model_id ?? '').trim()
    if (!modelId || seen.has(modelId)) return []
    seen.add(modelId)
    const displayName = String(model.display_name ?? '').trim()
    return [{
      value: modelId,
      label: displayName && displayName !== modelId ? `${displayName} · ${modelId}` : modelId,
    }]
  })
})

const roleAssignmentDescription = computed(() => {
  if (props.scope === 'project') {
    const effectiveCount = effectiveRoleAssignments.value.length
    if (roleAssignmentsInherited.value) {
      return `当前没有项目覆盖，沿用全局基线；同名任务类型新增项目规则后将由项目覆盖。当前生效 ${effectiveCount} 条。`
    }
    return `全局规则作为基线；这里只编辑项目覆盖，同名任务类型以项目规则为准。当前合并后 ${effectiveCount} 条。`
  }
  return '全局基线适用于所有项目；项目可按同名任务类型覆盖。'
})

const delegationStrategySource = computed(() => {
  const effectiveLabel = delegationStrategyLabels[effectiveDelegationStrategy.value]
  if (props.scope === 'project') {
    return delegationStrategyInherited.value
      ? `当前继承全局有效策略：${effectiveLabel}`
      : `当前项目覆盖：${effectiveLabel}`
  }
  return delegationStrategyInherited.value
    ? `当前使用内置默认：${effectiveLabel}`
    : `当前全局基线：${effectiveLabel}`
})

const delegationStrategyDescription = computed(() => {
  if (delegationStrategy.value === 'inherit') {
    return `继承全局策略：${delegationStrategyDescriptions[inheritedDelegationStrategy.value]}`
  }
  return delegationStrategyDescriptions[delegationStrategy.value]
})

const delegationStrategyScopeDescription = computed(() => {
  if (props.scope === 'project') {
    if (delegationStrategy.value === 'inherit') {
      return delegationStrategyInherited.value
        ? '当前项目没有本地覆盖。'
        : '保存后将移除当前项目覆盖，恢复继承全局策略。'
    }
    return delegationStrategyInherited.value
      ? '项目尚未配置覆盖；选择策略并保存后，仅写入当前项目。'
      : `保存到项目配置 ${props.workRoot || '(项目根)'}/.lam/config/subagent/settings.json。`
  }
  return '保存为所有项目的全局基线；项目可单独覆盖。'
})

function parseDelegationStrategy(value: unknown, fallback: DelegationStrategy = 'medium'): DelegationStrategy {
  return value === 'forbidden' || value === 'low' || value === 'medium' || value === 'high'
    ? value
    : fallback
}

function modelOptionsFor(currentModel: string) {
  if (!currentModel || roleModelOptions.value.some(option => option.value === currentModel)) {
    return roleModelOptions.value
  }
  return [{ value: currentModel, label: `${currentModel}（当前配置）` }, ...roleModelOptions.value]
}

function isRoleAssignmentType(value: unknown): value is RoleAssignmentType {
  return value === 'consider' || value === 'execute'
}

function isReasoningLevel(value: unknown): value is CoreThinkingMode {
  return reasoningLevels.includes(value as CoreThinkingMode)
}

function parseReasoningLevel(value: unknown, fallback: CoreThinkingMode): CoreThinkingMode {
  if (value === 'xh') return 'xhigh'
  return isReasoningLevel(value) ? value : fallback
}

function roleTaskTypeKey(value: string): string {
  // Upper-then-lower handles Unicode case expansions such as ß → SS → ss,
  // matching the backend's casefold semantics more closely than toLowerCase().
  return value.trim().toUpperCase().toLowerCase()
}

function parseRoleAssignments(value: unknown): RoleAssignmentPayload[] {
  if (!Array.isArray(value)) return []
  return value
    .filter(item => item && typeof item === 'object')
    .map(item => {
      const record = item as Record<string, unknown>
      return {
        task_type: String(record.task_type ?? ''),
        type: isRoleAssignmentType(record.type) ? record.type : 'consider',
        model: String(record.model ?? ''),
        reasoning_min: parseReasoningLevel(record.reasoning_min, 'off'),
        reasoning_max: parseReasoningLevel(record.reasoning_max, 'max'),
      }
    })
}

function toRoleAssignmentDraft(assignment: RoleAssignmentPayload): RoleAssignmentDraft {
  return { key: nextRoleAssignmentKey++, ...assignment }
}

function addRoleAssignment() {
  const firstModel = roleModelOptions.value[0]?.value ?? ''
  roleAssignments.value.push({
    key: nextRoleAssignmentKey++,
    task_type: '',
    type: 'consider',
    model: firstModel,
    reasoning_min: 'off',
    reasoning_max: 'max',
  })
  roleAssignmentError.value = ''
}

function removeRoleAssignment(index: number) {
  roleAssignments.value.splice(index, 1)
  roleAssignmentError.value = ''
}

function validatedRoleAssignments(): RoleAssignmentPayload[] | null {
  const normalized = roleAssignments.value.map(assignment => ({
    task_type: assignment.task_type.trim(),
    type: assignment.type,
    model: assignment.model.trim(),
    reasoning_min: assignment.reasoning_min,
    reasoning_max: assignment.reasoning_max,
  }))
  const seen = new Set<string>()
  for (let index = 0; index < normalized.length; index += 1) {
    const assignment = normalized[index]
    if (!assignment.task_type) {
      roleAssignmentError.value = `第 ${index + 1} 条角色分配的任务类型不能为空。`
      return null
    }
    const taskKey = roleTaskTypeKey(assignment.task_type)
    if (seen.has(taskKey)) {
      roleAssignmentError.value = `任务类型“${assignment.task_type}”重复，请保留一条。`
      return null
    }
    seen.add(taskKey)
    if (!assignment.model) {
      roleAssignmentError.value = `第 ${index + 1} 条角色分配必须选择建议模型。`
      return null
    }
    if (reasoningLevels.indexOf(assignment.reasoning_min) > reasoningLevels.indexOf(assignment.reasoning_max)) {
      roleAssignmentError.value = `第 ${index + 1} 条角色分配的最低思考强度不能高于最高思考强度。`
      return null
    }
  }
  return normalized
}

/** Built-in fallback when no default_multimodal_model is configured: the first
 *  multimodal model by model_id — same ordering as the backend ModelStore. */
const fallbackMultimodalModel = computed(() =>
  [...(props.models ?? [])]
    .filter(m => m.capability === 'multimodal')
    .sort((a, b) => String(a.model_id || a.id || '').localeCompare(String(b.model_id || b.id || '')))[0] ?? null,
)

const fallbackLabel = computed(() => {
  const m = fallbackMultimodalModel.value
  if (!m) return '无多模态模型'
  return m.display_name || m.model_id || m.id
})

async function fetchSettings(options: {
  preserveDefaultMm?: boolean
  preserveDelegationStrategy?: boolean
  preserveRoleAssignments?: boolean
} = {}) {
  settingsLoading.value = true
  error.value = ''
  try {
    const result = await props.requestRpc('config.subagent.settings.get', withScope({}))
    const settings = result.settings as Record<string, unknown> | undefined
    if (!options.preserveDefaultMm) {
      defaultMmModel.value = String(settings?.default_multimodal_model ?? '')
    }
    const effectiveStrategy = parseDelegationStrategy(
      result.effective_delegation_strategy,
      parseDelegationStrategy(settings?.delegation_strategy),
    )
    effectiveDelegationStrategy.value = effectiveStrategy
    inheritedDelegationStrategy.value = parseDelegationStrategy(
      result.global_delegation_strategy ?? result.inherited_delegation_strategy,
      effectiveStrategy,
    )
    delegationStrategyInherited.value = result.delegation_strategy_inherited === true
    if (!options.preserveDelegationStrategy) {
      delegationStrategy.value = props.scope === 'project' && delegationStrategyInherited.value
        ? 'inherit'
        : parseDelegationStrategy(settings?.delegation_strategy, effectiveStrategy)
    }
    if (!options.preserveRoleAssignments) {
      roleAssignments.value = parseRoleAssignments(settings?.role_assignments).map(toRoleAssignmentDraft)
      roleAssignmentError.value = ''
    }
    effectiveRoleAssignments.value = parseRoleAssignments(result.effective_role_assignments)
    roleAssignmentsInherited.value = result.role_assignments_inherited === true
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    settingsLoading.value = false
  }
}

async function saveRoleAssignments() {
  const normalized = validatedRoleAssignments()
  if (!normalized) return
  roleAssignmentsSaving.value = true
  roleAssignmentError.value = ''
  try {
    await props.requestRpc('config.subagent.settings.set', withScope({
      settings: { role_assignments: normalized },
    }))
    await fetchSettings({ preserveDefaultMm: true, preserveDelegationStrategy: true })
  } catch (e) {
    roleAssignmentError.value = e instanceof Error ? e.message : String(e)
  } finally {
    roleAssignmentsSaving.value = false
  }
}

async function saveDelegationStrategy() {
  delegationStrategySaving.value = true
  error.value = ''
  try {
    await props.requestRpc('config.subagent.settings.set', withScope({
      settings: {
        delegation_strategy: props.scope === 'project' && delegationStrategy.value === 'inherit'
          ? null
          : delegationStrategy.value,
      },
    }))
    await fetchSettings({ preserveDefaultMm: true, preserveRoleAssignments: true })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    delegationStrategySaving.value = false
  }
}

async function saveSettings() {
  settingsSaving.value = true
  error.value = ''
  try {
    await props.requestRpc('config.subagent.settings.set', withScope({
      settings: { default_multimodal_model: defaultMmModel.value },
    }))
    await fetchSettings({ preserveDelegationStrategy: true, preserveRoleAssignments: true })
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    settingsSaving.value = false
  }
}

onMounted(() => {
  fetchGuide()
  fetchSettings()
})
</script>

<style scoped>
.guide-editor {
  width: 100%;
  min-height: 320px;
  margin-top: 10px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 9px;
  font-family: var(--font-mono);
  font-size: 13px;
  resize: vertical;
}

.mm-select {
  width: 100%;
  max-width: 400px;
  margin-top: 8px;
}

.mm-select :deep(.ui-select-trigger) {
  min-height: 34px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  font-size: 13px;
}

.subhead-actions {
  display: flex;
  gap: 6px;
}

.delegation-strategy-card {
  --text: var(--settings-main-text, var(--theme-main-text));
  gap: var(--space-3);
}

.delegation-strategy-card .subhead {
  align-items: start;
}

.delegation-strategy-summary {
  margin: var(--space-1) 0 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  line-height: 1.5;
}

.delegation-strategy-body {
  display: grid;
  grid-template-columns: minmax(0, 320px) minmax(0, 1fr);
  gap: var(--space-3);
  align-items: start;
}

.delegation-strategy-select {
  width: 100%;
  color: var(--settings-control-text, var(--theme-control-text));
  font-size: 13px;
}

.delegation-strategy-select :deep(.ui-select-menu) {
  width: 100%;
  min-width: 0;
}

.delegation-strategy-description {
  min-height: 32px;
  margin: 0;
  border-radius: var(--radius-sm);
  background: var(--theme-main-subtle-background);
  color: color-mix(in srgb, var(--text) 65%, transparent);
  padding: var(--space-2) var(--space-3);
  display: flex;
  align-items: center;
  font-size: 12px;
  line-height: 1.5;
}

.delegation-strategy-scope {
  margin: 0;
}

.role-assignment-card {
  --text: var(--settings-main-text, var(--theme-main-text));
}

.role-assignment-card .subhead {
  align-items: start;
}

.role-assignment-summary {
  margin: var(--space-1) 0 0;
  color: color-mix(in srgb, var(--text) 65%, transparent);
  font-size: 12px;
  line-height: 1.5;
}

.role-assignment-labels,
.role-assignment-row {
  display: grid;
  grid-template-columns: minmax(140px, 1.1fr) minmax(92px, .65fr) minmax(180px, 1.35fr) minmax(128px, .85fr) minmax(128px, .85fr) auto;
  gap: var(--space-2);
  align-items: center;
}

.role-assignment-labels {
  padding: 0 var(--space-2);
  color: color-mix(in srgb, var(--text) 45%, transparent);
  font-size: 11px;
}

.role-assignment-list {
  position: relative;
  display: grid;
  gap: var(--space-2);
}

.role-assignment-row {
  padding: var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius);
  background: var(--theme-main-subtle-background);
}

.role-assignment-field {
  min-width: 0;
  color: var(--settings-control-text, var(--theme-control-text));
}

.role-assignment-mobile-label {
  display: none;
}

.role-assignment-input {
  width: 100%;
  min-height: 32px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  outline: 0;
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 0 var(--space-2);
  font-size: 13px;
}

.role-assignment-input:focus,
.role-assignment-input:focus-visible {
  outline: 0;
}

.role-assignment-input::placeholder {
  color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent);
}

.role-assignment-remove {
  align-self: center;
}

.role-assignment-error {
  margin: 0;
  border: 1px solid color-mix(in srgb, var(--red) 28%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent);
  color: color-mix(in srgb, var(--red) 68%, var(--text));
  padding: var(--space-2) var(--space-3);
  font-size: 12px;
  line-height: 1.5;
}

.role-assignment-empty {
  width: 100%;
  color: color-mix(in srgb, var(--text) 65%, transparent);
}

.role-assignment-enter-active,
.role-assignment-leave-active,
.role-assignment-move {
  transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
}

.role-assignment-enter-from,
.role-assignment-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.role-assignment-leave-active {
  position: absolute;
  width: 100%;
}

@media (max-width: 1100px) {
  .role-assignment-labels {
    display: none;
  }

  .role-assignment-row {
    grid-template-columns: minmax(160px, 1.2fr) minmax(110px, .8fr) minmax(180px, 1.3fr) auto;
  }

  .role-assignment-field:nth-of-type(4),
  .role-assignment-field:nth-of-type(5) {
    grid-column: span 2;
  }

  .role-assignment-mobile-label {
    display: block;
    margin-bottom: var(--space-1);
    color: color-mix(in srgb, var(--text) 45%, transparent);
    font-size: 11px;
  }
}

@media (max-width: 720px) {
  .delegation-strategy-body {
    grid-template-columns: 1fr;
  }

  .role-assignment-row {
    grid-template-columns: 1fr;
  }

  .role-assignment-field:nth-of-type(4),
  .role-assignment-field:nth-of-type(5) {
    grid-column: auto;
  }

  .role-assignment-remove {
    justify-self: start;
  }
}

@media (prefers-reduced-motion: reduce) {
  .role-assignment-enter-active,
  .role-assignment-leave-active,
  .role-assignment-move {
    transition: none;
  }
}

.hook-meta {
  margin-top: 10px;
  font-size: 12px;
  color: color-mix(in srgb, var(--settings-main-text, var(--theme-main-text)) 65%, transparent);
  line-height: 1.5;
}
</style>
