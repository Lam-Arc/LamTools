<template>
  <main
    class="core-start-page"
    :class="{ 'has-project': hasProject }"
    :data-state="hasProject ? 'project-no-session' : 'no-project'"
    data-core-start-page
  >
    <div class="core-start-page-backdrop" aria-hidden="true">准备开干！</div>
    <div class="core-start-page-content">
      <p class="core-start-page-kicker">LamTools Core</p>
      <h1>{{ hasProject ? '从一个新会话开始' : '先选一个工作目录' }}</h1>
      <p class="core-start-page-description">
        {{ hasProject
          ? '当前项目还没有可用会话。新建会话后即可开始工作。'
          : '项目保存工作目录、会话和运行配置。你也可以打开已使用过的目录。' }}
      </p>

      <div class="core-start-page-actions">
        <button
          v-if="hasProject"
          class="core-start-page-action primary"
          type="button"
          data-start-new-session
          @click="emit('new-session')"
        >新建会话</button>
        <button
          v-else
          class="core-start-page-action primary"
          type="button"
          data-start-new-project
          @click="emit('new-project')"
        >新建项目</button>
        <button
          class="core-start-page-action secondary"
          type="button"
          data-start-open-project
          @click="emit('open-project')"
        >{{ hasProject ? '打开其他项目' : '打开项目' }}</button>
      </div>

      <section v-if="recentProjects.length" class="core-start-page-recent" aria-labelledby="core-start-page-recent-title">
        <h2 id="core-start-page-recent-title">最近项目</h2>
        <div class="core-start-page-recent-list">
          <button
            v-for="project in recentProjects"
            :key="project.id"
            class="core-start-page-recent-item"
            type="button"
            :title="project.workRoot"
            :aria-label="`打开项目 ${project.name}`"
            :data-recent-project="project.id"
            @click="emit('open-recent-project', project.id)"
          >
            <span class="core-start-page-recent-copy">
              <span class="core-start-page-recent-name">{{ project.name }}</span>
              <span class="core-start-page-recent-path">{{ project.workRoot }}</span>
            </span>
            <time class="core-start-page-recent-time" :datetime="project.openedAt">{{ formatOpenedAt(project.openedAt) }}</time>
          </button>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
export interface CoreRecentProject {
  id: string
  name: string
  workRoot: string
  openedAt: string
}

withDefaults(defineProps<{
  hasProject?: boolean
  recentProjects?: CoreRecentProject[]
}>(), {
  hasProject: false,
  recentProjects: () => [],
})

const emit = defineEmits<{
  'new-project': []
  'open-project': []
  'new-session': []
  'open-recent-project': [projectId: string]
}>()

