<template>
  <Teleport to="body">
    <div
      ref="settingsOverlayEl"
      class="settings-overlay"
    >
      <div ref="settingsCardEl" class="settings-card">
        <SettingsShell
          :sections="sections"
          :title="`${project.name} · 项目设置`"
          :settings-theme-style="settingsThemeStyle"
          @close="$emit('close')"
        >
          <template #default="{ activeSection }">
            <!-- 项目分区：即时保存的名称/外观 + work root + AGENTS.md -->
            <section v-if="activeSection === 'project'" class="settings-panel">
              <header class="settings-title">
                <h1>项目</h1>
                <p>项目作用域的元信息与 AGENTS.md 指令。</p>
              </header>

              <article class="setting-card">
                <form class="core-project-rename" @submit.prevent="commitProjectName">
                  <label>
                    <span>项目名称</span>
                    <input
                      v-model="projectNameInput"
                      class="field-input"
                      data-project-name-input
                      :disabled="projectActionLoading"
                      @change="commitProjectName"
                      @blur="commitProjectName"
                      @keydown.enter.prevent="commitProjectName"
                    />
                  </label>
                </form>
                <div class="core-project-visual-settings">
                  <div class="core-project-visual-heading">
                    <span>项目外观</span>
                    <small>用于侧边栏中的项目辨识。</small>
                  </div>
                  <ProjectVisualPicker
                    :icon-key="projectIconKey"
                    :color-key="projectColorKey"
                    :disabled="projectActionLoading"
                    @update:icon-key="selectProjectIcon"
                    @update:color-key="selectProjectColor"
                  />
                </div>
                <p v-if="projectActionLoading" class="project-save-status" role="status">正在保存项目更改…</p>
                <p v-if="project.workRoot" class="hook-meta">工作根目录：<code>{{ project.workRoot }}</code></p>
              </article>

              <article v-if="sessionId" class="setting-card project-session-card" data-project-session>
                <div class="project-session-heading">
                  <div class="project-session-details">
                    <span>当前会话</span>
                    <code data-project-session-id>#{{ sessionId.slice(0, 8) }}</code>
                  </div>
                  <button
                    class="text-btn project-session-copy"
                    :class="{ 'is-copied': copiedSessionId }"
                    type="button"
                    data-project-session-copy
                    :data-copied="copiedSessionId ? '' : undefined"
                    :aria-label="copiedSessionId ? '已复制完整会话 ID' : '复制完整会话 ID'"
                    :title="copiedSessionId ? '已复制完整会话 ID' : '复制完整会话 ID'"
                    @click="copySessionId"
                  >
                    <Check v-if="copiedSessionId" :size="14" :stroke-width="1.8" aria-hidden="true" />
                    <Copy v-else :size="14" :stroke-width="1.8" aria-hidden="true" />
                    <span>{{ copiedSessionId ? '已复制' : '复制完整 ID' }}</span>
                  </button>
                </div>
              </article>

              <article class="setting-card">
                <div class="subhead">
                  <span class="muted subhead-title">
                    项目规则
                    <span class="subhead-sub">AGENTS.md</span>
                  </span>
                  <div class="subhead-actions">
                    <button class="text-btn" type="button" :disabled="agentsLoading" @click="emit('refresh-agents')">刷新</button>
                    <button class="text-btn" type="button" :disabled="agentsLoading || agentsSaving" @click="emit('save-agents', agentsDraft)">保存</button>
                  </div>
                </div>
                <textarea
                  v-model="agentsDraft"
                  class="guide-editor"
                  rows="14"
                  spellcheck="false"
                  :placeholder="agentsLoading ? '加载中…' : '# 项目级约束\n项目专属指令，会叠加在全局约束之上…'"
                  :disabled="agentsLoading"
                />
                <p v-if="agentsError" class="skill-error" role="alert">{{ agentsError }}</p>
                <p class="hook-meta">保存到 <code>{{ project.workRoot || '(项目根)' }}/AGENTS.md</code>。注入顺序：先全局约束（.lam/core/config/AGENTS.md），再本文件，两者相加。全局约束在「设置 → 项目规则」内编辑。</p>
              </article>

              <p v-if="projectActionError" class="skill-error" role="alert">{{ projectActionError }}</p>
            </section>

            <!-- Sub agent 分区：项目作用域 -->
            <section v-else-if="activeSection === 'subagent'" class="settings-panel">
              <header class="settings-title">
                <h1>Sub agent</h1>
                <p>项目作用域的 sub_agent 配置，会覆盖全局配置。留空保存可回退到继承的全局 / 内置默认。</p>
              </header>
              <CoreSubAgentEditor
                :request-rpc="requestRpc"
                :models="models"
                scope="project"
                :work-root="project.workRoot || ''"
              />
            </section>

          </template>
        </SettingsShell>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { Check, Copy } from 'lucide-vue-next'
