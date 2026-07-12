<template>
  <div class="settings-page" :style="settingsThemeStyle">
    <!-- Sidebar -->
    <aside class="settings-sidebar">
      <div class="settings-brand">
        <strong>{{ title }}</strong>
        <button class="icon-btn" title="返回" @click="$emit('close')">×</button>
      </div>

      <nav class="settings-nav">
        <button
          v-for="section in sections"
          :key="section.id"
          :class="{ active: activeSection === section.id }"
          :data-settings-section="section.id"
          @click="activeSection = section.id; $emit('section-change', section.id)"
        >
          <span>{{ section.icon || '○' }}</span>
          <span>{{ section.label }}</span>
        </button>
      </nav>

      <button class="settings-entry" @click="$emit('close')">
        <span>←</span>
        <span>返回主界面</span>
      </button>
    </aside>

    <!-- Main content -->
    <main class="settings-main">
      <slot name="notice" />
      <div class="settings-content">
        <slot :activeSection="activeSection" />
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
/**
 * SettingsShell — settings page layout
 *
 * Left sidebar with navigation + right content area.
 * Product provides sections array and slot content per section.
 */
import { ref } from 'vue'

export interface SettingsSection {
  id: string
  label: string
  icon?: string
  description?: string
}

const props = withDefaults(
  defineProps<{
    sections: SettingsSection[]
    title?: string
    settingsThemeStyle?: Record<string, string>
  }>(),
  {
    title: '设置',
    settingsThemeStyle: () => ({}),
  },
)

const emit = defineEmits<{
  close: []
  'section-change': [id: string]
}>()

const activeSection = ref(props.sections[0]?.id || '')
</script>

<style scoped>
.icon-btn {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--muted);
  display: grid;
  place-items: center;
  font-size: 18px;
  font-weight: 700;
}
.icon-btn:hover {
  background: rgba(255, 255, 255, 0.14);
  color: var(--text);
}
</style>
