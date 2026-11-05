<script setup lang="ts">
/**
 * Super-agent 交付台。
 *
 * user:“让用户能直观地发起任务、查看进度、干预执行和查看成果。界面保持 Sunday 现有
 * 设计语言，不堆砌管理面板。”+(所以这里只有三件事：交付目标、看它做到哪一步、
 * 验收或退回；执行细节由后端与已有会话界面承担，不在这里再造一套监控面板)。
 */
import { t } from '@/i18n/index.ts'

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowLeft, CircleAlert, FileCheck2, Plus, RotateCw, Square, Undo2 } from 'lucide-vue-next'
import FullAreaActions from '@/components/FullAreaActions.vue'
import UiSelect from '@/components/UiSelect.vue'

type Stage = 'open' | 'running' | 'review' | 'blocked' | 'closed'

interface TicketMandate {
  repo_root?: string
  base_branch?: string
  can_push?: boolean
  can_create_pr?: boolean
  revoked?: boolean
}

interface Ticket {
  ticket_id: string
  title?: string
  stage: Stage
  instructions?: string
  decision_reason?: string
  mandate?: TicketMandate
  result?: Record<string, unknown>
  job_id?: string
  assignment_id?: string
  created_at?: string
  updated_at?: string
}

interface Assignment {
  assignment_id: string
  status?: string
  worktree_path?: string
  branch?: string
  started_at?: string
  ended_at?: string | null
}

const props = defineProps<{
  workRoot?: string
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  /** Desktop sends the actions into the header band; phones render them in place. */
  bandActions?: boolean
}>()
const emit = defineEmits<{
  back: []
  heading: [payload: { title: string; subtitle: string }]
  openSession: [sessionId: string]
}>()

const view = ref<'list' | 'compose' | 'detail'>('list')
const tickets = ref<Ticket[]>([])
const loading = ref(false)
const busy = ref('')
const error = ref('')
const notice = ref('')

const selected = ref<Ticket | null>(null)
const assignments = ref<Assignment[]>([])

const formGoal = ref('')
const formRepo = ref('')
const formBranch = ref('')
const formPush = ref(false)
const formPr = ref(false)
const formPreset = ref('auto')
const formRequireApproval = ref(false)

const presetOptions = computed(() => [
  { value: 'auto', label: t('自己动手，危险操作仍然拦下') },
  { value: 'full_access', label: t('完全放开') },
])

const presetHint = computed(() =>
  formPreset.value === 'full_access'
    ? t('不再拦任何操作，包括越界访问。只在完全信任目标时用。')
    : t('读写文件、跑测试自己决定；真正的危险操作仍会被拦。'),
)

const STAGE_LABEL: Record<Stage, string> = {
  open: '待开始',
  running: '执行中',
  review: '待验收',
  blocked: '需处理',
  closed: '已交付',
}

const heading = computed(() => {
  if (view.value === 'compose') return { get title() { return t("Super-agent › 交付新目标") }, subtitle: '' }
  if (view.value === 'detail') return { get title() { return t("Super-agent › 工单详情") }, subtitle: '' }
  return { get title() { return t("Super-agent") }, get subtitle() { return t("把复杂目标交给它，自己规划、执行并交付结果。") } }
})
watch(heading, (value) => emit('heading', { ...value }), { immediate: true })

function repoName(path?: string): string {
  const raw = String(path || '').trim()
  if (!raw) return ''
  const parts = raw.split(/[\\/]+/).filter(Boolean)
  return parts.length ? parts[parts.length - 1] : raw
}

function when(value?: string): string {
  if (!value) return ''
  const stamp = new Date(value)
  if (Number.isNaN(stamp.getTime())) return ''
  const diff = Date.now() - stamp.getTime()
  if (diff < 60_000) return t('刚刚')
  if (diff < 3_600_000) return t('{0} 分钟前', { 0: Math.floor(diff / 60_000) })
  if (diff < 86_400_000) return t('{0} 小时前', { 0: Math.floor(diff / 3_600_000) })
  return stamp.toLocaleDateString()
}