import {
  gradientFromStops,
  relativeLuminance,
  type ThemeData,
} from '../helpers/theme'
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import CoreSubAgentEditor from './CoreSubAgentEditor.vue'
import ProjectVisualPicker from './ProjectVisualPicker.vue'
import type { CoreSettingsModel } from './CoreSettings.vue'
import { useOutsidePointerDismiss } from '../composables/useOutsidePointerDismiss'
import { copyText } from '../helpers/clipboard'
import type { CoreProjectColorKey, CoreProjectIconKey } from '../projects/types'

export interface CoreProjectSettingsProject {
  id: string
  name: string
  workRoot?: string
  iconKey: CoreProjectIconKey
  colorKey: CoreProjectColorKey
}

const props = defineProps<{
  project: CoreProjectSettingsProject
  sessionId?: string | null
  theme: ThemeData
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  models?: CoreSettingsModel[]
  projectNameDraft: string
  agentsContent: string
  agentsLoading: boolean
  agentsSaving?: boolean
  agentsError: string
  projectActionLoading: boolean
  projectActionError: string
}>()

const emit = defineEmits<{
  close: []
  'rename-project': [name: string]
  'update-project-visual': [iconKey: CoreProjectIconKey, colorKey: CoreProjectColorKey]
  'save-agents': [content: string]
  'refresh-agents': []
}>()

const sections: SettingsSection[] = [
  { id: 'project', label: '项目', icon: 'folder' },
  { id: 'subagent', label: 'Sub agent', icon: 'bot' },
]

// Local mirrors of draft inputs so editing doesn't mutate parent state per keystroke.
const projectNameInput = ref(props.projectNameDraft)
const projectIconKey = ref<CoreProjectIconKey>(props.project.iconKey)
const projectColorKey = ref<CoreProjectColorKey>(props.project.colorKey)
const pendingName = ref<string | null>(null)
const pendingVisual = ref<string | null>(null)
const agentsDraft = ref(props.agentsContent)
const copiedSessionId = ref(false)
let copiedSessionIdTimer: ReturnType<typeof setTimeout> | null = null
const settingsOverlayEl = ref<HTMLElement | null>(null)
const settingsCardEl = ref<HTMLElement | null>(null)

watch(() => props.projectNameDraft, (value) => { projectNameInput.value = value })
watch(() => props.project.iconKey, (value) => { projectIconKey.value = value })
watch(() => props.project.colorKey, (value) => { projectColorKey.value = value })
watch(() => props.agentsContent, (value) => { agentsDraft.value = value })
watch(() => props.sessionId, () => {
  copiedSessionId.value = false
  if (copiedSessionIdTimer) clearTimeout(copiedSessionIdTimer)
  copiedSessionIdTimer = null
})
watch(() => props.projectActionLoading, (loading) => {
  if (loading) return
  pendingName.value = null
  pendingVisual.value = null
})
// When switching projects (id changes), resync drafts.
watch(() => props.project.id, () => {
  projectNameInput.value = props.projectNameDraft
  projectIconKey.value = props.project.iconKey
  projectColorKey.value = props.project.colorKey
  pendingName.value = null
  pendingVisual.value = null
  agentsDraft.value = props.agentsContent
})

function commitProjectName(): void {
  const name = projectNameInput.value.trim()
  if (!name) {
    projectNameInput.value = props.project.name
    return
  }
  if (name === props.project.name || name === pendingName.value || props.projectActionLoading) return
  projectNameInput.value = name
  pendingName.value = name
  emit('rename-project', name)
}

function commitProjectVisual(iconKey: CoreProjectIconKey, colorKey: CoreProjectColorKey): void {
  const next = `${iconKey}:${colorKey}`
  const current = `${props.project.iconKey}:${props.project.colorKey}`
  if (next === current || next === pendingVisual.value || props.projectActionLoading) return
  pendingVisual.value = next
  emit('update-project-visual', iconKey, colorKey)
}

function selectProjectIcon(iconKey: CoreProjectIconKey): void {
  projectIconKey.value = iconKey
  commitProjectVisual(iconKey, projectColorKey.value)
}

function selectProjectColor(colorKey: CoreProjectColorKey): void {
  projectColorKey.value = colorKey
  commitProjectVisual(projectIconKey.value, colorKey)
}

async function copySessionId(): Promise<void> {
  const sessionId = props.sessionId
  if (!sessionId) return
  try {
    await copyText(sessionId)
  } catch {
    // Clipboard access can be unavailable in an embedded desktop context.
    return
  }
  copiedSessionId.value = true
  if (copiedSessionIdTimer) clearTimeout(copiedSessionIdTimer)
  copiedSessionIdTimer = setTimeout(() => {
    copiedSessionId.value = false
    copiedSessionIdTimer = null
  }, 1400)
}

