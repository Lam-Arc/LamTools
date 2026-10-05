<template>
  <div ref="settingsPageEl" class="settings-page" :class="{ 'settings-page--no-nav': props.hideNav }" :style="settingsThemeStyle">
    <!-- Sidebar (hidden when the host renders the nav in the workspace drawer) -->
    <aside v-if="!props.hideNav" class="settings-sidebar">
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

    <!-- Main content (the page's own scroller) -->
    <main ref="settingsMainEl" class="settings-main" :class="{ 'settings-main--models': activeSection === 'models' }">
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
import { ArrowLeft, Circle, type LucideIcon } from 'lucide-vue-next'
import { settingsSectionIcon, type SettingsSection } from './settingsSections'

function iconComponent(icon: string | undefined): LucideIcon | null {
  return settingsSectionIcon(icon)
}

export type { SettingsSection }

const props = withDefaults(
  defineProps<{
    sections: SettingsSection[]
    title?: string
    settingsThemeStyle?: Record<string, string>
    /** Section to open on; falls back to the first section when absent/unknown. */
    initialSection?: string
    /** Hide the built-in left nav: the host renders it in the workspace drawer. */
    hideNav?: boolean
    /** Controlled section from the host's drawer nav; synced one-way in. */
    activeSection?: string
  }>(),
  {
    title: '设置',
    settingsThemeStyle: () => ({}),
    initialSection: undefined,
    hideNav: false,
    activeSection: undefined,
  },
)

const emit = defineEmits<{
  close: []
  'section-change': [id: string]
}>()

const activeSection = ref(
  props.initialSection && props.sections.some((section) => section.id === props.initialSection)
    ? props.initialSection
    : (props.sections[0]?.id || ''),
)
const settingsPageEl = ref<HTMLElement | null>(null)
const settingsNavEl = ref<HTMLElement | null>(null)
const settingsMainEl = ref<HTMLElement | null>(null)
const settingsContentEl = ref<HTMLElement | null>(null)

/**
 * 打开一页设置（或换分区）时回到顶部：滚动容器在前一版布局/上一分区里留下的
 * 位置会原样沿用，页面一进来就从中间开始，看着像被裁掉了。
 */
function resetScrollPosition() {
  if (settingsMainEl.value) settingsMainEl.value.scrollTop = 0
  const view = settingsMainEl.value?.closest<HTMLElement>('.full-area-view')
  if (view) view.scrollTop = 0
}

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
  resetScrollPosition()
  animateActiveNavItem()
  animateSectionChange()
})

// Host-controlled section (drawer nav): follow it while it names a real section.
watch(() => props.activeSection, (id) => {
  if (id && props.sections.some((section) => section.id === id)) {
    activeSection.value = id
  }
})

onMounted(async () => {
  // Tell the host which section actually opened so its drawer nav highlights it.
  if (activeSection.value) emit('section-change', activeSection.value)
  resetScrollPosition()
  // 内容（插件列表等）是异步落位的：落位后再回一次顶，别让浏览器把锚点留在中间。
  await nextTick()
  resetScrollPosition()
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
