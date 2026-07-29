<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>Hooks</h1>
      <p>管理事件钩子。未信任的 Hook 不会执行，需在此审核后启用。</p>
    </header>

    <p v-if="error" class="hook-error">{{ error }}</p>

    <article class="setting-card agent-toggle">
      <div class="agent-toggle-row">
        <div>
          <h3>允许 Agent 自建 Hook</h3>
          <p>开启后，系统提示词会注入 hooks.json 的编写指引，Agent 可按用户要求自行创建事件钩子。</p>
        </div>
        <button
          class="text-btn"
          :class="{ 'is-on': allowAgentCreateHooks }"
          type="button"
          @click="toggleAllowCreate"
        >{{ allowAgentCreateHooks ? '已开启' : '已关闭' }}</button>
      </div>
    </article>

    <div class="subhead">
      <span class="muted">{{ loading ? '加载中…' : `共 ${totalCount} 个 · 已信任 ${trustedCount}${trustableCount ? ` · 待审核 ${trustableCount}` : ''}` }}</span>
      <div class="row-actions">
        <button
          v-if="!showHookForm && !showConfig"
          class="small-btn primary"
          type="button"
          @click="openHookForm"
        >新增 Hook</button>
        <button
          v-if="trustableCount > 0"
          class="small-btn"
          type="button"
          @click="trustAll"
        >全部信任</button>
        <button
          class="text-btn"
          type="button"
          @click="toggleConfigView"
        >{{ showConfig ? '返回列表' : '原始配置' }}</button>
      </div>
    </div>

    <!-- Hook creation form -->
    <section v-if="showHookForm" class="settings-editor hook-form">
      <div class="subhead">
        <h3>新增 Hook</h3>
      </div>
      <form class="config-form" @submit.prevent="saveHookForm">
        <label class="field">事件
          <select v-model="hookForm.event">
            <option v-for="ev in eventOrder" :key="ev" :value="ev">{{ eventLabel(ev) }} ({{ ev }})</option>
          </select>
        </label>
        <label class="field">匹配器
          <input
            v-model.trim="hookForm.matcher"
            placeholder="* 或工具名，多个用 | 分隔"
          />
        </label>
        <label class="field">处理器类型
          <select v-model="hookForm.handlerType">
            <option value="command">command (Shell 命令)</option>
            <option value="http">http (HTTP 请求)</option>
            <option value="mcp">mcp (MCP 工具)</option>
            <option value="prompt">prompt (内联提示)</option>
          </select>
        </label>
        <label class="field">超时 (秒)
          <input
            v-model.number="hookForm.timeout"
            type="number"
            min="1"
            max="300"
          />
        </label>
        <label v-if="hookForm.handlerType === 'command'" class="field field-wide">命令
          <textarea
            v-model="hookForm.command"
            rows="3"
            spellcheck="false"
            placeholder="e.g. node &quot;path/to/hook.mjs&quot;"
          />
        </label>
        <label v-if="hookForm.handlerType === 'http'" class="field field-wide">URL
          <input
            v-model.trim="hookForm.url"
            type="url"
            placeholder="https://example.com/hook"
          />
        </label>
        <label v-if="hookForm.handlerType === 'mcp'" class="field field-wide">MCP 工具名
          <input
            v-model.trim="hookForm.tool"
            placeholder="mcp_server_tool_name"
          />
        </label>
        <label v-if="hookForm.handlerType === 'prompt'" class="field field-wide">提示文本
          <textarea
            v-model="hookForm.prompt"
            rows="3"
            spellcheck="false"
            placeholder="注入到上下文的提示文本"
          />
        </label>
        <label class="field field-wide">状态消息 (可选)
          <input
            v-model.trim="hookForm.statusMessage"
            placeholder="执行前显示给用户的状态文字"
          />
        </label>
        <label class="field field-wide checkbox-inline">
          <span>hook 失败时阻断执行</span>
          <input v-model="hookForm.required" type="checkbox" />
        </label>
        <div class="editor-actions field-wide">
          <button type="button" class="small-btn quiet" @click="showHookForm = false">取消</button>
          <button class="small-btn primary" type="submit" :disabled="hookFormSaving">
            {{ hookFormSaving ? '保存中…' : '添加' }}
          </button>
        </div>
      </form>
    </section>

    <!-- Config editor view -->
    <article v-if="showConfig" class="setting-card hook-config">
      <h3>hooks.json</h3>
      <textarea
        v-model="configDraft"
        class="hook-config-textarea"
        spellcheck="false"
        aria-label="hooks.json 内容"
        :disabled="configSaving"
      />
      <div class="subhead">
        <span class="muted" :class="{ 'hook-config-error': configError }">{{ configMessage || '修改后需重启后端生效。' }}</span>
        <div class="row-actions">
          <button class="text-btn" type="button" @click="revertConfig">还原</button>
          <button
            class="small-btn"
            type="button"
            :disabled="configSaving"
            @click="saveConfig"
          >{{ configSaving ? '保存中…' : '保存' }}</button>
        </div>
      </div>
    </article>

    <!-- Empty state -->
    <article v-else-if="!loading && !hooks.length && !showHookForm" class="setting-card">
      <p>未发现任何 Hook。点击「新增 Hook」创建事件钩子，或切换到「原始配置」手写 JSON。</p>
    </article>

    <!-- Hook list -->
    <div v-else-if="!showConfig && !showHookForm" class="provider-list">
      <section
        v-for="(group, event) in groupedHooks"
        :key="event"
        class="provider-group"
      >
        <header class="provider-head">
          <div class="provider-identity">
            <strong>{{ eventLabel(event) }}</strong>
            <span>{{ group.length }} 个</span>
          </div>
        </header>

        <div class="model-list">
          <div
            v-for="hook in group"
            :key="hook.id"
            class="model-row"
            :class="{ 'is-pending': !hook.trusted }"
          >
            <div class="model-identity">
              <strong>{{ hook.matcher === '*' ? '全部工具' : hook.matcher }}</strong>
              <span class="hook-meta">{{ hook.handler_type }} · {{ hook.source_name || hook.source }}</span>
              <span v-if="hook.command" class="skill-path">{{ hook.command }}</span>
            </div>
            <div class="row-actions">
              <span class="hook-status" :class="hook.trusted ? 'is-trusted' : 'is-pending-text'">{{ hook.trusted ? '已信任' : '待审核' }}</span>
              <button
                v-if="!hook.trusted"
                class="text-btn is-on"
                type="button"
                @click="trustHook(hook.id)"
              >信任</button>
              <button
                v-else
                class="text-btn"
                type="button"
                @click="untrustHook(hook.id)"
              >取消</button>
              <button
                v-if="canDelete(hook)"
                class="text-btn danger"
                type="button"
                @click="deleteHook(hook.id)"
              >删除</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CoreHookItem, CoreHookListPayload } from '../types'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const hooks = ref<CoreHookItem[]>([])