const settingsThemeStyle = computed(() => {
  const lightMain = relativeLuminance(props.theme.mainText) < 0.45
  return {
    '--settings-backdrop-background': gradientFromStops(
      props.theme.backdropAngle,
      props.theme.backdropStops,
      1,
    ),
    '--settings-backdrop-text': props.theme.backdropText,
    '--settings-main-background': gradientFromStops(
      props.theme.mainAngle,
      props.theme.mainStops,
      props.theme.mainOpacity,
    ),
    '--settings-main-text': props.theme.mainText,
    // main 区首停点纯色：卡片实色底（渐变值不可用于 color-mix）
    '--settings-main-solid': props.theme.mainStops[0]?.color || '#111111',
    // 卡片/浮层面板：main 实色 + 文字色 4% 微调，不透明、与内容区有层级
    '--settings-card-background': 'color-mix(in srgb, var(--settings-main-solid) 96%, var(--settings-main-text) 4%)',
    '--settings-card-text': props.theme.mainText,
    '--settings-control-background': gradientFromStops(
      props.theme.controlAngle,
      props.theme.controlStops,
      props.theme.controlOpacity,
    ),
    '--settings-control-text': props.theme.controlText,
    // control 区首停点纯色：color-mix 混透明用的实色底（渐变值不可用于 color-mix）
    '--settings-control-solid': props.theme.controlStops[0]?.color || '#3a3834',
    // 暗色分支不重复字面量：layout.css 的 --settings-* fallback 即 :root 真值（单一来源）
    ...(lightMain ? {
      '--settings-panel-2': '#f0efeb',
      '--settings-line': '#d4d0cc',
      '--settings-muted': '#8a8580',
    } : {}),
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

useOutsidePointerDismiss({
  overlay: settingsOverlayEl,
  card: settingsCardEl,
  onDismiss: () => emit('close'),
})

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => {
  document.removeEventListener('keydown', onKeydown)
  if (copiedSessionIdTimer) clearTimeout(copiedSessionIdTimer)
})
</script>

<style scoped>
/* ── Overlay — full-viewport backdrop with centered card (mirrors CoreSettings) ── */
.settings-overlay {
  position: fixed;
  inset: var(--titlebar-offset, 36px) 0 0 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(3px);
  -webkit-backdrop-filter: blur(3px);
}

.settings-card {
  position: relative;
  width: min(960px, calc(100vw - 48px));
  max-height: calc(100dvh - var(--titlebar-offset, 36px) - 48px);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #f2efeb) 12%, transparent);
  border-radius: var(--radius-lg);
  background: var(--settings-card-background, var(--theme-main-background, #111111));
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

@media (max-width: 640px) {
  .settings-card {
    width: 100vw;
    max-height: calc(100dvh - var(--titlebar-offset, 36px));
    border-radius: 0;
  }
}

/* ── Project rename form ── */
.core-project-rename {
  display: grid;
  gap: 6px;
}

.core-project-rename label {
  display: grid;
  gap: 6px;
  color: color-mix(in srgb, var(--settings-main-text, #fff) 72%, transparent);
  font-size: 12px;
}

.field-input {
  min-height: 36px;
  border: 1px solid color-mix(in srgb, var(--theme-composer-text) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-composer-background) 70%, transparent);
  color: var(--theme-composer-text);
  caret-color: var(--theme-composer-text);
  padding: 0 9px;
}

.core-project-visual-settings {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding-top: var(--space-4);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text) 10%, transparent);
}

.core-project-visual-heading {
  display: grid;
  gap: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text) 72%, transparent);
  font-size: 12px;
}

.core-project-visual-heading small {
  color: color-mix(in srgb, var(--settings-main-text) 52%, transparent);
  font-size: 11px;
}

.project-save-status {
  margin: var(--space-3) 0 0;
  color: color-mix(in srgb, var(--settings-main-text) 62%, transparent);
  font-size: 12px;
}

.project-session-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.project-session-details {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text) 65%, transparent);
  font-size: 12px;
}

.project-session-details code {
  color: var(--settings-main-text);
  font-family: var(--font-mono);
  font-size: 12px;
}

.project-session-copy {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--space-1);
  padding-inline: var(--space-2);
  color: color-mix(in srgb, var(--settings-main-text) 65%, transparent);
}

.project-session-copy:hover {
  background: color-mix(in srgb, var(--settings-main-text) var(--alpha-hover), transparent);
  color: var(--settings-main-text);
}

.project-session-copy.is-copied {
  color: var(--green);
}

.guide-editor {
  width: 100%;
  min-height: 220px;
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

.subhead-actions {
  display: flex;
  gap: 6px;
}

.subhead-title {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.subhead-sub {
  font-size: 11px;
  color: color-mix(in srgb, var(--muted) 70%, transparent);
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
}

.hook-meta {
  margin-top: 10px;
  font-size: 12px;
  color: var(--muted);
  line-height: 1.5;
}

.skill-error {
  margin: 8px 0 0;
  color: var(--red);
  font-size: 12px;
  line-height: 1.35;
}
</style>