function resultText(key: string): string {
  const value = selected.value?.result?.[key]
  if (value === null || value === undefined || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function resultFiles(): string[] {
  const value = selected.value?.result?.files
  return Array.isArray(value) ? value.map((item) => String(item)) : []
}

function sessionId(): string {
  return String(selected.value?.result?.thread_id || '')
}

async function call<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  return (await props.requestRpc(method, params)) as T
}

async function loadTickets() {
  loading.value = true
  error.value = ''
  try {
    const payload = await call<{ tickets?: Ticket[] }>('superagent.ticket.list', {})
    tickets.value = payload.tickets || []
  } catch (cause) {
    error.value = String(cause)
  } finally {
    loading.value = false
  }
}

function openCompose() {
  formGoal.value = ''
  formRepo.value = props.workRoot || ''
  formBranch.value = ''
  formPush.value = false
  formPr.value = false
  formPreset.value = 'auto'
  formRequireApproval.value = false
  error.value = ''
  notice.value = ''
  view.value = 'compose'
}

async function submitGoal() {
  const goal = formGoal.value.trim()
  if (!goal) {
    error.value = t('先写清楚要它做什么')
    return
  }
  busy.value = 'submit'
  error.value = ''
  notice.value = ''
  try {
    const payload = await call<{ result?: { status?: string; reason?: string; ticket_id?: string } }>(
      'superagent.goal.submit',
      {
        goal,
        repo_root: formRepo.value.trim() || props.workRoot || '',
        base_branch: formBranch.value.trim(),
        can_push: formPush.value,
        can_create_pr: formPr.value,
        permission_preset: formPreset.value,
        require_approval: formRequireApproval.value,
      },
    )
    const status = String(payload.result?.status || '')
    if (status === 'duplicate') {
      notice.value = t('这个目标已经在队列里了，直接打开那张工单就行')
    } else if (status === 'ask_human') {
      // 工单停在待确认：这不是失败，用户点头之后才开工。
      notice.value = t('已提交，等你确认后开工。在列表里打开它点「批准开工」。')
    } else if (status !== 'accepted') {
      error.value = String(payload.result?.reason || t('没能接单'))
      return
    }
    view.value = 'list'
    await loadTickets()
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = ''
  }
}

async function openDetail(ticket: Ticket) {
  busy.value = 'detail'
  error.value = ''
  try {
    const payload = await call<{ ticket?: Ticket; assignments?: Assignment[] }>(
      'superagent.ticket.report',
      { ticket_id: ticket.ticket_id },
    )
    selected.value = payload.ticket || ticket
    assignments.value = payload.assignments || []
    view.value = 'detail'
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = ''
  }
}

async function act(action: 'close' | 'reject' | 'retry' | 'stop' | 'approve') {
  const ticket = selected.value
  if (!ticket) return
  busy.value = action
  error.value = ''
  notice.value = ''
  try {
    if (action === 'approve') {
      await call('superagent.ticket.approve', { ticket_id: ticket.ticket_id, approver: 'ui' })
    } else if (action === 'retry') {
      await call('superagent.ticket.retry', { ticket_id: ticket.ticket_id })
    } else if (action === 'stop') {
      await call('superagent.ticket.stop', { ticket_id: ticket.ticket_id })
    } else {
      await call('superagent.ticket.close', {
        ticket_id: ticket.ticket_id,
        accepted: action === 'close',
      })
    }
    await loadTickets()
    const refreshed = tickets.value.find((item) => item.ticket_id === ticket.ticket_id)
    if (refreshed) await openDetail(refreshed)
    else view.value = 'list'
  } catch (cause) {
    error.value = String(cause)
  } finally {
    busy.value = ''
  }
}

function goBack() {
  if (view.value !== 'list') {
    view.value = 'list'
    selected.value = null
    error.value = ''
    return
  }
  emit('back')
}

let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  void loadTickets()
  // 工单是后台跑的，列表按节奏自己刷新；离开页面就停，不在后台空转。
  timer = setInterval(() => {
    if (view.value === 'list' && !loading.value) void loadTickets()
  }, 15_000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
  timer = null
})
</script>

