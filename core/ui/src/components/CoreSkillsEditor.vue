<template>
  <section class="settings-panel">
    <header class="settings-title">
      <h1>{{ t("技能") }}</h1>
      <p>{{ t("管理已发现的 Skills，禁用后不会出现在斜杠命令中；新建技能写入用户级技能目录，Agent 按需 load_skill 调取。") }}</p>
    </header>

    <p v-if="error" class="skill-error">{{ error }}</p>

    <div class="subhead">
      <span class="muted">{{ loading ? t("加载中…") : t('共 {0} 个 · 已启用 {1}', { 0: skills.length, 1: enabledCount }) }}</span>
      <div class="row-actions">
        <button
          v-if="!showCreateForm"
          class="btn btn--primary"
          type="button"
          @click="openCreateForm"
        >{{ t("新建技能") }}</button>
        <button
          class="btn btn--ghost"
          type="button"
          data-open-group-manager
          :aria-pressed="showGroupManager"
          @click="showGroupManager = !showGroupManager"
        >{{ t("管理分组") }}</button>
        <button class="btn btn--ghost" type="button" @click="refreshSkills">{{ t("刷新") }}</button>
      </div>
    </div>

    <!-- 新建技能表单：标题 / 描述 / 内容 / 分组 -->
    <article v-if="showCreateForm" class="setting-card skill-create-card">
      <div class="editor-popover-head">
        <h3>{{ t("新建技能") }}</h3>
        <button type="button" class="editor-popover-close" :aria-label="t('关闭')" @click="closeCreateForm">
          <X :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
      <p v-if="createError" class="skill-error create-error" role="alert">{{ createError }}</p>
      <div class="config-form">
        <label class="field">
          <span class="field-label">{{ t("标题（name）") }}<code class="field-type">{{ t("目录名 + frontmatter name") }}</code></span>
          <input v-model="createForm.name" class="field-input" type="text" :placeholder="t('如 my-skill（字母/数字/._-）')" />
        </label>
        <label class="field">
          <span class="field-label">{{ t("描述（description）") }}<code class="field-type">{{ t("说明何时使用，供 Agent 检索") }}</code></span>
          <input v-model="createForm.description" class="field-input" type="text" :placeholder="t('一句话说明这个技能的用途')" />
        </label>
        <label class="field">
          <span class="field-label">{{ t("内容（content）") }}<code class="field-type">{{ t("SKILL.md 正文，加载后应遵循的指引") }}</code></span>
          <textarea
            v-model="createForm.content"
            class="field-input skill-content-input"
            rows="8"
            :placeholder="t('技能加载后 Agent 应遵循的完整指引……')"
          ></textarea>
        </label>
        <label v-if="groups.length" class="field">
          <span class="field-label">{{ t("所属分组") }}</span>
          <UiSelect
            :model-value="createForm.group"
            :options="groupOptions"
            :aria-label="t('所属分组')"
            @update:model-value="createForm.group = $event"
          />
        </label>
        <div class="editor-actions">
          <button class="btn btn--quiet" type="button" @click="closeCreateForm">{{ t("取消") }}</button>
          <button class="btn btn--primary" type="button" :disabled="createSaving" @click="submitCreate">
            {{ createSaving ? t("创建中…") : t("创建技能") }}
          </button>
        </div>
      </div>
    </article>

    <!-- 分组管理：新建 / 重命名 / 删除 -->
    <article v-if="showGroupManager" class="setting-card skill-group-manager">
      <div class="editor-popover-head">
        <h3>{{ t("管理分组") }}</h3>
        <button type="button" class="editor-popover-close" :aria-label="t('关闭')" @click="showGroupManager = false">
          <X :size="14" :stroke-width="1.8" aria-hidden="true" />
        </button>
      </div>
      <div v-if="groups.length" class="skill-group-rows">
        <div v-for="group in groups" :key="group" class="skill-group-row" data-group-row>
          <template v-if="renamingGroup === group">
            <input
              v-model="renameDraft"
              class="skill-group-rename-input"
              type="text"
              :aria-label="t('重命名分组')"
              @keydown.enter.prevent="submitRename(group)"
            />
            <div class="row-actions">
              <button class="btn btn--ghost" type="button" @click="submitRename(group)">{{ t("保存") }}</button>
              <button class="btn btn--quiet" type="button" @click="renamingGroup = ''">{{ t("取消") }}</button>
            </div>
          </template>
          <template v-else>
            <strong>{{ group }}</strong>
            <span class="muted">{{ groupCounts[group] || 0 }}</span>
            <div class="row-actions">
              <button
                class="btn btn--ghost icon-btn"
                type="button"
                :data-group-rename="group"
                :aria-label="t('重命名分组')"
                :title="t('重命名')"
                @click="startRename(group)"
              ><Pencil :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
              <button
                class="btn btn--ghost btn--danger icon-btn"
                type="button"
                :data-group-delete="group"
                :aria-label="t('删除分组 {0}', { 0: group })"
                :title="t('删除')"
                @click="pendingDeleteGroup = group"
              ><Trash2 :size="14" :stroke-width="1.8" aria-hidden="true" /></button>
            </div>
          </template>
        </div>
      </div>
      <p v-else class="muted skill-group-empty">{{ t("还没有分组。新建一个，把技能归类到瀑布流的各个分区。") }}</p>
      <div class="skill-group-create">
        <input
          v-model="newGroupName"
          class="skill-group-rename-input"
          type="text"
          data-group-name-input
          :placeholder="t('分组名称')"
          :aria-label="t('分组名称')"
          @keydown.enter.prevent="submitCreateGroup"
        />
        <button class="btn btn--secondary" type="button" data-group-create :disabled="!newGroupName.trim()" @click="submitCreateGroup">
          <Plus :size="14" :stroke-width="1.8" aria-hidden="true" />
          {{ t("新建分组") }}
        </button>
      </div>
    </article>

    <!-- 分组筛选：全部 / 未分组 / 各分组 -->
    <div class="skill-filters" role="group" :aria-label="t('按分组筛选')">
      <button
        class="skill-filter"
        :class="{ 'is-active': filter === 'all' }"
        type="button"
        data-skill-filter="all"
        :aria-pressed="filter === 'all'"
        @click="filter = 'all'"
      >{{ t("全部") }}<span class="skill-filter-count">{{ skills.length }}</span></button>
      <button
        class="skill-filter"
        :class="{ 'is-active': filter === 'ungrouped' }"
        type="button"
        data-skill-filter="ungrouped"
        :aria-pressed="filter === 'ungrouped'"
        @click="filter = 'ungrouped'"
      >{{ t("未分组") }}<span class="skill-filter-count">{{ ungroupedCount }}</span></button>
      <button
        v-for="group in groups"
        :key="group"
        class="skill-filter"
        :class="{ 'is-active': filter === group }"
        type="button"
        :data-skill-filter="`g:${group}`"
        :aria-pressed="filter === group"
        @click="filter = group"
      >{{ group }}<span class="skill-filter-count">{{ groupCounts[group] || 0 }}</span></button>
    </div>

    <article v-if="!loading && !skills.length" class="setting-card">
      <p>{{ t("未发现任何 Skill。点击「新建技能」创建，或将 SKILL.md 放入技能目录（桌面端为") }}<code>.lam/skills/</code>{{ t("，移动端为应用私有技能目录）。") }}</p>
    </article>

    <!-- 卡片墙：多列瀑布流，技能按分组筛选后铺成一整面墙 -->
    <div v-else-if="visibleSkills.length" class="skill-wall">
      <article
        v-for="skill in visibleSkills"
        :key="skill.name"
        class="skill-card"
        :class="{ 'is-disabled': !skill.enabled }"
        :data-skill-card="skill.name"
      >
        <div class="skill-card-head">
          <strong class="skill-card-name" :title="skill.name">{{ skill.name }}</strong>
          <span class="skill-source" :data-source="skill.source">{{ sourceLabel(skill.source) }}</span>
        </div>
        <p class="skill-card-desc">{{ skill.description }}</p>
        <p v-if="skill.location" class="skill-card-path" :title="skill.location">{{ skill.location }}</p>
        <div class="skill-card-foot">
          <span class="skill-card-group" data-skill-group-select>
            <UiSelect
              :model-value="skill.group || ''"
              :options="groupOptions"
              :aria-label="t('移动到分组')"
              :menu-min-width="140"
              @update:model-value="assignGroup(skill, $event)"
            />
          </span>
          <div class="row-actions">
            <button
              v-if="skill.deletable"
              class="btn btn--ghost btn--danger icon-btn"
              type="button"
              :disabled="deletingName === skill.name"
              :aria-label="t('删除技能 {0}', { 0: skill.name })"
              :title="t('删除')"
              @click="deleteSkill(skill)"
            >
              <Trash2 :size="15" :stroke-width="1.8" aria-hidden="true" />
            </button>
            <button
              class="btn btn--ghost toggle-btn"
              :class="{ 'is-on': skill.enabled }"
              type="button"
              :aria-label="skill.enabled ? t('禁用技能 {0}', { 0: skill.name }) : t('启用技能 {0}', { 0: skill.name })"
              :title="skill.enabled ? t('已启用') : t('已禁用')"
              @click="toggleSkill(skill.name, !skill.enabled)"
            >
              <ToggleRight v-if="skill.enabled" :size="16" :stroke-width="1.8" aria-hidden="true" />
              <ToggleLeft v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
            </button>
          </div>
        </div>
      </article>
    </div>

    <p v-else-if="!loading" class="muted skill-filter-empty">{{ t("这个分组还没有技能。在卡片下方的分组菜单里把技能移进来。") }}</p>

    <CoreConfirmDialog
      :open="Boolean(pendingDeleteSkill)"
      :title="t('删除技能及目录？')"
      :detail="pendingDeleteSkill?.name || ''"
      @cancel="pendingDeleteSkill = null"
      @confirm="confirmDeleteSkill"
    />
    <CoreConfirmDialog
      :open="Boolean(pendingDeleteGroup)"
      :title="t('删除分组？')"
      :detail="pendingDeleteGroup || ''"
      @cancel="pendingDeleteGroup = ''"
      @confirm="confirmDeleteGroup"
    />
  </section>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'

