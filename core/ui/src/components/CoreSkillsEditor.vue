<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>技能</h1>
      <p>管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。</p>
    </header>

    <p v-if="error" class="skill-error">{{ error }}</p>

    <div class="subhead">
      <span class="muted">{{ loading ? '加载中…' : `共 ${skills.length} 个 · 已启用 ${enabledCount}` }}</span>
      <div class="row-actions">
        <button
          v-if="!showCreateForm"
          class="small-btn primary"
          type="button"
          @click="openCreateForm"
        >新建技能</button>
        <button class="text-btn" type="button" @click="fetchSkills">刷新</button>
      </div>
    </div>

    <!-- 新建技能表单：标题 / 描述 / 内容 -->
    <article v-if="showCreateForm" class="setting-card skill-create-card">
      <div class="editor-popover-head">
        <h3>新建技能</h3>
        <button type="button" class="editor-popover-close" aria-label="关闭" @click="closeCreateForm">
          <X :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
      <p v-if="createError" class="skill-error create-error" role="alert">{{ createError }}</p>
      <div class="config-form">
        <label class="field">
          <span class="field-label">标题（name）<code class="field-type">目录名 + frontmatter name</code></span>
          <input v-model="createForm.name" class="field-input" type="text" placeholder="如 my-skill（字母/数字/._-）" />
        </label>
        <label class="field">
          <span class="field-label">描述（description）<code class="field-type">说明何时使用，供 Agent 检索</code></span>
          <input v-model="createForm.description" class="field-input" type="text" placeholder="一句话说明这个技能的用途" />
        </label>
        <label class="field">
          <span class="field-label">内容（content）<code class="field-type">SKILL.md 正文，加载后应遵循的指引</code></span>
          <textarea
            v-model="createForm.content"
            class="field-input skill-content-input"
            rows="8"
            placeholder="技能加载后 Agent 应遵循的完整指引……"
          ></textarea>
        </label>
        <div class="editor-actions">
          <button class="small-btn quiet" type="button" @click="closeCreateForm">取消</button>
          <button class="small-btn primary" type="button" :disabled="createSaving" @click="submitCreate">
            {{ createSaving ? '创建中…' : '创建技能' }}
          </button>
        </div>
      </div>
    </article>

    <article v-if="!loading && !skills.length" class="setting-card">
      <p>未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入 <code>.lam/skills/</code> 目录。</p>
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
                class="text-btn toggle-btn"
                :class="{ 'is-on': skill.enabled }"
                type="button"
                :aria-label="skill.enabled ? `禁用技能 ${skill.name}` : `启用技能 ${skill.name}`"
                :title="skill.enabled ? '已启用' : '已禁用'"
                @click="toggleSkill(skill.name, !skill.enabled)"
              >
                <ToggleRight v-if="skill.enabled" :size="16" :stroke-width="1.8" aria-hidden="true" />
                <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ToggleLeft, ToggleRight, X } from 'lucide-vue-next'
import type { CoreSkillItem } from '../types'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()

const skills = ref<CoreSkillItem[]>([])
const loading = ref(true)
const error = ref('')

// 新建技能表单（标题 / 描述 / 内容三块）
const showCreateForm = ref(false)
const createSaving = ref(false)
const createError = ref('')
const createForm = ref({ name: '', description: '', content: '' })

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
    const skillResult = await props.requestRpc('skill.list')
    skills.value = (skillResult.skills as CoreSkillItem[]) || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
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

function openCreateForm() {
  showCreateForm.value = true
  createError.value = ''
}

function closeCreateForm() {
  showCreateForm.value = false
  createError.value = ''
  createForm.value = { name: '', description: '', content: '' }
}

async function submitCreate() {
  createSaving.value = true
  createError.value = ''
  try {
    await props.requestRpc('skill.create', { ...createForm.value })
    closeCreateForm()
    await fetchSkills()
  } catch (e) {
    createError.value = e instanceof Error ? e.message : String(e)
  } finally {
    createSaving.value = false
  }
}

onMounted(fetchSkills)
</script>

<style scoped>
.skill-error {
  margin: 0;
  padding: 9px 12px;
  border-radius: var(--radius);
  border: 1px solid color-mix(in srgb, var(--red) 22%, transparent);
  background: color-mix(in srgb, var(--red) 10%, transparent);
  color: color-mix(in srgb, var(--red) 64%, var(--settings-main-text, #fff));
  font-size: 13px;
}

.skill-create-card {
  padding: 14px 16px;
  margin-bottom: 14px;
}

.create-error {
  margin-bottom: 10px;
}

.skill-content-input {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  resize: vertical;
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