<template>
  <div class="sa-view">
    <main class="sa-page full-area-column">
      <FullAreaActions :to-band="bandActions">
        <template v-if="view === 'list'">
          <button class="icon-button" type="button" :disabled="loading" :aria-label="t('刷新')" :title="t('刷新')" @click="loadTickets">
            <RotateCw :size="14" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <button class="primary-button" type="button" @click="openCompose">{{ t("交付新目标") }}</button>
        </template>
      </FullAreaActions>

      <!-- 手机没有顶部条：标题与返回键留在版面里。 -->
      <header v-if="!bandActions" class="sa-mobile-head">
        <button class="sa-back" type="button" :aria-label="t('返回')" @click="goBack">
          <ArrowLeft :size="16" :stroke-width="1.8" aria-hidden="true" />
        </button>
        <div class="sa-head-copy">
          <h1>{{ heading.title }}</h1>
          <p v-if="heading.subtitle" class="sa-subtitle">{{ heading.subtitle }}</p>
        </div>
      </header>

      <p v-if="notice" class="sa-notice">{{ notice }}</p>
      <div v-if="error" class="sa-error" role="alert">
        <span>{{ error }}</span>
        <button type="button" @click="error = ''">{{ t("知道了") }}</button>
      </div>

      <!-- ── 交付新目标 ── -->
      <section v-if="view === 'compose'" class="sa-card">
        <label class="sa-field">
          <span class="sa-label">{{ t("要它做成什么") }}</span>
          <textarea
            v-model="formGoal"
            class="sa-input sa-textarea"
            rows="4"
            :placeholder="t('写清楚目标与验收标准，例如：把资料库的搜索改成支持按标签过滤，并补一条端到端测试')"
          />
        </label>
        <label class="sa-field">
          <span class="sa-label">{{ t("在哪个目录里做") }}</span>
          <input v-model="formRepo" class="sa-input" type="text" :placeholder="workRoot || t('仓库或目录的绝对路径')" />
          <span class="sa-hint">{{ t("是 git 仓库时它会开独立工作树和分支，不会动你当前的检出。") }}</span>
        </label>
        <label class="sa-field">
          <span class="sa-label">{{ t("从哪条分支开始") }}</span>
          <input v-model="formBranch" class="sa-input" type="text" placeholder="main" />
        </label>
        <label class="sa-check sa-check--wide">
          <input v-model="formRequireApproval" type="checkbox" />{{ t("先让我确认再开工") }}
        </label>
        <label class="sa-field">
          <span class="sa-label">{{ t("它能不能自己动手") }}</span>
          <UiSelect v-model="formPreset" :options="presetOptions" :aria-label="t('权限档')" />
          <span class="sa-hint">{{ presetHint }}</span>
        </label>
        <div class="sa-checks">
          <label class="sa-check"><input v-model="formPush" type="checkbox" />{{ t("允许推送分支") }}</label>
          <label class="sa-check"><input v-model="formPr" type="checkbox" />{{ t("允许创建 PR") }}</label>
        </div>
        <p class="sa-hint">{{ t("推送与合并仍要你确认；不勾选时它只把改动留在本地分支。") }}</p>
        <div class="sa-actions">
          <button class="quiet-button" type="button" @click="goBack">{{ t("取消") }}</button>
          <button class="primary-button" type="button" :disabled="busy === 'submit'" @click="submitGoal">
            {{ busy === 'submit' ? t("正在交付…") : t("交给 Super-agent") }}
          </button>
        </div>
      </section>

      <!-- ── 列表 ── -->
      <section v-else-if="view === 'list'" class="sa-list">
        <p v-if="loading && !tickets.length" class="sa-muted">{{ t("正在读取工单…") }}</p>
        <p v-else-if="!tickets.length" class="sa-empty">
          <CircleAlert :size="18" :stroke-width="1.6" aria-hidden="true" />
          <span>{{ t("还没有工单。把一件复杂的活写清楚交给它，比你自己一步步推更快。") }}</span>
        </p>
        <button
          v-for="ticket in tickets"
          :key="ticket.ticket_id"
          class="sa-row"
          type="button"
          @click="openDetail(ticket)"
        >
          <span class="sa-stage" :data-stage="ticket.stage">
            <i aria-hidden="true" />{{ STAGE_LABEL[ticket.stage] || ticket.stage }}
          </span>
          <span class="sa-row-main">
            <span class="sa-row-title">{{ ticket.title || ticket.instructions || ticket.ticket_id }}</span>
            <span class="sa-row-meta">
              <span v-if="repoName(ticket.mandate?.repo_root)">{{ repoName(ticket.mandate?.repo_root) }}</span>
              <span v-if="when(ticket.updated_at)">{{ when(ticket.updated_at) }}</span>
            </span>
          </span>
        </button>
      </section>

      <!-- ── 工单详情 ── -->
      <section v-else-if="view === 'detail' && selected" class="sa-detail">
        <div class="sa-card">
          <div class="sa-detail-head">
            <span class="sa-stage" :data-stage="selected.stage">
              <i aria-hidden="true" />{{ STAGE_LABEL[selected.stage] || selected.stage }}
            </span>
            <span class="sa-muted">{{ selected.decision_reason }}</span>
          </div>
          <h2 class="sa-detail-title">{{ selected.title || selected.ticket_id }}</h2>
          <p class="sa-goal">{{ selected.instructions }}</p>
          <dl class="sa-facts">
            <div v-if="selected.mandate?.repo_root"><dt>{{ t("目录") }}</dt><dd>{{ selected.mandate.repo_root }}</dd></div>
            <div v-if="selected.mandate?.base_branch"><dt>{{ t("基线分支") }}</dt><dd>{{ selected.mandate.base_branch }}</dd></div>
            <div><dt>{{ t("推送") }}</dt><dd>{{ selected.mandate?.can_push ? t('允许') : t('不允许') }}</dd></div>
            <div><dt>{{ t("PR") }}</dt><dd>{{ selected.mandate?.can_create_pr ? t('允许') : t('不允许') }}</dd></div>
          </dl>
        </div>

        <div v-if="resultText('summary') || resultText('error')" class="sa-card">
          <h3 class="sa-section">{{ t("这次的结果") }}</h3>
          <p v-if="resultText('summary')" class="sa-report">{{ resultText('summary') }}</p>
          <p v-if="resultText('error')" class="sa-report sa-report--error">{{ resultText('error') }}</p>
          <ul v-if="resultFiles().length" class="sa-files">
            <li v-for="file in resultFiles()" :key="file">{{ file }}</li>
          </ul>
        </div>

        <div v-if="assignments.length" class="sa-card">
          <h3 class="sa-section">{{ t("执行现场") }}</h3>
          <div v-for="item in assignments" :key="item.assignment_id" class="sa-assignment">
            <span class="sa-muted">{{ item.status }}</span>
            <code v-if="item.branch">{{ item.branch }}</code>
            <code v-if="item.worktree_path">{{ item.worktree_path }}</code>
          </div>
        </div>

        <div class="sa-actions">
          <button v-if="sessionId()" class="quiet-button" type="button" @click="emit('openSession', sessionId())">
            {{ t("打开这次执行的会话") }}
          </button>
          <button
            v-if="selected.stage === 'blocked' && selected.decision_reason === 'awaiting-user-approval'"
            class="primary-button"
            type="button"
            :disabled="Boolean(busy)"
            @click="act('approve')"
          >
            <FileCheck2 :size="14" :stroke-width="1.8" aria-hidden="true" />{{ t("批准开工") }}
          </button>
          <button
            v-if="selected.stage === 'review'"
            class="primary-button"
            type="button"
            :disabled="Boolean(busy)"
            @click="act('close')"
          >
            <FileCheck2 :size="14" :stroke-width="1.8" aria-hidden="true" />{{ t("验收通过") }}
          </button>
          <button
            v-if="selected.stage === 'review'"
            class="quiet-button danger"
            type="button"
            :disabled="Boolean(busy)"
            @click="act('reject')"
          >
            {{ t("退回") }}
          </button>
          <button
            v-if="selected.stage === 'blocked' || selected.stage === 'closed'"
            class="quiet-button"
            type="button"
            :disabled="Boolean(busy)"
            @click="act('retry')"
          >
            <Undo2 :size="14" :stroke-width="1.8" aria-hidden="true" />{{ t("再跑一次") }}
          </button>
          <button
            v-if="selected.stage === 'running' || selected.stage === 'open'"
            class="quiet-button danger"
            type="button"
            :disabled="Boolean(busy)"
            @click="act('stop')"
          >
            <Square :size="13" :stroke-width="2" aria-hidden="true" />{{ t("停下") }}
          </button>
          <button class="quiet-button" type="button" @click="goBack">
            <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />{{ t("回到列表") }}
          </button>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
