<template>
  <section class="plan-library" data-plan-library aria-label="方案库">
    <header class="plan-library-head">
      <div class="plan-library-title">
        <strong>方案</strong>
        <span class="plan-library-count">
          {{ plans.length }} 份<template v-if="openQuestionTotal"> · {{ openQuestionTotal }} 个未答</template>
        </span>
      </div>
      <div class="plan-library-head-actions">
        <button
          class="plan-text-button"
          type="button"
          aria-label="刷新方案库"
          title="刷新"
          :disabled="loading || !rpcReady"
          @click="refresh"
        >
          <RefreshCw :size="13" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <button
          class="plan-text-button"
          type="button"
          :disabled="!rpcReady"
          title="新建一份方案"
          @click="startNew"
        >新建</button>
      </div>
    </header>

    <div class="plan-filters" aria-label="方案筛选">
      <UiSelect
        :model-value="projectFilter"
        :options="projectOptions"
        aria-label="按项目筛选"
        @update:model-value="setProjectFilter"
      />
      <UiSelect
        :model-value="statusFilter"
        :options="statusFilterOptions"
        aria-label="按状态筛选"
        @update:model-value="setStatusFilter"
      />
      <button
        class="plan-toggle"
        :class="{ active: includeDeleted }"
        type="button"
        :aria-pressed="includeDeleted"
        @click="toggleDeleted"
      >{{ includeDeleted ? '隐藏已删除' : '显示已删除' }}</button>
    </div>

    <p v-if="error" class="plan-error" role="alert">{{ error }}</p>
    <p v-if="conflictNotice" class="plan-conflict" role="alert">{{ conflictNotice }}</p>

    <div v-if="!rpcReady" class="plan-state" data-state="empty">方案库需要连接 Core 后使用。</div>
    <div v-else-if="loading" class="plan-state" data-state="loading" role="status" aria-live="polite">
      <LoaderCircle class="plan-spinner" :size="15" :stroke-width="1.8" aria-hidden="true" />
      <span>正在加载方案…</span>
    </div>
    <div v-else-if="!plans.length" class="plan-state" data-state="empty" data-plan-empty>
      还没有方案。让助手先起草一份方案，或点「新建」自己写一份。
    </div>
    <ul v-else class="plan-list" aria-label="方案列表">
      <li
        v-for="plan in plans"
        :key="plan.plan_id"
        class="plan-item"
        :class="{ 'plan-item--selected': selectedId === plan.plan_id, 'plan-item--deleted': Boolean(plan.deleted_at) }"
        :data-plan-id="plan.plan_id"
        :data-status="plan.status"
      >
        <button
          class="plan-item-main"
          type="button"
          :aria-label="`打开方案 ${plan.title || plan.plan_id}`"
          @click="openPlan(plan)"
        >
          <span class="plan-item-copy">
            <span class="plan-title" :title="plan.title">{{ plan.title || '（无标题）' }}</span>
            <span class="plan-summary">{{ plan.summary || '（无摘要）' }}</span>
            <span class="plan-item-meta">
              <span class="plan-status" :data-status="plan.status">{{ statusLabel(plan.status) }}</span>
              <span class="plan-progress">{{ progressLabel(plan) }}</span>
              <span v-if="openCount(plan)" class="plan-questions">{{ openCount(plan) }} 个未答</span>
              <span v-if="plan.deleted_at" class="plan-deleted-flag">已删除</span>
            </span>
          </span>
        </button>
        <div class="plan-item-actions">
          <button
            v-if="plan.deleted_at"
            class="plan-icon-button plan-icon-button--restore"
            type="button"
            :disabled="busyId === plan.plan_id"
            :aria-label="`恢复方案 ${plan.title}`"
            title="恢复"
            @click="restoreRow(plan)"
          >恢复</button>
          <button
            v-else
            class="plan-icon-button plan-icon-button--danger"
            type="button"
            :disabled="busyId === plan.plan_id"
            :aria-label="`删除方案 ${plan.title}`"
            title="删除"
            @click="deleteRow(plan)"
          >删除</button>
        </div>
      </li>
    </ul>

    <section v-if="hasDraft" class="plan-editor" data-plan-editor :aria-label="isNew ? '新建方案' : '编辑方案'">
      <header class="plan-editor-head">
        <div class="plan-editor-title">
          <strong>{{ isNew ? '新建方案' : `修订 ${savedSnapshot?.revision ?? ''}` }}</strong>
          <span v-if="dirty" class="plan-dirty">未保存</span>
          <span v-else-if="savedSnapshot?.deleted_at" class="plan-deleted-flag">已删除</span>
        </div>
        <button class="plan-text-button" type="button" @click="closeDraft">关闭</button>
      </header>

      <label class="plan-field">
        <span class="plan-label">标题</span>
        <input class="plan-input" type="text" placeholder="这份方案要解决什么" v-model="draft.title" />
      </label>
      <div class="plan-field">
        <span class="plan-label">状态</span>
        <UiSelect
          :model-value="draft.status"
          :options="draftStatusOptions"
          aria-label="方案状态"
          @update:model-value="setDraftStatus"
        />
      </div>
      <label class="plan-field">
        <span class="plan-label">摘要</span>
        <AutoTextarea :min-rows="2" :max-rows="3" placeholder="一句话摘要" v-model="draft.summary" />
      </label>

      <section class="plan-block" data-plan-block="requirement">
        <h3 class="plan-block-title">需求</h3>
        <label class="plan-field">
          <span class="plan-label">复述</span>
          <AutoTextarea :min-rows="2" :max-rows="5" placeholder="把需求用自己的话说一遍" v-model="draft.requirement.restatement" />
        </label>
        <label class="plan-field">
          <span class="plan-label">成功是什么样</span>
          <AutoTextarea :min-rows="2" :max-rows="5" placeholder="用户观察到什么才算成" v-model="draft.requirement.success_looks_like" />
        </label>
        <div class="plan-field">
          <span class="plan-label">明确不做</span>
          <PlanStringListEditor v-model="draft.requirement.non_goals" aria-label="明确不做" placeholder="这一项不做" add-label="加一项不做的" />
        </div>
        <div class="plan-field">
          <span class="plan-label">假设</span>
          <PlanStringListEditor v-model="draft.requirement.assumptions" aria-label="假设" placeholder="假设…" add-label="加一条假设" />
        </div>
      </section>

      <section class="plan-block" data-plan-block="approach">
        <h3 class="plan-block-title">取舍</h3>
        <label class="plan-field">
          <span class="plan-label">选中方案</span>
          <input class="plan-input" type="text" placeholder="打算怎么做" v-model="draft.approach.chosen" />
        </label>
        <label class="plan-field">
          <span class="plan-label">理由</span>
          <AutoTextarea :min-rows="2" :max-rows="5" placeholder="为什么是它" v-model="draft.approach.why" />
        </label>
        <div class="plan-field">
          <span class="plan-label">被否决的方案</span>
          <div v-for="(entry, index) in draft.approach.rejected" :key="index" class="plan-rejected-row" data-plan-rejected>
            <input class="plan-input" type="text" placeholder="被否决的方案" v-model="entry.option" />
            <input class="plan-input" type="text" placeholder="为什么否决" v-model="entry.why" />
            <button
              class="plan-icon-button"
              type="button"
              :aria-label="`删除被否决的方案 ${index + 1}`"
              title="删除"
              @click="draft.approach.rejected.splice(index, 1)"
            >×</button>
          </div>
          <button class="plan-add-button" type="button" @click="draft.approach.rejected.push({ option: '', why: '' })">
            加一个被否决的方案
          </button>
        </div>
      </section>

      <section class="plan-block" data-plan-block="docs">
        <h3 class="plan-block-title">文档</h3>
        <p v-if="!draft.docs.length" class="plan-block-empty">还没有要写的文档。</p>
        <div v-for="(doc, index) in draft.docs" :key="index" class="plan-doc-row" data-plan-doc>
          <input class="plan-input" type="text" placeholder="项目内相对路径" v-model="doc.path" />
          <UiSelect
            :model-value="doc.kind"
            :options="docKindOptions"
            :aria-label="`文档 ${index + 1} 种类`"
            @update:model-value="doc.kind = asDocKind($event)"
          />
          <input class="plan-input" type="text" placeholder="标题" v-model="doc.title" />
          <button
            class="plan-icon-button"
            type="button"
            :aria-label="`删除文档 ${index + 1}`"
            title="删除"
            @click="draft.docs.splice(index, 1)"
          >×</button>
        </div>
        <button class="plan-add-button" type="button" @click="draft.docs.push({ path: '', kind: 'design', title: '' })">
          加一份文档
        </button>
      </section>

      <section class="plan-block" data-plan-block="steps">
        <h3 class="plan-block-title">步骤 <span class="plan-block-hint">{{ progressLabel(draft) }}</span></h3>
        <p v-if="!draft.checklist.steps.length" class="plan-block-empty">还没有步骤；就绪（定稿）至少需要一步。</p>
        <div v-for="(step, index) in draft.checklist.steps" :key="step.id" class="plan-step" :data-plan-step="step.id">
          <div class="plan-step-head">
            <span class="plan-step-index">{{ index + 1 }}</span>
            <UiSelect
              :model-value="step.status"
              :options="stepStatusOptions"
              :aria-label="`步骤 ${index + 1} 状态`"
              @update:model-value="step.status = asStepStatus($event)"
            />
            <button
              class="plan-icon-button"
              type="button"
              :aria-label="`删除步骤 ${index + 1}`"
              title="删除"
              @click="removeDraftStep(index)"
            >×</button>
          </div>
          <AutoTextarea :min-rows="2" :max-rows="5" placeholder="要改什么，怎么知道做完了" v-model="step.description" />
          <div class="plan-field">
            <span class="plan-label">交付物</span>
            <PlanStringListEditor
              v-model="step.deliverables"
              :aria-label="`步骤 ${index + 1} 交付物`"
              placeholder="交付物"
              add-label="加一个交付物"
            />
          </div>
        </div>
        <button class="plan-add-button" type="button" @click="addDraftStep">加一步</button>
      </section>

      <section class="plan-block" data-plan-block="goal">
        <h3 class="plan-block-title">目标与完成判据</h3>
        <label class="plan-field">
          <span class="plan-label">目标</span>
          <input class="plan-input" type="text" placeholder="这项工作为了什么" v-model="draft.goal.objective" />
        </label>
        <div class="plan-field">
          <span class="plan-label">完成判据</span>
          <PlanStringListEditor
            v-model="draft.goal.completion_criteria"
            aria-label="完成判据"
            placeholder="满足了什么就算完成"
            add-label="加一条完成判据"
          />
        </div>
      </section>

      <section class="plan-block" data-plan-block="risks">
        <h3 class="plan-block-title">风险</h3>
        <p v-if="!draft.risks.length" class="plan-block-empty">还没有记录风险。</p>
        <div v-for="(risk, index) in draft.risks" :key="index" class="plan-risk-row" data-plan-risk>
          <input class="plan-input" type="text" placeholder="风险" v-model="risk.risk" />
          <UiSelect
            :model-value="risk.severity"
            :options="severityOptions"
            :aria-label="`风险 ${index + 1} 等级`"
            @update:model-value="risk.severity = asSeverity($event)"
          />
          <AutoTextarea :min-rows="2" :max-rows="3" placeholder="怎么应对" v-model="risk.mitigation" />
          <button
            class="plan-icon-button"
            type="button"
            :aria-label="`删除风险 ${index + 1}`"
            title="删除"
            @click="draft.risks.splice(index, 1)"
          >×</button>
        </div>
        <button class="plan-add-button" type="button" @click="draft.risks.push({ risk: '', severity: 'medium', mitigation: '' })">
          加一条风险
        </button>
      </section>

      <section class="plan-block" data-plan-block="questions">
        <h3 class="plan-block-title">未答问题</h3>
        <p v-if="!draft.open_questions.length" class="plan-block-empty">没有待答的问题。</p>
        <div v-for="(question, index) in draft.open_questions" :key="question.id" class="plan-question" :data-plan-question="question.id">
          <div class="plan-question-head">
            <input class="plan-input" type="text" placeholder="问题" v-model="question.question" />
            <UiSelect
              :model-value="question.status"
              :options="questionStatusOptions"
              :aria-label="`问题 ${index + 1} 状态`"
              @update:model-value="setQuestionStatus(question, $event)"
            />
            <button
              class="plan-icon-button"
              type="button"
              :aria-label="`删除问题 ${index + 1}`"
              title="删除"
              @click="removeDraftQuestion(index)"
            >×</button>
          </div>
          <AutoTextarea
            :min-rows="2"
            :max-rows="4"
            :placeholder="question.status === 'open' ? '写下答案即转为已答' : '答案'"
            :model-value="question.answer"
            @update:model-value="onAnswerInput(question, $event)"
          />
        </div>
        <button class="plan-add-button" type="button" @click="addDraftQuestion">加一个问题</button>
      </section>

      <section v-if="!isNew" class="plan-block" data-plan-block="revisions">
        <h3 class="plan-block-title">版本</h3>
        <p v-if="revisionsLoading" class="plan-block-empty">正在加载版本…</p>
        <p v-else-if="!revisions.length" class="plan-block-empty">暂无版本记录。</p>
        <div v-else class="plan-revision-list">
          <div v-for="revision in revisions" :key="revision.revision" class="plan-revision" data-plan-revision>
            <span class="plan-revision-copy">
              <strong>修订 {{ revision.revision }}</strong>
              <span>{{ revision.title || '（无标题）' }} · {{ statusLabel(revision.status) }} · {{ formatPlanTime(revision.created_at) }}</span>
            </span>
            <button
              v-if="revision.revision !== savedSnapshot?.revision"
              class="plan-text-button"
              type="button"
              :disabled="saving"
              @click="revert(revision.revision)"
            >回滚</button>
            <span v-else class="plan-revision-current">当前</span>
          </div>
        </div>
      </section>

      <div class="plan-editor-actions">
        <button
          class="plan-action plan-action--primary"
          type="button"
          :disabled="saving || !dirty"
          @click="save"
        >{{ saving ? '保存中…' : (isNew ? '创建' : '保存') }}</button>
        <button class="plan-action" type="button" :disabled="!dirty" @click="resetDraft">还原</button>
        <button
          class="plan-action plan-action--start"
          type="button"
          data-plan-start
          :disabled="startDisabled"
          :title="startTitle"
          @click="startWork"
        >开工</button>
        <button
          v-if="savedSnapshot && !savedSnapshot.deleted_at"
          class="plan-action plan-action--danger"
          type="button"
          :disabled="busyId === savedSnapshot.plan_id"
          @click="deleteSelected"
        >删除</button>
        <button
          v-if="savedSnapshot?.deleted_at"
          class="plan-action"
          type="button"
          :disabled="busyId === savedSnapshot.plan_id"
          @click="restoreSelected"
        >恢复</button>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { LoaderCircle, RefreshCw } from 'lucide-vue-next'