function formatOpenedAt(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return '最近打开'
  const elapsed = Date.now() - date.valueOf()
  if (elapsed >= 0 && elapsed < 60_000) return '刚刚打开'
  if (elapsed >= 0 && elapsed < 3_600_000) return `${Math.max(1, Math.floor(elapsed / 60_000))} 分钟前`
  if (elapsed >= 0 && elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)} 小时前`
  if (elapsed >= 0 && elapsed < 7 * 86_400_000) return `${Math.floor(elapsed / 86_400_000)} 天前`
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' }).format(date)
}
</script>

<style scoped>
.core-start-page {
  --text: var(--theme-main-text);
  position: relative;
  isolation: isolate;
  display: grid;
  min-height: 100%;
  overflow: hidden;
  place-items: center;
  padding: var(--space-6);
  background: var(--theme-main-background);
  color: var(--text);
}

.core-start-page-backdrop {
  position: absolute;
  z-index: -1;
  top: 50%;
  left: 50%;
  width: max-content;
  max-width: 100%;
  color: color-mix(in srgb, var(--text) 7%, transparent);
  font-size: clamp(56px, 11vw, 144px);
  font-weight: 800;
  letter-spacing: -0.035em;
  line-height: .96;
  pointer-events: none;
  transform: translate(-50%, -50%);
  user-select: none;
  white-space: nowrap;
}

.core-start-page-content {
  width: min(100%, 540px);
  padding: var(--space-5);
}

.core-start-page-kicker {
  margin: 0 0 var(--space-2);
  color: color-mix(in srgb, var(--text) 58%, transparent);
  font-size: 13px;
  font-weight: 620;
}

.core-start-page h1 {
  margin: 0;
  font-size: 28px;
  font-weight: 740;
  letter-spacing: -0.025em;
  line-height: 1.2;
  text-wrap: balance;
}

.core-start-page-description {
  max-width: 38ch;
  margin: var(--space-3) 0 0;
  color: color-mix(in srgb, var(--text) 68%, transparent);
  font-size: 14px;
  line-height: 1.65;
}

.core-start-page-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-5);
}

.core-start-page-action {
  min-height: 38px;
  border: 0;
  border-radius: var(--radius-sm);
  padding: 0 var(--space-3);
  font: inherit;
  font-size: 13px;
  font-weight: 650;
  cursor: pointer;
  transition: background var(--dur-fast) var(--ease-out), filter var(--dur-fast) var(--ease-out);
}

.core-start-page-action.primary {
  background: var(--theme-control-background);
  color: var(--theme-control-text);
}

.core-start-page-action.primary:hover { filter: brightness(.94); }
.core-start-page-action.primary:active { filter: brightness(.9); }

.core-start-page-action.secondary {
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  color: var(--text);
}

.core-start-page-action.secondary:hover {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
}

.core-start-page-action.secondary:active {
  background: color-mix(in srgb, var(--text) var(--alpha-press), transparent);
}

.core-start-page-action:focus-visible,
.core-start-page-recent-item:focus-visible {
  outline: 2px solid var(--blue);
  outline-offset: 2px;
}

.core-start-page-recent {
  margin-top: var(--space-6);
}

.core-start-page-recent h2 {
  margin: 0 0 var(--space-2);
  color: color-mix(in srgb, var(--text) 64%, transparent);
  font-size: 13px;
  font-weight: 680;
}

.core-start-page-recent-list {
  display: grid;
}

.core-start-page-recent-item {
  display: flex;
  min-width: 0;
  min-height: 54px;
  align-items: center;
  gap: var(--space-3);
  border: 0;
  border-radius: 0;
  padding: var(--space-2) var(--space-1);
  background: transparent;
  color: var(--text);
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.core-start-page-recent-item:hover,
.core-start-page-recent-item:active {
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--text) var(--alpha-hover), transparent) var(--row-fade), color-mix(in srgb, var(--text) var(--alpha-hover), transparent) calc(100% - var(--row-fade)), transparent);
}

.core-start-page-recent-item:active {
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--text) var(--alpha-active), transparent) var(--row-fade), color-mix(in srgb, var(--text) var(--alpha-active), transparent) calc(100% - var(--row-fade)), transparent);
}

.core-start-page-recent-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.core-start-page-recent-name,
.core-start-page-recent-path,
.core-start-page-recent-time {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.core-start-page-recent-name {
  font-size: 14px;
  font-weight: 630;
}

.core-start-page-recent-path {
  color: color-mix(in srgb, var(--text) 52%, transparent);
  font-family: var(--font-mono);
  font-size: 11px;
}

.core-start-page-recent-time {
  margin-left: auto;
  color: color-mix(in srgb, var(--text) 50%, transparent);
  font-size: 12px;
}

@media (max-width: 640px) {
  .core-start-page { padding: var(--space-4); }
  .core-start-page-content { padding: var(--space-4); }
  .core-start-page-backdrop { font-size: clamp(44px, 13vw, 76px); }
  .core-start-page-recent-time { display: none; }
}

@media (max-width: 420px) {
  .core-start-page-backdrop { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .core-start-page-action { transition: none; }
}
</style>