/* 整版界面：内容落在与会话同一条轴线上（full-area-column）。 */
.sa-view {
  --text: var(--theme-main-text);
}

.sa-page {
  padding: var(--space-4) 0 var(--space-5);
}

.sa-mobile-head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.sa-head-copy { min-width: 0; }

.sa-back {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  margin-top: 2px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  cursor: pointer;
}

.sa-back:hover { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }

h1 { margin: 0 0 2px; font-size: 17px; font-weight: 700; }
h2, h3 { margin: 0; }
p { margin: 0; }
button { font: inherit; }

.sa-subtitle { font-size: 12px; color: color-mix(in srgb, var(--text) 62%, transparent); }
.sa-muted { font-size: 12.5px; color: color-mix(in srgb, var(--text) 58%, transparent); }
.sa-hint { font-size: 12px; color: color-mix(in srgb, var(--text) 52%, transparent); }

/* 按钮：与资料库、定时任务同一套配方。 */
.quiet-button, .primary-button, .icon-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 5px var(--space-3);
  border-radius: var(--radius-sm);
  font-size: 12.5px;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out);
}

.quiet-button, .icon-button {
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  background: transparent;
  color: color-mix(in srgb, var(--text) 78%, transparent);
}

.quiet-button:hover:not(:disabled), .icon-button:hover:not(:disabled) {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.icon-button { justify-content: center; width: 28px; padding: 0; }

.quiet-button.danger { color: var(--red); border-color: color-mix(in srgb, var(--red) 35%, transparent); }
.quiet-button.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--red) 10%, transparent); color: var(--red); }

