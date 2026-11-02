<script setup lang="ts">
/** 选择目标项目 + 会话。Ping 与桌宠两套绑定都用它，但互不改写对方。 */
export interface SessionPickerView {
  open: boolean
  mode: 'ping' | 'pet'
  petId: string
  projects: { id: string; name: string }[]
  sessions: { id: string; title: string }[]
  projectId: string | null
  /** 当前固定目标（用于高亮“当前”）。 */
  targetSessionId?: string | null
  targetProjectId?: string | null
  loading: boolean
  error?: string
}

const props = defineProps<{
  picker: SessionPickerView
  loadSessions: (projectId: string) => void
  chooseSession: (sessionId: string) => void
  close: () => void
}>()

function isCurrent(sessionId: string): boolean {
  return props.picker.targetProjectId === props.picker.projectId
    && props.picker.targetSessionId === sessionId
}
</script>

<template>
  <div v-if="props.picker.open" class="picker" role="dialog" aria-label="选择会话" @pointerdown.self="props.close()">
    <section class="picker__panel" data-pet-hit>
      <header class="picker__head">
        <div>
          <span class="picker__eyebrow">PING</span>
          <h2>{{ props.picker.mode === 'ping' ? '选择 Ping 会话' : `桌宠 ${props.picker.petId} 的会话` }}</h2>
        </div>
        <button class="picker__close" type="button" aria-label="关闭" @click="props.close()">✕</button>
      </header>

      <p class="picker__hint">
        {{ props.picker.mode === 'ping'
          ? '选中后固定为 Ping 的目标：截图与标记都发到这里，并持久保存。'
          : '桌宠的右键临时切换重启后恢复默认，不影响 Ping。' }}
      </p>

      <div class="picker__body">
        <aside class="picker__projects">
          <div class="picker__label">项目</div>
          <button
            v-for="project in props.picker.projects"
            :key="project.id"
            type="button"
            class="picker__project"
            :class="{ 'is-active': project.id === props.picker.projectId }"
            @click="props.loadSessions(project.id)"
          >
            <span class="picker__project-dot" />
            <span class="picker__project-name">{{ project.name }}</span>
          </button>
        </aside>

        <div class="picker__sessions">
          <div class="picker__label-row">
            <span class="picker__label">会话</span>
            <span v-if="!props.picker.loading" class="picker__count">{{ props.picker.sessions.length }}</span>
          </div>
          <div class="picker__list">
            <button
              v-for="session in props.picker.sessions"
              :key="session.id"
              type="button"
              class="picker__session"
              :class="{ 'is-current': isCurrent(session.id) }"
              @click="props.chooseSession(session.id)"
            >
              <span class="picker__session-title">{{ session.title || session.id.slice(0, 8) }}</span>
              <span v-if="isCurrent(session.id)" class="picker__badge">当前</span>
            </button>
            <div v-if="props.picker.loading" class="picker__empty">加载中…</div>
            <div v-else-if="props.picker.sessions.length === 0" class="picker__empty">
              这个项目还没有可选的会话
            </div>
          </div>
        </div>
      </div>

      <div v-if="props.picker.error" class="picker__error">{{ props.picker.error }}</div>
    </section>
  </div>
</template>

<style scoped>
.picker {
  position: absolute;
  inset: 0;
  z-index: 60;
  display: grid;
  place-items: center;
  padding: 24px;
  background: color-mix(in srgb, #000 38%, transparent);
  pointer-events: auto;
}

.picker__panel {
  width: min(560px, calc(100vw - 48px));
  max-height: min(460px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  padding: var(--space-4) var(--space-4) var(--space-3);
  border-radius: var(--radius-lg);
  border: 1px solid var(--theme-main-border);
  background: var(--theme-main-background);
  background-image: var(--theme-main-image, none);
  background-size: var(--theme-main-image-size, auto);
  background-repeat: var(--theme-main-image-repeat, no-repeat);
  box-shadow: var(--shadow-md);
  color: var(--theme-main-text);
  -webkit-backdrop-filter: var(--theme-main-glass-filter, none);
  backdrop-filter: var(--theme-main-glass-filter, none);
  font-size: 12px;
}

.picker__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.picker__eyebrow {
  display: block;
  font-size: 10px;
  letter-spacing: 0.16em;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}

.picker__head h2 {
  margin: 2px 0 0;
  font-size: 17px;
  font-weight: 680;
  line-height: 1.2;
}

.picker__close {
  flex: none;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 62%, transparent);
  font-size: 14px;
  cursor: pointer;
}

.picker__close:hover {
  background: color-mix(in srgb, var(--theme-main-text) 10%, transparent);
  color: var(--theme-main-text);
}

.picker__hint {
  margin: 8px 0 12px;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
  font-size: 11px;
  line-height: 1.5;
}

.picker__body {
  display: grid;
  grid-template-columns: minmax(140px, 0.8fr) minmax(0, 1.4fr);
  gap: 12px;
  min-height: 0;
  flex: 1;
}

.picker__projects {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-height: 0;
  overflow-y: auto;
  padding-right: 8px;
  border-right: 1px solid color-mix(in srgb, var(--theme-main-text) 9%, transparent);
}

.picker__label {
  margin-bottom: 2px;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}

.picker__label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.picker__count {
  font-size: 10px;
  color: color-mix(in srgb, var(--theme-main-text) 40%, transparent);
}

.picker__project {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 7px 8px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: color-mix(in srgb, var(--theme-main-text) 80%, transparent);
  text-align: left;
  font-size: 12px;
  cursor: pointer;
}

.picker__project:hover {
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  color: var(--theme-main-text);
}

.picker__project.is-active {
  border-color: color-mix(in srgb, var(--theme-main-text) 14%, transparent);
  background: color-mix(in srgb, var(--theme-main-text) 12%, transparent);
  color: var(--theme-main-text);
}

.picker__project-dot {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.35;
}

.picker__project.is-active .picker__project-dot {
  background: var(--green, #6fcf97);
  opacity: 1;
}

.picker__project-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker__sessions {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.picker__list {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1;
  min-height: 0;
  margin-top: 4px;
  padding-right: 2px;
  overflow-y: auto;
}

.picker__session {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 9px 10px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--theme-main-text) 5%, transparent);
  color: var(--theme-main-text);
  text-align: left;
  font-size: 12px;
  cursor: pointer;
}

.picker__session:hover {
  background: color-mix(in srgb, var(--theme-main-text) 10%, transparent);
}

.picker__session.is-current {
  border-color: color-mix(in srgb, var(--green, #6fcf97) 52%, transparent);
  background: color-mix(in srgb, var(--green, #6fcf97) 8%, transparent);
}

.picker__session-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.picker__badge {
  flex: none;
  padding: 1px 6px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--green, #6fcf97) 16%, transparent);
  color: color-mix(in srgb, var(--green, #6fcf97) 88%, white);
  font-size: 10px;
}

.picker__empty {
  padding: 10px 8px;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  font-size: 11px;
}

.picker__error {
  margin-top: 8px;
  color: #ffb4b4;
  font-size: 11px;
}
</style>
