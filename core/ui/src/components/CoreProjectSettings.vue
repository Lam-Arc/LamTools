<template>
  <Teleport to="body">
    <div
      class="settings-overlay"
      @click.self="$emit('close')"
    >
      <div class="settings-card">
        <SettingsShell
          :sections="sections"
          :title="`${project.name} · 项目设置`"
          :settings-theme-style="settingsThemeStyle"
          @close="$emit('close')"
        >
          <template #default="{ activeSection }">
            <!-- 项目分区：重命名 + work root + AGENTS.md -->
            <section v-if="activeSection === 'project'" class="settings-panel">
              <header class="settings-title">
                <h1>项目</h1>
                <p>项目作用域的元信息与 AGENTS.md 指令。</p>
              </header>

              <article class="setting-card">
                <form @submit.prevent="emit('rename-project', projectNameInput)" class="core-project-rename">
                  <label>
                    <span>项目名称</span>
                    <input
                      v-model="projectNameInput"
                      class="field-input"
                      :disabled="projectActionLoading"
                    />
                  </label>
                  <div class="core-project-management-actions">
                    <button type="submit" class="small-btn primary" :disabled="projectActionLoading || !projectNameInput.trim()">
                      {{ projectActionLoading ? '保存中' : '重命名' }}
                    </button>
                  </div>
                </form>
                <p v-if="project.workRoot" class="hook-meta">工作根目录：<code>{{ project.workRoot }}</code></p>
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

            <!-- 工作流分区：项目作用域 -->
            <section v-else-if="activeSection === 'workflow'" class="settings-panel">
              <header class="settings-title">
                <h1>工作流</h1>
                <p class="settings-subhead">当前项目下的工作流，可控制是否暴露为 Agent 工具。</p>
              </header>
              <article class="setting-card">
                <div class="subhead">
                  <h3>已创建的工作流</h3>
                  <div class="subhead-actions">
                    <button class="small-btn" type="button" @click="emit('refresh-workflows')">
                      <RefreshCw :size="13" :stroke-width="1.8" aria-hidden="true" /> 刷新
                    </button>
                  </div>
                </div>
                <div v-if="workflowListLoading" class="model-empty">加载中…</div>
                <div v-else-if="workflowList.length" class="provider-list">
                  <div v-for="wf in workflowList" :key="wf.name" class="provider-group">
                    <div class="provider-head">
                      <strong>{{ wf.name }}</strong>
                      <span v-if="wf.exposed" class="tool-status ok">已暴露</span>
                      <span v-else class="tool-status">未暴露</span>
                      <div class="row-actions">
                        <button
                          type="button"
                          class="text-btn"
                          :class="{ 'is-on': wf.exposed }"
                          @click="emit('toggle-workflow-exposed', wf.name, !wf.exposed)"
                        >{{ wf.exposed ? '取消暴露' : '暴露为工具' }}</button>
                      </div>
                    </div>
                    <div class="model-list">
                      <div class="model-row">
                        <div class="model-identity">
                          <span>{{ wf.nodes.length }} 个节点 · {{ wf.edges.length }} 条连线</span>
                          <span v-if="wf.description" class="hook-meta">{{ wf.description }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <p v-else class="model-empty">当前项目下暂无工作流。</p>
              </article>
            </section>
          </template>
        </SettingsShell>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import {
  gradientFromStops,
  relativeLuminance,
  type ThemeData,
} from '../helpers/theme'
import SettingsShell, { type SettingsSection } from './SettingsShell.vue'
import CoreSubAgentEditor from './CoreSubAgentEditor.vue'
import type { CoreSettingsModel, WorkflowListItem } from './CoreSettings.vue'

export interface CoreProjectSettingsProject {
  id: string
  name: string
  workRoot?: string
}

const props = defineProps<{
  project: CoreProjectSettingsProject
  theme: ThemeData
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
  models?: CoreSettingsModel[]
  workflows?: WorkflowListItem[]
  workflowListLoading?: boolean
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
  'save-agents': [content: string]
  'refresh-agents': []
  'refresh-workflows': []
  'toggle-workflow-exposed': [name: string, exposed: boolean]
}>()

const sections: SettingsSection[] = [
  { id: 'project', label: '项目', icon: 'folder' },
  { id: 'subagent', label: 'Sub agent', icon: 'bot' },
  { id: 'workflow', label: '工作流', icon: 'workflow' },
]

const workflowList = computed(() => props.workflows ?? [])

// Local mirrors of draft inputs so editing doesn't mutate parent state per keystroke.
const projectNameInput = ref(props.projectNameDraft)
const agentsDraft = ref(props.agentsContent)

watch(() => props.projectNameDraft, (value) => { projectNameInput.value = value })
watch(() => props.agentsContent, (value) => { agentsDraft.value = value })
// When switching projects (id changes), resync drafts.
watch(() => props.project.id, () => {
  projectNameInput.value = props.projectNameDraft
  agentsDraft.value = props.agentsContent
})

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

onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
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
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
  padding: 0 9px;
}

.core-project-management-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

.small-btn.primary {
  background: var(--settings-control-background, #343331);
  color: var(--settings-control-text, var(--text));
}

.guide-editor {
  width: 100%;
  min-height: 220px;
  margin-top: 10px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--settings-main-text, #fff)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, #343331) 70%, transparent);
  color: var(--settings-control-text, var(--settings-main-text, #fff));
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