.primary-button {
  border: 1px solid transparent;
  background: var(--theme-control-background);
  color: var(--theme-control-text);
  font-weight: 600;
}

.primary-button:hover:not(:disabled) { filter: brightness(0.94); }
.primary-button:disabled, .quiet-button:disabled, .icon-button:disabled { opacity: .45; cursor: default; }

/* 卡片：主区配方，内部层级只用 soft / subtle 背景，不嵌套实色卡片。 */
.sa-card {
  padding: var(--space-3);
  border: 1px solid var(--theme-main-border);
  border-radius: var(--radius);
  background: var(--theme-main-soft-background);
  box-shadow: var(--shadow-md);
  margin-bottom: var(--space-3);
}

.sa-notice {
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--blue) 12%, transparent);
  color: color-mix(in srgb, var(--text) 85%, transparent);
  font-size: 12.5px;
}

.sa-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: var(--red);
  font-size: 12.5px;
}

.sa-error button {
  flex: none;
  min-height: 26px;
  padding: 4px var(--space-2);
  border: 1px solid currentColor;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 12px;
}

/* 表单：输入不加焦点描边，光标就是焦点提示。 */
.sa-field { display: block; margin-bottom: var(--space-3); }
.sa-label { display: block; margin-bottom: 6px; font-size: 12.5px; font-weight: 600; }

