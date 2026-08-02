<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>Skills</h1>
      <p>管理已发现的 Skills，禁用后不会出现在斜杠命令中。</p>
    </header>

    <p v-if="error" class="skill-error">{{ error }}</p>

    <article class="setting-card agent-toggle">
      <div class="agent-toggle-row">
        <div>
          <h3>允许 Agent 安装 Skill</h3>
          <p>开启后，系统提示词会注入创建 SKILL.md 的指引，Agent 可按用户要求自行编写新技能。</p>
        </div>
        <button
          class="text-btn"
          :class="{ 'is-on': allowAgentInstallSkill }"
          type="button"
          @click="toggleAllowInstall"
        >{{ allowAgentInstallSkill ? '已开启' : '已关闭' }}</button>
      </div>
    </article>

    <div class="subhead">
      <span class="muted">{{ loading ? '加载中…' : `共 ${skills.length} 个 · 已启用 ${enabledCount}` }}</span>
      <button class="text-btn" type="button" @click="fetchSkills">刷新</button>
    </div>

    <article v-if="!loading && !skills.length" class="setting-card">
      <p>未发现任何 Skill。将 SKILL.md 放入 <code>.lam/skills/</code> 目录即可注册。</p>
    </article>

    <div v-else class="provider-list">
      <section
        v-for="(group, source) in groupedSkills"
        :key="source"
        class="provider-group"
      >
        <header class="provider-head">
          <div class="provider-identity">
            <strong>{{ sourceLabel(source) }}</strong>
            <span>{{ group.length }} 个</span>
          </div>
        </header>

        <div class="model-list">
          <div
            v-for="skill in group"
            :key="skill.name"
            class="model-row"
            :class="{ 'is-disabled': !skill.enabled }"
          >
            <div class="model-identity">
              <strong>{{ skill.name }}</strong>
              <span>{{ skill.description }}</span>
              <span class="skill-path">{{ skill.location }}</span>
            </div>
            <div class="row-actions">
              <button
                class="text-btn"
                :class="{ 'is-on': skill.enabled }"
                type="button"
                @click="toggleSkill(skill.name, !skill.enabled)"
              >{{ skill.enabled ? '已启用' : '已禁用' }}</button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { CoreSkillItem } from '../types'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const skills = ref<CoreSkillItem[]>([])
const loading = ref(true)
const error = ref('')
const allowAgentInstallSkill = ref(false)

const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)

const groupedSkills = computed(() => {
  const groups: Record<string, CoreSkillItem[]> = {
    project: [],
    user: [],
    core: [],
    plugin: [],
  }
  for (const skill of skills.value) {
    const src = skill.source || 'core'
    ;(groups[src] || (groups[src] = [])).push(skill)
  }
  const result: Record<string, CoreSkillItem[]> = {}
  for (const [key, list] of Object.entries(groups)) {
    if (list.length) result[key] = list
  }
  return result
})

function sourceLabel(source: string): string {
  return ({ project: '项目', user: '用户', core: '核心', plugin: '插件' } as Record<string, string>)[source] || source
}

async function fetchSkills() {
  loading.value = true
  error.value = ''
  try {
    const [skillResult, settingsResult] = await Promise.all([
      props.requestRpc('skill.list'),
      props.requestRpc('settings.get', { namespace: 'core.runtimeControls' }),
    ])
    skills.value = (skillResult.skills as CoreSkillItem[]) || []
    const value = settingsResult.value as Record<string, unknown> | undefined
    allowAgentInstallSkill.value = value ? !!value.allow_agent_install_skill : false
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function toggleAllowInstall() {
  const next = !allowAgentInstallSkill.value
  allowAgentInstallSkill.value = next
  try {
    await props.requestRpc('settings.update', {
      namespace: 'core.runtimeControls',
      value: { allow_agent_install_skill: next },
    })
  } catch (e) {
    allowAgentInstallSkill.value = !next
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function toggleSkill(name: string, enable: boolean) {
  try {
    await props.requestRpc(enable ? 'skill.enable' : 'skill.disable', { name })
    const idx = skills.value.findIndex((s) => s.name === name)
    if (idx >= 0) skills.value[idx] = { ...skills.value[idx], enabled: enable }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

onMounted(fetchSkills)
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

.text-btn.is-on {
  color: var(--green);
}

.skill-error {
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

.model-row.is-disabled {
  opacity: .5;
}

code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
}
</style>
