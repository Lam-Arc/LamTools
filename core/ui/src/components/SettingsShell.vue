<template>
  <div class="settings-page" :style="settingsThemeStyle">
    <!-- Sidebar -->
    <aside class="settings-sidebar">
      <div class="settings-brand">
        <strong>{{ title }}</strong>
      </div>

      <nav class="settings-nav">
        <button
          v-for="section in sections"
          :key="section.id"
          :class="{ active: activeSection === section.id }"
          :aria-current="activeSection === section.id ? 'page' : undefined"
          :data-settings-section="section.id"
          @click="activeSection = section.id; $emit('section-change', section.id)"
        >
          <span>{{ section.icon || '○' }}</span>
          <span>{{ section.label }}</span>
        </button>
      </nav>

      <footer class="settings-sidebar-footer">
        <button class="settings-entry" @click="$emit('close')">
          <span aria-hidden="true">←</span>
          <span>返回主界面</span>
        </button>
      </footer>
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