import UiSelect from '../components/UiSelect.vue'
import AutoTextarea from '../components/AutoTextarea.vue'
import PlanStringListEditor from './PlanStringListEditor.vue'
import { usePlanLibrary } from './usePlanLibrary'
import {
  PLAN_DOC_KINDS,
  PLAN_STATUSES,
  PLAN_STEP_STATUSES,
  type PlanDocKind,
  type PlanPackage,
  type PlanQuestion,
  type PlanRiskSeverity,
  type PlanStatus,
  type PlanStepStatus,
} from './types'
import {
  PLAN_DOC_KIND_LABELS,
  PLAN_QUESTION_STATUS_LABELS,
  PLAN_RISK_SEVERITY_LABELS,
  PLAN_STATUS_LABELS,
  PLAN_STEP_STATUS_LABELS,
  asRiskSeverity,
  clonePlan,
  formatPlanTime,
  isDocKind,
  isPlanStatus,
  isStepStatus,
  planStatusTargets,
} from './planEditing'

const props = withDefaults(defineProps<{
  projectId?: string | null
  requestRpc?: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>(), {
  projectId: null,
  requestRpc: undefined,
})

const emit = defineEmits<{
  'start-plan': [plan: PlanPackage]
}>()

const rpcReady = computed(() => Boolean(props.requestRpc))

const {
  plans,
  projects,
  loading,
  error,
  conflictNotice,
  statusFilter,
  projectFilter,
  includeDeleted,
  selectedId,
  hasDraft,
  draft,
  savedSnapshot,
  revisions,
  revisionsLoading,
  saving,
  busyId,
  isNew,
  dirty,
  openQuestionTotal,
  refresh,
  loadProjects,
  selectPlan,
  startNew,
  closeDraft,
  resetDraft,
  save,
  remove,
  restore,
  revert,
  setStatusFilter,
  setProjectFilter,
  toggleDeleted,
  addDraftStep,
  removeDraftStep,
  addDraftQuestion,
  removeDraftQuestion,
} = usePlanLibrary({
  requestRpc: (method, params) => {
    if (!props.requestRpc) return Promise.reject(new Error('方案库需要连接 Core 后使用。'))
    return props.requestRpc(method, params)
  },
  projectId: () => props.projectId ?? null,
})

const projectOptions = computed(() => {
  const options = [{ value: '', label: '全部项目' }]
  const seen = new Set([''])
  for (const project of projects.value) {
    if (seen.has(project.id)) continue
    seen.add(project.id)
    options.push({ value: project.id, label: project.name })
  }
  if (projectFilter.value && !seen.has(projectFilter.value)) {
    options.push({ value: projectFilter.value, label: '当前项目' })
  }
  return options
})

const statusFilterOptions = computed(() => [
  { value: '', label: '全部状态' },
  ...PLAN_STATUSES.map((status) => ({ value: status, label: PLAN_STATUS_LABELS[status] })),
])

const draftStatusOptions = computed(() => {
  const current = draft.status
  const values = [current, ...planStatusTargets(current).filter((status) => status !== current)]
  return values.map((status) => ({ value: status, label: PLAN_STATUS_LABELS[status] }))
})

const stepStatusOptions = PLAN_STEP_STATUSES.map((status) => ({
  value: status,
  label: PLAN_STEP_STATUS_LABELS[status],
}))

const docKindOptions = PLAN_DOC_KINDS.map((kind) => ({
  value: kind,
  label: PLAN_DOC_KIND_LABELS[kind],
}))

const severityOptions = (['low', 'medium', 'high'] as PlanRiskSeverity[]).map((severity) => ({
  value: severity,
  label: PLAN_RISK_SEVERITY_LABELS[severity],
}))

const questionStatusOptions = (['open', 'answered'] as PlanQuestion['status'][]).map((status) => ({
  value: status,
  label: PLAN_QUESTION_STATUS_LABELS[status],
}))

const startDisabled = computed(() => (
  !savedSnapshot.value
  || savedSnapshot.value.status !== 'ready'
  || Boolean(savedSnapshot.value.deleted_at)
  || dirty.value
  || saving.value
))

const startTitle = computed(() => {
  const plan = savedSnapshot.value
  if (!plan) return '先保存一份方案'
  if (dirty.value) return '先保存改动再开工'
  if (plan.deleted_at) return '已删除的方案不能开工'
  if (plan.status === 'ready') return '把这份方案的步骤装进当前会话的清单'
  return '只有「就绪」的方案可以开工'
})

function statusLabel(status: PlanStatus): string {
  return PLAN_STATUS_LABELS[status] || status
}

function progressLabel(plan: PlanPackage): string {
  const total = plan.checklist.steps.length
  const done = plan.checklist.steps.filter((step) => step.status === 'completed' || step.status === 'skipped').length
  return `${done}/${total} 步`
}

function openCount(plan: PlanPackage): number {
  return plan.open_questions.filter((question) => question.status === 'open').length
}

function asStepStatus(value: string): PlanStepStatus {
  return isStepStatus(value) ? value : 'pending'
}

function asDocKind(value: string): PlanDocKind {
  return isDocKind(value) ? value : 'notes'
}

function asSeverity(value: string): PlanRiskSeverity {
  return asRiskSeverity(value)
}

function setDraftStatus(value: string): void {
  if (isPlanStatus(value)) draft.status = value
}

function setQuestionStatus(question: PlanQuestion, value: string): void {
  question.status = value === 'answered' ? 'answered' : 'open'
}

/** Writing an answer settles the question, as the package contract intends. */
function onAnswerInput(question: PlanQuestion, value: string): void {
  question.answer = value
  if (value.trim() && question.status === 'open') question.status = 'answered'
}

function openPlan(plan: PlanPackage): void {
  if (dirty.value && selectedId.value !== plan.plan_id) {
    if (!window.confirm('当前方案有未保存的改动，切换会丢弃它们。继续？')) return
  }
  selectPlan(plan)
}

function deleteRow(plan: PlanPackage): void {
  if (!window.confirm(`确定删除「${plan.title || plan.plan_id}」？方案会被软删除，之后可以恢复。`)) return
  void remove(plan.plan_id)
}

function restoreRow(plan: PlanPackage): void {
  void restore(plan.plan_id)
}

function deleteSelected(): void {
  const plan = savedSnapshot.value
  if (!plan) return
  deleteRow(plan)
}

function restoreSelected(): void {
  const plan = savedSnapshot.value
  if (plan) void restore(plan.plan_id)
}

function startWork(): void {
  const plan = savedSnapshot.value
  if (!plan || startDisabled.value) return
  emit('start-plan', clonePlan(plan))
}

onMounted(() => {
  void loadProjects()
  void refresh()
})

defineExpose({
  plans,
  draft,
  savedSnapshot,
  selectedId,
  hasDraft,
  revisions,
  error,
  conflictNotice,
  dirty,
  refresh,
  selectPlan,
  startNew,
  save,
  remove,
  restore,
  revert,
  resetDraft,
  closeDraft,
})
</script>

<style scoped>
.plan-library { --text: var(--theme-backdrop-text); display: flex; flex-direction: column; gap: var(--space-2); min-width: 0; padding: 0 var(--space-2) var(--space-3); color: var(--text); overflow-wrap: anywhere; }
.plan-library-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-1) 0 0; }
.plan-library-title { display: flex; align-items: baseline; gap: var(--space-1); min-width: 0; }
.plan-library-title strong { font-size: 13px; font-weight: 760; }
.plan-library-count { color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 10px; }
.plan-library-head-actions { display: inline-flex; align-items: center; gap: var(--space-1); }
.plan-text-button { display: inline-flex; align-items: center; justify-content: center; min-height: 28px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-2); background: transparent; color: color-mix(in srgb, var(--text) 64%, transparent); font-size: 11px; }
.plan-text-button:hover:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-text-button:active:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.plan-text-button:disabled { opacity: .45; }
.plan-text-button:focus-visible, .plan-icon-button:focus-visible, .plan-add-button:focus-visible, .plan-toggle:focus-visible, .plan-action:focus-visible, .plan-item-main:focus-visible, .plan-input:focus-visible { outline: 2px solid color-mix(in srgb, var(--blue) 75%, transparent); outline-offset: 1px; }
.plan-filters { display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-1); }
.plan-filters :deep(.ui-select-trigger) { min-height: 28px; padding-inline: var(--space-1); font-size: 10px; }
.plan-toggle { grid-column: 1 / -1; justify-self: start; min-height: 26px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 10px; }
.plan-toggle:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-toggle.active { color: var(--orange); }
.plan-error { margin: 0; border: 1px solid color-mix(in srgb, var(--red) 22%, transparent); border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); background: color-mix(in srgb, var(--red) 10%, var(--theme-backdrop-background)); color: color-mix(in srgb, var(--red) 80%, var(--text) 20%); font-size: 11px; }
.plan-conflict { margin: 0; border: 1px solid color-mix(in srgb, var(--orange) 22%, transparent); border-radius: var(--radius-sm); padding: var(--space-1) var(--space-2); background: color-mix(in srgb, var(--orange) 10%, var(--theme-backdrop-background)); color: color-mix(in srgb, var(--orange) 78%, var(--text) 22%); font-size: 11px; }
.plan-state { display: flex; align-items: center; justify-content: center; gap: var(--space-1); min-height: 88px; padding: var(--space-3); color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 11px; line-height: 1.6; text-align: center; }
.plan-spinner { animation: plan-spin .9s linear infinite; color: var(--blue); }
@keyframes plan-spin { to { transform: rotate(360deg); } }
.plan-list { display: grid; gap: var(--space-1); margin: 0; padding: 0; list-style: none; }
.plan-item { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: var(--space-1); min-width: 0; border: 1px solid color-mix(in srgb, var(--text) 12%, transparent); border-radius: var(--radius-sm); padding: var(--space-1); background: var(--theme-backdrop-background); }
.plan-item:hover { border-color: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); background: color-mix(in srgb, var(--text) var(--alpha-hover), var(--theme-backdrop-background)); }
.plan-item--selected { border-color: color-mix(in srgb, var(--text) 28%, transparent); background: color-mix(in srgb, var(--text) var(--alpha-active), var(--theme-backdrop-background)); }
.plan-item--deleted { opacity: .68; }
.plan-item-main { display: block; min-width: 0; border: 0; border-radius: var(--radius-sm); padding: var(--space-1); background: transparent; color: inherit; text-align: left; }
.plan-item-copy { display: grid; min-width: 0; gap: 2px; }
.plan-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; font-weight: 700; }
.plan-summary { min-width: 0; overflow: hidden; color: color-mix(in srgb, var(--text) 48%, transparent); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.plan-item-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); padding-top: 2px; }
.plan-status, .plan-progress, .plan-questions, .plan-deleted-flag { flex: 0 0 auto; border-radius: 999px; padding: 1px var(--space-1); color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 9px; }
.plan-status[data-status="executing"] { color: var(--blue); }
.plan-status[data-status="ready"] { color: var(--green); }
.plan-status[data-status="done"] { color: var(--green); }
.plan-status[data-status="archived"], .plan-deleted-flag { color: color-mix(in srgb, var(--text) 45%, transparent); }
.plan-questions { color: var(--orange); }
.plan-item-actions { display: inline-flex; align-items: center; gap: 2px; }
.plan-icon-button { display: inline-flex; align-items: center; justify-content: center; min-width: 26px; min-height: 26px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 10px; }
.plan-icon-button:hover:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-icon-button:active:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.plan-icon-button:disabled { opacity: .45; }
.plan-icon-button--danger:hover:not(:disabled) { color: var(--red); }
.plan-icon-button--restore:hover:not(:disabled) { color: var(--green); }
.plan-editor { display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); padding-top: var(--space-2); }
.plan-editor-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); }
.plan-editor-title { display: flex; align-items: center; gap: var(--space-1); min-width: 0; }
.plan-editor-title strong { font-size: 11px; }
.plan-dirty { border-radius: 999px; padding: 1px var(--space-1); color: var(--orange); font-size: 9px; }
.plan-block { display: flex; flex-direction: column; gap: var(--space-2); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); padding-top: var(--space-2); }
.plan-block-title { display: flex; align-items: baseline; gap: var(--space-1); margin: 0; font-size: 11px; font-weight: 700; }
.plan-block-hint { color: color-mix(in srgb, var(--text) 48%, transparent); font-size: 9px; font-weight: 400; }
.plan-block-empty { margin: 0; color: color-mix(in srgb, var(--text) 45%, transparent); font-size: 10px; }
.plan-field { display: grid; gap: var(--space-1); min-width: 0; }
.plan-label { color: color-mix(in srgb, var(--text) 58%, transparent); font-size: 10px; }
.plan-input { width: 100%; min-width: 0; box-sizing: border-box; min-height: 30px; border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent); border-radius: var(--radius-sm); padding: 0 var(--space-2); background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent); color: var(--theme-composer-text); caret-color: var(--theme-composer-text); font: inherit; font-size: 11px; }
.plan-input::placeholder { color: color-mix(in srgb, var(--theme-composer-text) 45%, transparent); }
.plan-input:focus-visible { outline: 0; }
.plan-add-button { justify-self: start; min-height: 26px; border: 0; border-radius: var(--radius-sm); padding: 0 var(--space-1); background: transparent; color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 10px; }
.plan-add-button:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-rejected-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; align-items: center; gap: var(--space-1); min-width: 0; }
.plan-doc-row { display: grid; gap: var(--space-1); min-width: 0; }
.plan-doc-row :deep(.plan-icon-button) { justify-self: start; }
.plan-step, .plan-risk-row, .plan-question { display: grid; gap: var(--space-1); min-width: 0; border-radius: var(--radius-sm); padding: var(--space-2); background: color-mix(in srgb, var(--text) 5%, var(--theme-backdrop-background)); }
.plan-step-head, .plan-question-head { display: flex; align-items: center; gap: var(--space-1); min-width: 0; }
.plan-step-index { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; width: 18px; height: 18px; border-radius: 999px; background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: color-mix(in srgb, var(--text) 68%, transparent); font-size: 9px; }
.plan-step-head :deep(.ui-select), .plan-question-head :deep(.ui-select) { flex: 1 1 auto; min-width: 0; }
.plan-revision-list { display: grid; gap: var(--space-1); }
.plan-revision { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); border-radius: var(--radius-sm); padding: var(--space-1); background: color-mix(in srgb, var(--text) 5%, var(--theme-backdrop-background)); }
.plan-revision-copy { display: grid; min-width: 0; gap: 2px; }
.plan-revision-copy strong { font-size: 10px; }
.plan-revision-copy span { min-width: 0; overflow: hidden; color: color-mix(in srgb, var(--text) 46%, transparent); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.plan-revision-current { color: color-mix(in srgb, var(--text) 45%, transparent); font-size: 9px; }
.plan-editor-actions { display: flex; flex-wrap: wrap; gap: var(--space-1); border-top: 1px solid color-mix(in srgb, var(--text) 12%, transparent); padding-top: var(--space-2); }
.plan-action { display: inline-flex; align-items: center; justify-content: center; min-height: 30px; border: 1px solid color-mix(in srgb, var(--text) 14%, transparent); border-radius: var(--radius-sm); padding: 0 var(--space-2); background: transparent; color: color-mix(in srgb, var(--text) 72%, transparent); font-size: 11px; }
.plan-action:hover:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.plan-action:active:not(:disabled) { background: color-mix(in srgb, var(--text) var(--alpha-active), transparent); }
.plan-action:disabled { opacity: .45; }
.plan-action--primary { background: var(--theme-control-background); color: var(--theme-control-text); border-color: transparent; }
.plan-action--primary:hover:not(:disabled) { background: var(--theme-control-background); filter: brightness(.94); color: var(--theme-control-text); }
.plan-action--start { color: color-mix(in srgb, var(--green) 78%, var(--text) 22%); border-color: color-mix(in srgb, var(--green) 28%, transparent); }
.plan-action--danger { color: color-mix(in srgb, var(--red) 80%, var(--text) 20%); border-color: color-mix(in srgb, var(--red) 24%, transparent); }
.plan-action--danger:hover:not(:disabled) { background: color-mix(in srgb, var(--red) var(--alpha-hover), transparent); color: var(--red); }
@media (max-width: 640px) {
  .plan-filters { grid-template-columns: 1fr 1fr; }
  .plan-filters :deep(.ui-select-trigger) { min-height: 34px; }
  .plan-toggle { min-height: 34px; }
  .plan-input { min-height: 36px; font-size: 12px; }
  .plan-icon-button { min-width: 34px; min-height: 34px; }
  .plan-text-button, .plan-add-button { min-height: 34px; }
  .plan-action { min-height: 38px; flex: 1 1 auto; }
}
@media (prefers-reduced-motion: reduce) {
  .plan-spinner { animation: none; }
}
</style>
