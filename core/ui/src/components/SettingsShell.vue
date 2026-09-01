<template>
  <div ref="settingsPageEl" class="settings-page" :style="settingsThemeStyle">
    <!-- Sidebar -->
    <aside class="settings-sidebar">
      <div class="settings-brand">
        <strong>{{ title }}</strong>
      </div>

    <nav ref="settingsNavEl" class="settings-nav">
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
    <main class="settings-main" :class="{ 'settings-main--models': activeSection === 'models' }">
      <slot name="notice" />
      <!-- No :key remount here — sections are kept alive (v-show in the
           parent slot) so draft state in child editors survives switching
           back and forth (audit 17 S3). -->
      <div ref="settingsContentEl" class="settings-content">
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
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { gsap } from 'gsap'
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
  Puzzle,
  Scale,
  Search,
  Server,
  Settings2,
  Sparkles,
  UsersRound,
  Wand2,
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
  puzzle: Puzzle,
  plug: Plug,
  scale: Scale,
  search: Search,
  server: Server,
  settings: Settings2,
  sparkles: Sparkles,
  users: UsersRound,
  wand: Wand2,
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
const settingsPageEl = ref<HTMLElement | null>(null)
const settingsNavEl = ref<HTMLElement | null>(null)
const settingsContentEl = ref<HTMLElement | null>(null)

let motionContext: gsap.Context | null = null
let motionMedia: gsap.MatchMedia | null = null
let contentTween: gsap.core.Tween | null = null
let navTween: gsap.core.Tween | null = null
let motionEnabled = false

function animateSectionChange() {
  if (!motionEnabled || !motionContext || !settingsContentEl.value) return
  const panel = settingsContentEl.value.querySelector<HTMLElement>('.settings-panel')
  if (!panel) return
  contentTween?.kill()
  motionContext.add(() => {
    contentTween = gsap.fromTo(
      panel,
      { autoAlpha: 0, y: 8, scale: 0.995, transformOrigin: '50% 0%' },
      {
        autoAlpha: 1,
        y: 0,
        scale: 1,
        duration: 0.28,
        ease: 'back.out(1.05)',
        overwrite: 'auto',
        clearProps: 'opacity,visibility,transform',
      },
    )
  })
}

function animateActiveNavItem() {
  if (!motionEnabled || !motionContext || !settingsNavEl.value) return
  const activeItem = settingsNavEl.value.querySelector<HTMLElement>('.active')
  if (!activeItem) return
  navTween?.kill()
  motionContext.add(() => {
    navTween = gsap.fromTo(
      activeItem,
      { scale: 0.975, transformOrigin: '50% 50%' },
      { scale: 1, duration: 0.2, ease: 'back.out(1.25)', overwrite: 'auto', clearProps: 'transform' },
    )
  })
}

watch(activeSection, async () => {
  await nextTick()
  animateActiveNavItem()
  animateSectionChange()
})

onMounted(() => {
  if (!settingsPageEl.value) return
  motionContext = gsap.context(() => {}, settingsPageEl.value)
  motionMedia = gsap.matchMedia()
  motionMedia.add('(prefers-reduced-motion: no-preference)', () => {
    motionEnabled = true
    return () => { motionEnabled = false }
  })
})

onUnmounted(() => {
  contentTween?.kill()
  navTween?.kill()
  motionMedia?.revert()
  motionContext?.revert()
  contentTween = null
  navTween = null
  motionMedia = null
  motionContext = null
})
</script>
