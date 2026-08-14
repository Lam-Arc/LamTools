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
          <span class="settings-nav-icon">
            <component
              :is="iconComponent(section.icon)"
              v-if="iconComponent(section.icon)"
              :size="16"
              :stroke-width="1.8"
              aria-hidden="true"
            />
            <Circle v-else :size="16" :stroke-width="1.8" aria-hidden="true" />
          </span>
          <span>{{ section.label }}</span>
        </button>
      </nav>

      <footer class="settings-sidebar-footer">
        <button class="settings-entry" @click="$emit('close')">
          <span aria-hidden="true"><ArrowLeft :size="16" :stroke-width="1.8" /></span>
          <span>返回主界面</span>
        </button>
      </footer>
    </aside>

    <!-- Main content -->
    <main class="settings-main">
      <slot name="notice" />
      <!-- No :key remount here — sections are kept alive (v-show in the
           parent slot) so draft state in child editors survives switching
           back and forth (audit 17 S3). -->
      <div class="settings-content">
        <slot :activeSection="activeSection" />
      </div>
    </main>
  </div>
</template>

<style scoped>
.settings-content {
  animation: contentEnter 260ms cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes contentEnter {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .settings-content {
    animation: none;
  }
}
</style>

<script setup lang="ts">
/**
 * SettingsShell — settings page layout
 *
 * Left sidebar with navigation + right content area.
 * Product provides sections array and slot content per section.
 */
import { ref } from 'vue'
import {
  Activity,
  AppWindow,
  ArrowLeft,
  Bell,
  Bot,
  Braces,
  Brush,
  Circle,
  Database,
  Eye,
  FileCode2,
  Folder,
  Globe,
  Image as ImageIcon,
  Info,
  Layers,
  ListChecks,
  Lock,
  Palette,
  Plug,
  Scale,
  Search,
  Server,
  Settings2,
  Sparkles,
  UsersRound,
  Wand2,
  Workflow,
  type LucideIcon,
} from 'lucide-vue-next'

/**
 * 设置分区图标注册表：icon 字段填键名（如 "search"），渲染为 lucide 矢量图标。
 * 未注册的键回退到文本显示（保持向后兼容）。
 */
const ICON_MAP: Record<string, LucideIcon> = {
  activity: Activity,
  'app-window': AppWindow,
  bell: Bell,
  bot: Bot,
  braces: Braces,
  brush: Brush,
  database: Database,
  eye: Eye,
  'file-code': FileCode2,
  folder: Folder,
  globe: Globe,
  image: ImageIcon,
  info: Info,
  layers: Layers,
  'list-checks': ListChecks,
  lock: Lock,
  palette: Palette,
  plug: Plug,
  scale: Scale,
  search: Search,
  server: Server,
  settings: Settings2,
  sparkles: Sparkles,
  users: UsersRound,
  wand: Wand2,
  workflow: Workflow,
}

function iconComponent(icon: string | undefined) {
  if (!icon) return null
  return ICON_MAP[icon.toLowerCase()] || null
}

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