.sa-input {
  width: 100%;
  padding: 8px var(--space-2);
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--text);
  font: inherit;
  font-size: 13px;
  outline: 0;
}

.sa-input:focus, .sa-input:focus-visible { outline: 0; border-color: color-mix(in srgb, var(--text) 22%, transparent); }

.sa-textarea { resize: none; line-height: 1.55; white-space: pre-wrap; }

.sa-checks { display: flex; flex-wrap: wrap; gap: var(--space-4); margin-bottom: 6px; }
.sa-check { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; }
.sa-check--wide { display: flex; margin-bottom: var(--space-3); }

.sa-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }

/* 列表行 */
.sa-list { display: flex; flex-direction: column; gap: var(--space-1); }

.sa-empty {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) 0;
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 13px;
}

.sa-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}

.sa-row:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  border-color: color-mix(in srgb, var(--text) 10%, transparent);
}

.sa-row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.sa-row-title { font-size: 13.5px; line-height: 1.45; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sa-row-meta { display: flex; gap: var(--space-3); font-size: 12px; color: color-mix(in srgb, var(--text) 55%, transparent); }

/* 阶段：颜色之外必须有文字，色盲也能读。 */
.sa-stage {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--text) 8%, transparent);
  font-size: 11.5px;
  color: color-mix(in srgb, var(--text) 78%, transparent);
}

.sa-stage i { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

.sa-stage[data-stage='running'] { color: color-mix(in srgb, var(--text) 90%, transparent); }
.sa-stage[data-stage='running'] i { animation: sa-pulse 1.1s ease-in-out infinite; }

.sa-stage[data-stage='review'] { color: var(--blue); background: color-mix(in srgb, var(--blue) 14%, transparent); }
.sa-stage[data-stage='blocked'] { color: var(--orange); background: color-mix(in srgb, var(--orange) 14%, transparent); }
.sa-stage[data-stage='closed'] { color: color-mix(in srgb, var(--text) 60%, transparent); }

@keyframes sa-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .45; transform: scale(.8); }
}

@media (prefers-reduced-motion: reduce) {
  .sa-stage[data-stage='running'] i { animation: none; }
}

/* 详情 */
.sa-detail-head { display: flex; align-items: center; gap: var(--space-2); margin-bottom: var(--space-2); }
.sa-detail-title { font-size: 15px; font-weight: 700; margin-bottom: var(--space-2); }
.sa-goal { font-size: 13px; line-height: 1.6; white-space: pre-wrap; color: color-mix(in srgb, var(--text) 88%, transparent); }
.sa-section { font-size: 12.5px; font-weight: 700; margin-bottom: var(--space-2); }

.sa-facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px var(--space-3); margin: var(--space-3) 0 0; font-size: 12.5px; }
.sa-facts dt { color: color-mix(in srgb, var(--text) 55%, transparent); }
.sa-facts dd { margin: 0; word-break: break-all; }

.sa-report { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.sa-report--error { color: var(--red); margin-top: var(--space-2); }

.sa-files { margin: var(--space-2) 0 0; padding-left: var(--space-4); font-size: 12.5px; font-family: var(--font-mono); }

.sa-assignment { display: flex; flex-direction: column; gap: 2px; padding: var(--space-1) 0; font-size: 12.5px; }
.sa-assignment code { font-family: var(--font-mono); font-size: 12px; color: color-mix(in srgb, var(--text) 72%, transparent); word-break: break-all; }

@media (max-width: 640px) {
  .quiet-button, .primary-button { min-height: 34px; }
  .sa-row-meta { flex-wrap: wrap; }
}
</style>