import { computed, onMounted, ref } from 'vue'
import { Pencil, Plus, ToggleLeft, ToggleRight, Trash2, X } from 'lucide-vue-next'
import CoreConfirmDialog from '@/components/CoreConfirmDialog.vue'
import UiSelect from '@/components/UiSelect.vue'
import type { CoreSkillItem } from '@/types.ts'

const props = defineProps<{
  requestRpc: (method: string, params?: Record<string, unknown>) => Promise<Record<string, unknown>>
}>()
const emit = defineEmits<{
  changed: []
}>()

const skills = ref<CoreSkillItem[]>([])
const groups = ref<string[]>([])
const loading = ref(true)
const error = ref('')
const deletingName = ref('')

// 新建技能表单（标题 / 描述 / 内容 / 所属分组）
const showCreateForm = ref(false)
const createSaving = ref(false)
const createError = ref('')
const createForm = ref({ name: '', description: '', content: '', group: '' })

// 分组管理面板状态
const showGroupManager = ref(false)
const newGroupName = ref('')
const renamingGroup = ref('')
const renameDraft = ref('')
const pendingDeleteGroup = ref('')

// 分组筛选：all / ungrouped / 分组名
const filter = ref('all')

const enabledCount = computed(() => skills.value.filter((s) => s.enabled).length)
const ungroupedCount = computed(() => skills.value.filter((s) => !s.group).length)