const loading = ref(true)
const error = ref('')
const totalCount = ref(0)
const trustedCount = ref(0)
const trustableCount = ref(0)
const allowAgentCreateHooks = ref(false)

const showConfig = ref(false)
const configDraft = ref('')
const configOriginal = ref('')
const configSaving = ref(false)
const configMessage = ref('')
const configError = ref(false)

// ── Hook creation form ─────────────────────────────────────────────────

interface HookFormState {
  event: string
  matcher: string
  handlerType: string
  command: string
  url: string
  tool: string
  prompt: string
  timeout: number
  statusMessage: string
  required: boolean
}

const showHookForm = ref(false)
const hookFormSaving = ref(false)
const defaultHookForm = (): HookFormState => ({
  event: 'PostToolUse',
  matcher: '*',
  handlerType: 'command',
  command: '',
  url: '',
  tool: '',
  prompt: '',
  timeout: 10,
  statusMessage: '',
  required: false,
})
const hookForm = ref<HookFormState>(defaultHookForm())

const eventOrder = [
  'SessionStart',
  'UserPromptSubmit',
  'PreToolUse',
  'PermissionRequest',
  'PostToolUse',
  'PostToolUseFailure',
  'Stop',
]

const groupedHooks = computed(() => {
  const groups: Record<string, CoreHookItem[]> = {}
  for (const event of eventOrder) groups[event] = []
  for (const hook of hooks.value) {
    const ev = hook.event || 'PreToolUse'
    ;(groups[ev] || (groups[ev] = [])).push(hook)
  }
  const result: Record<string, CoreHookItem[]> = {}
  for (const [key, list] of Object.entries(groups)) {
    if (list.length) result[key] = list
  }
  return result
})

function eventLabel(event: string): string {
  return ({
    SessionStart: '会话开始',
    UserPromptSubmit: '用户提交',
    PreToolUse: '工具调用前',
    PermissionRequest: '权限请求',
    PostToolUse: '工具调用后',
    PostToolUseFailure: '工具调用失败',
    Stop: '会话停止',
  } as Record<string, string>)[event] || event
}