const groupCounts = computed(() => {
  const counts: Record<string, number> = {}
  for (const skill of skills.value) {
    if (skill.group) counts[skill.group] = (counts[skill.group] || 0) + 1
  }
  return counts
})

const groupOptions = computed(() => [
  { value: '', label: t('未分组') },
  ...groups.value.map((group) => ({ value: group, label: group })),
])

const visibleSkills = computed(() => {
  if (filter.value === 'all') return skills.value
  if (filter.value === 'ungrouped') return skills.value.filter((s) => !s.group)
  return skills.value.filter((s) => s.group === filter.value)
})

function sourceLabel(source: string): string {
  return ({ project: t('项目'), user: t('用户'), core: t('核心'), plugin: t('插件') } as Record<string, string>)[source] || source
}

async function fetchSkills() {
  loading.value = true
  error.value = ''
  try {
    const skillResult = await props.requestRpc('skill.list')
    skills.value = (skillResult.skills as CoreSkillItem[]) || []
    groups.value = (skillResult.groups as string[]) || []
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

async function refreshSkills() {
  await fetchSkills()
  emit('changed')
}

async function toggleSkill(name: string, enable: boolean) {
  try {
    await props.requestRpc(enable ? 'skill.enable' : 'skill.disable', { name })
    const idx = skills.value.findIndex((s) => s.name === name)
    if (idx >= 0) skills.value[idx] = { ...skills.value[idx], enabled: enable }
    emit('changed')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// ── 卡片分组归属 ────────────────────────────────────────────────────────

async function assignGroup(skill: CoreSkillItem, group: string) {
  if ((skill.group || '') === group) return
  try {
    await props.requestRpc('skill.group.assign', { name: skill.name, group })
    const idx = skills.value.findIndex((s) => s.name === skill.name)
    if (idx >= 0) skills.value[idx] = { ...skills.value[idx], group }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// ── 分组管理 ────────────────────────────────────────────────────────────

async function submitCreateGroup() {
  const name = newGroupName.value.trim()
  if (!name) return
  error.value = ''
  try {
    const result = await props.requestRpc('skill.group.create', { name })
    groups.value = (result.groups as string[]) || groups.value
    newGroupName.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

function startRename(group: string) {
  renamingGroup.value = group
  renameDraft.value = group
}

async function submitRename(group: string) {
  const next = renameDraft.value.trim()
  renamingGroup.value = ''
  if (!next || next === group) return
  error.value = ''
  try {
    const result = await props.requestRpc('skill.group.rename', { from: group, to: next })
    groups.value = (result.groups as string[]) || groups.value
    skills.value = skills.value.map((s) => (s.group === group ? { ...s, group: next } : s))
    if (filter.value === group) filter.value = next
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

async function confirmDeleteGroup() {
  const group = pendingDeleteGroup.value
  pendingDeleteGroup.value = ''
  if (!group) return
  error.value = ''
  try {
    const result = await props.requestRpc('skill.group.delete', { name: group })
    groups.value = (result.groups as string[]) || groups.value
    skills.value = skills.value.map((s) => (s.group === group ? { ...s, group: '' } : s))
    if (filter.value === group) filter.value = 'all'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
}

// ── 新建技能 ────────────────────────────────────────────────────────────

function openCreateForm() {
  showCreateForm.value = true
  createError.value = ''
}

function closeCreateForm() {
  showCreateForm.value = false
  createError.value = ''
  createForm.value = { name: '', description: '', content: '', group: '' }
}

async function submitCreate() {
  createSaving.value = true
  createError.value = ''
  try {
    const { group, ...fields } = createForm.value
    await props.requestRpc('skill.create', { ...fields })
    if (group) await props.requestRpc('skill.group.assign', { name: fields.name, group })
    closeCreateForm()
    await fetchSkills()
    emit('changed')
  } catch (e) {
    createError.value = e instanceof Error ? e.message : String(e)
  } finally {
    createSaving.value = false
  }
}

// ── 删除技能 ────────────────────────────────────────────────────────────

const pendingDeleteSkill = ref<CoreSkillItem | null>(null)

function deleteSkill(skill: CoreSkillItem): void {
  if (!skill.deletable) return
  pendingDeleteSkill.value = skill
}

async function confirmDeleteSkill(): Promise<void> {
  const skill = pendingDeleteSkill.value
  pendingDeleteSkill.value = null
  if (!skill) return
  deletingName.value = skill.name
  error.value = ''
  try {
    await props.requestRpc('skill.delete', { name: skill.name })
    await fetchSkills()
    emit('changed')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    deletingName.value = ''
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

code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
}

/* ── 分组管理面板 ──────────────────────────────────────────────────────── */

.skill-group-manager {
  padding: 14px 16px;
  margin-bottom: 14px;
}

.skill-group-rows {
  display: flex;
  flex-direction: column;
  margin-bottom: var(--space-2);
}

.skill-group-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 34px;
  padding: var(--space-1) 0;
}

.skill-group-row strong {
  font-size: 13px;
}

.skill-group-row .row-actions {
  margin-left: auto;
}

.skill-group-rename-input {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid color-mix(in srgb, var(--settings-control-text, var(--theme-control-text)) 12%, transparent);
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--settings-control-solid, var(--theme-control-background)) 70%, transparent);
  color: var(--settings-control-text, var(--theme-control-text));
  font-size: 12px;
}

.skill-group-empty {
  font-size: 12px;
  margin: 0 0 var(--space-2);
}

.skill-group-create {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
}

/* ── 分组筛选行 ────────────────────────────────────────────────────────── */

.skill-filters {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
}

.skill-filter {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  padding: 0 var(--space-2);
  border-radius: 999px;
  border: 1px solid transparent;
  background: transparent;
  color: color-mix(in srgb, var(--settings-main-text, #fff) 64%, transparent);
  font-size: 12px;
  white-space: nowrap;
  transition:
    background var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out);
}

.skill-filter:hover {
  background: color-mix(in srgb, var(--settings-main-text, #fff) var(--alpha-hover), transparent);
  color: var(--settings-main-text, #fff);
}

.skill-filter.is-active {
  background: color-mix(in srgb, var(--settings-main-text, #fff) var(--alpha-active), transparent);
  color: var(--settings-main-text, #fff);
}

.skill-filter-count {
  margin-left: var(--space-1);
  color: color-mix(in srgb, var(--settings-main-text, #fff) 45%, transparent);
  font-variant-numeric: tabular-nums;
}

.skill-filter-empty {
  font-size: 12px;
  padding: var(--space-4) 0;
  text-align: center;
}

/* ── 卡片墙（多列瀑布流）─────────────────────────────────────────────────
   user:“skill 界面也做成瀑布流”+(列宽下限 230px、最多 4 列，卡片按自身内容
   高度错落堆叠；卡片内部从名字/来源到描述、路径、分组菜单一气呵成。) */

.skill-wall {
  columns: 230px 4;
  column-gap: var(--space-2);
  padding-bottom: var(--space-4);
}

.skill-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  break-inside: avoid;
  margin: 0 0 var(--space-2);
  padding: var(--space-3);
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
  border-radius: var(--radius);
  background: var(--settings-card-background, color-mix(in srgb, var(--settings-main-text, #fff) 4%, transparent));
  transition:
    border-color var(--dur-fast) var(--ease-out),
    box-shadow var(--dur-base) var(--ease-out);
}

.skill-card:hover {
  border-color: color-mix(in srgb, var(--settings-main-text, #fff) 24%, transparent);
  box-shadow: var(--shadow-sm);
}

.skill-card.is-disabled .skill-card-head,
.skill-card.is-disabled .skill-card-desc,
.skill-card.is-disabled .skill-card-path {
  opacity: .55;
}

.skill-card-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
}

.skill-card-name {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

/* 来源徽标：语义色固定，核心保持中性。 */
.skill-source {
  flex: 0 0 auto;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 10px;
  color: color-mix(in srgb, var(--settings-main-text, #fff) 58%, transparent);
  background: color-mix(in srgb, var(--settings-main-text, #fff) 8%, transparent);
}

.skill-source[data-source='user'] {
  color: color-mix(in srgb, var(--green) 78%, var(--settings-main-text, #fff));
  background: color-mix(in srgb, var(--green) 14%, transparent);
}

.skill-source[data-source='project'] {
  color: color-mix(in srgb, var(--blue) 78%, var(--settings-main-text, #fff));
  background: color-mix(in srgb, var(--blue) 14%, transparent);
}

.skill-source[data-source='plugin'] {
  color: color-mix(in srgb, var(--purple) 78%, var(--settings-main-text, #fff));
  background: color-mix(in srgb, var(--purple) 14%, transparent);
}

.skill-card-desc {
  margin: 0;
  font-size: 12px;
  line-height: 1.55;
  color: color-mix(in srgb, var(--settings-main-text, #fff) 65%, transparent);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  overflow: hidden;
}

.skill-card-path {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: color-mix(in srgb, var(--settings-main-text, #fff) 45%, transparent);
}

.skill-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
  min-width: 0;
}

.skill-card-group {
  flex: 1 1 auto;
  min-width: 0;
}

/* UiSelect 在卡片里走紧凑配方：触发器与筛选行同高，菜单不再撑宽卡片。 */
.skill-card-group :deep(.ui-select-trigger) {
  width: 100%;
  min-height: 26px;
  padding: 0 8px;
  font-size: 12px;
  border: 1px solid color-mix(in srgb, var(--settings-main-text, #fff) 10%, transparent);
  border-radius: 999px;
  background: color-mix(in srgb, var(--settings-main-text, #fff) 5%, transparent);
}

@media (prefers-reduced-motion: reduce) {
  .skill-card,
  .skill-filter {
    transition: none;
  }
}
</style>