function canDelete(hook: CoreHookItem): boolean {
  // Only allow deleting hooks from the unified config file (source=user, source_name=config)
  return hook.source === 'user' && hook.source_name === 'config'
}

async function fetchHooks() {
  loading.value = true
  error.value = ''
  try {
    const [hookResult, settingsResult] = await Promise.all([
      props.requestRpc('hook.list'),
      props.requestRpc('settings.get', { namespace: 'core.runtimeControls' }),
    ])
    const result = hookResult as unknown as CoreHookListPayload
    hooks.value = result.hooks || []
    totalCount.value = result.total_count || 0
    trustedCount.value = result.trusted_count || 0
    trustableCount.value = result.trustable_count || 0
    const value = settingsResult.value as Record<string, unknown> | undefined
    allowAgentCreateHooks.value = value ? !!value.allow_agent_create_hooks : false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function toggleAllowCreate() {
  const next = !allowAgentCreateHooks.value
  allowAgentCreateHooks.value = next
  try {
    await props.requestRpc('settings.update', {
      namespace: 'core.runtimeControls',
      value: { allow_agent_create_hooks: next },
    })
  } catch (e) {
    allowAgentCreateHooks.value = !next
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function trustHook(id: string) {
  try {
    await props.requestRpc('hook.trust', { hook_id: id })
    const idx = hooks.value.findIndex((h) => h.id === id)
    if (idx >= 0) {
      hooks.value[idx] = { ...hooks.value[idx], trusted: true, status: 'trusted' }
      trustedCount.value++
      trustableCount.value = Math.max(0, trustableCount.value - 1)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function untrustHook(id: string) {
  try {
    await props.requestRpc('hook.untrust', { hook_id: id })
    const idx = hooks.value.findIndex((h) => h.id === id)
    if (idx >= 0) {
      hooks.value[idx] = { ...hooks.value[idx], trusted: false, status: 'pending_review' }
      trustedCount.value = Math.max(0, trustedCount.value - 1)
      trustableCount.value++
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function trustAll() {
  try {
    await props.requestRpc('hook.trust_all')
    hooks.value = hooks.value.map((h) => ({
      ...h,
      trusted: true,
      status: h.status === 'pending_review' ? 'trusted' : h.status,
    }))
    trustedCount.value = hooks.value.length
    trustableCount.value = 0
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function deleteHook(id: string) {
  try {
    await props.requestRpc('hook.delete', { hook_id: id })
    hooks.value = hooks.value.filter((h) => h.id !== id)
    totalCount.value = Math.max(0, totalCount.value - 1)
    trustedCount.value = Math.max(0, trustedCount.value - 1)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// ── Hook form ──────────────────────────────────────────────────────────

function openHookForm() {
  hookForm.value = defaultHookForm()
  showHookForm.value = true
}

async function saveHookForm() {
  const f = hookForm.value
  // Build the handler object
  const handler: Record<string, unknown> = {
    type: f.handlerType,
    timeout: f.timeout,
  }
  if (f.statusMessage) handler.statusMessage = f.statusMessage
  if (f.required) handler.required = true
  if (f.handlerType === 'command') {
    if (!f.command.trim()) { error.value = 'command 不能为空'; return }
    handler.command = f.command
  } else if (f.handlerType === 'http') {
    if (!f.url.trim()) { error.value = 'URL 不能为空'; return }
    handler.url = f.url
  } else if (f.handlerType === 'mcp') {
    if (!f.tool.trim()) { error.value = 'MCP 工具名不能为空'; return }
    handler.tool = f.tool
  } else if (f.handlerType === 'prompt') {
    if (!f.prompt.trim()) { error.value = '提示文本不能为空'; return }
    handler.prompt = f.prompt
  }

  hookFormSaving.value = true
  error.value = ''
  try {
    // 1. Read current config
    const getResult = await props.requestRpc('hook.config.get')
    const rawContent = typeof getResult.content === 'string' ? getResult.content : '{}'
    let config: Record<string, unknown>
    try {
      config = JSON.parse(rawContent) || {}
    } catch {
      config = {}
    }
    // 2. Merge the new hook
    const hooksSection = (config.hooks as Record<string, unknown[]>) || {}
    if (!hooksSection[f.event] || !Array.isArray(hooksSection[f.event])) {
      hooksSection[f.event] = []
    }
    // Find existing group with same matcher, or create one
    const groups = hooksSection[f.event] as Array<Record<string, unknown>>
    let group = groups.find((g) => g.matcher === f.matcher)
    if (!group) {
      group = { matcher: f.matcher, hooks: [] }
      groups.push(group)
    }
    const handlers = (group.hooks as unknown[]) || []
    handlers.push(handler)
    group.hooks = handlers
    config.hooks = hooksSection
    // 3. Save back
    const newContent = JSON.stringify(config, null, 2)
    await props.requestRpc('hook.config.update', { content: newContent })
    // 4. Close form & refresh
    showHookForm.value = false
    await fetchHooks()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    hookFormSaving.value = false
  }
}

// ── Config raw editor ──────────────────────────────────────────────────

async function toggleConfigView() {
  showConfig.value = !showConfig.value
  showHookForm.value = false
  configMessage.value = ''
  configError.value = false
  if (showConfig.value && !configDraft.value) {
    try {
      const result = await props.requestRpc('hook.config.get')
      const content = typeof result.content === 'string' ? result.content : '{}'
      try {
        configDraft.value = JSON.stringify(JSON.parse(content), null, 2)
      } catch {
        configDraft.value = content
      }
      configOriginal.value = configDraft.value
    } catch (e) {
      configMessage.value = e instanceof Error ? e.message : String(e)
      configError.value = true
    }
  }
}

function revertConfig() {
  configDraft.value = configOriginal.value
  configMessage.value = ''
  configError.value = false
}

async function saveConfig() {
  configSaving.value = true
  configMessage.value = ''
  configError.value = false
  try {
    await props.requestRpc('hook.config.update', { content: configDraft.value })
    configOriginal.value = configDraft.value
    configMessage.value = '已保存，重启后端后生效。'
    await fetchHooks()
  } catch (e) {
    configMessage.value = e instanceof Error ? e.message : String(e)
    configError.value = true
  } finally {
    configSaving.value = false
  }
}

onMounted(fetchHooks)
</script>

<style scoped>
.agent-toggle {
  padding: 12px 14px;
}

.agent-toggle-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
}

.agent-toggle h3 {
  margin: 0 0 4px;
  font-size: 14px;
}

.agent-toggle p {
  margin: 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.5;
}

.hook-error {
  margin: 0;
  padding: 9px 12px;
  border-radius: var(--radius);
  border: 1px solid color-mix(in srgb, var(--red) 22%, transparent);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 64%, var(--settings-main-text, #fff));
  font-size: 13px;
}

.skill-path {
  font-family: var(--font-mono);
  font-size: 11px;
  opacity: .7;
  margin-top: 2px !important;
}

.hook-meta {
  text-transform: uppercase;
  letter-spacing: .04em;
  font-size: 11px !important;
}

.model-row.is-pending {
  opacity: .7;
}

.hook-status {
  font-size: 12px;
  color: var(--muted);
}

.hook-status.is-trusted {
  color: var(--green);
}

.hook-status.is-pending-text {
  color: var(--orange);
}

.text-btn.is-on {
  color: var(--green);
}

.hook-config h3 {
  margin: 0;
}

.hook-config-textarea {
  box-sizing: border-box;
  width: 100%;
  min-height: 280px;
  resize: vertical;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 18%, transparent);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 6%, transparent);
  color: var(--settings-main-text, var(--text));
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  padding: 12px;
}

.hook-config-error {
  color: var(--red) !important;
}

.hook-form .config-form textarea {
  min-height: 72px;
}

.hook-form input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  min-width: 14px;
  min-height: 14px;
  margin: 0;
  padding: 0;
  border: 1.5px solid color-mix(in srgb, var(--settings-main-text, #fff) 30%, transparent);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  position: relative;
  flex-shrink: 0;
  transition: border-color .15s, background .15s;
}

.hook-form input[type="checkbox"]:hover {
  border-color: color-mix(in srgb, var(--settings-main-text, #fff) 55%, transparent);
}

.hook-form input[type="checkbox"]:checked {
  border-color: var(--green, #32d17d);
  background: var(--green, #32d17d);
}

.hook-form input[type="checkbox"]:checked::after {
  content: '';
  position: absolute;
  top: 0px;
  left: 3px;
  width: 3px;
  height: 7px;
  border: solid #fff;
  border-width: 0 1.5px 1.5px 0;
  transform: rotate(45deg);
}

.checkbox-inline {
  display: flex !important;
  flex-direction: row !important;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.hook-form .editor-actions {
  gap: 14px;
}
</style>
