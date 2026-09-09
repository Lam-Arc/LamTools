<template>
  <div ref="root" class="core-workspace-menu" data-core-workspace-menu>
    <button
      class="core-workspace-menu__trigger"
      type="button"
      :disabled="disabled || options.length === 0"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="`工作环境：${activeOption?.label || '未选择'}`"
      :title="activeOption?.label || '选择工作环境'"
      @click="toggle"
    >
      <component :is="iconFor(activeOption)" :size="15" :stroke-width="2" aria-hidden="true" />
      <ChevronDown :size="12" :stroke-width="2" aria-hidden="true" />
    </button>

    <section v-if="open" ref="card" class="core-workspace-menu__card" :style="viewportStyle" role="menu" aria-label="选择工作环境">
      <div class="core-workspace-menu__heading">工作环境</div>
      <button
        v-for="option in options"
        :key="option.id"
        class="core-workspace-menu__option"
        :class="{ active: option.id === activeId }"
        type="button"
        role="menuitemradio"
        :aria-checked="option.id === activeId"
        :data-workspace-option="option.id"
        @click="selectOption(option.id)"
      >
        <component :is="iconFor(option)" class="core-workspace-menu__device-icon" :size="16" :stroke-width="2" aria-hidden="true" />
        <span class="core-workspace-menu__copy">
          <span>{{ option.label }}</span>
          <small>{{ option.deviceName || platformLabel(option.platform) }}</small>
        </span>
        <span class="core-workspace-menu__status" :class="{ offline: option.online === false }">
          {{ option.online === false ? '离线' : '在线' }}
        </span>
        <Check v-if="option.id === activeId" :size="15" :stroke-width="2.2" aria-hidden="true" />
      </button>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Check, ChevronDown, Monitor, Smartphone } from 'lucide-vue-next'
import type { RuntimeWorkspaceOption } from '../app/runtime'
import { useComposerMenuMotion } from '../motion/composerMenu'
import { useComposerMenuViewport } from '../composables/useComposerMenuViewport'

const props = withDefaults(defineProps<{
  activeId?: string
  options?: RuntimeWorkspaceOption[]
  disabled?: boolean
}>(), {
  activeId: '',
  options: () => [],
  disabled: false,
})

const emit = defineEmits<{ select: [id: string] }>()
const root = ref<HTMLElement | null>(null)
const card = ref<HTMLElement | null>(null)
const open = ref(false)
const { animatePrimaryCard, cancel } = useComposerMenuMotion(root)
const { updateViewportPosition, viewportStyle } = useComposerMenuViewport(root)
const activeOption = computed(() => props.options.find((option) => option.id === props.activeId))

function iconFor(option?: RuntimeWorkspaceOption) {
  return /android|ios|mobile|phone/i.test(option?.platform || '') ? Smartphone : Monitor
}

function platformLabel(platform?: string): string {
  return /android|ios|mobile|phone/i.test(platform || '') ? '移动设备' : '电脑'
}

function toggle(): void {
  if (props.disabled || props.options.length === 0) return
  open.value = !open.value
  if (!open.value) return cancel()
  updateViewportPosition()
  void nextTick(() => animatePrimaryCard(card.value, ':scope > .core-workspace-menu__heading, :scope > .core-workspace-menu__option'))
}

function close(): void {
  cancel()
  open.value = false
}

function selectOption(id: string): void {
  emit('select', id)
  close()
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target as Node | null
  if (target && root.value && !root.value.contains(target)) close()
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) close()
}

onMounted(() => {
  document.addEventListener('pointerdown', onPointerDown)
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onPointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.core-workspace-menu { position: relative; flex: 0 0 auto; --text: var(--theme-composer-text); }
.core-workspace-menu__trigger { display: inline-flex; align-items: center; justify-content: center; gap: 2px; min-width: 30px; height: 28px; padding: 0 5px; border: 0; border-radius: var(--radius-sm); background: transparent; color: color-mix(in srgb, var(--text) 68%, transparent); cursor: pointer; }
.core-workspace-menu__trigger:hover, .core-workspace-menu__trigger[aria-expanded="true"] { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); color: var(--text); }
.core-workspace-menu__trigger:disabled { opacity: .4; cursor: not-allowed; }
.core-workspace-menu__card { position: absolute; left: 0; bottom: calc(100% + var(--space-2)); z-index: var(--z-popover); display: grid; gap: 2px; width: min(280px, calc(100vw - 24px)); padding: var(--space-2); border: 1px solid color-mix(in srgb, var(--text) 12%, transparent); border-radius: var(--radius); background: var(--theme-composer-background); color: var(--text); box-shadow: var(--shadow-md); }
.core-workspace-menu__heading { padding: var(--space-1) var(--space-2) var(--space-2); color: color-mix(in srgb, var(--text) 55%, transparent); font-size: 11px; font-weight: 650; }
.core-workspace-menu__option { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: var(--space-2); width: 100%; min-height: 42px; padding: var(--space-2); border: 0; border-radius: var(--radius-sm); background: transparent; color: var(--text); text-align: left; font: inherit; cursor: pointer; }
.core-workspace-menu__option:hover, .core-workspace-menu__option.active { background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent); }
.core-workspace-menu__device-icon { color: color-mix(in srgb, var(--text) 66%, transparent); }
.core-workspace-menu__copy { display: grid; min-width: 0; gap: 2px; }
.core-workspace-menu__copy > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; font-weight: 600; }
.core-workspace-menu__copy small, .core-workspace-menu__status { color: color-mix(in srgb, var(--text) 52%, transparent); font-size: 10px; }
.core-workspace-menu__status:not(.offline) { color: var(--green); }
@media (prefers-reduced-motion: reduce) { .core-workspace-menu__trigger { transition: none; } }
@media (max-width: 640px) {
  .core-workspace-menu__card {
    position: fixed;
    right: var(--space-3);
    bottom: var(--composer-menu-bottom);
    left: var(--space-3);
    box-sizing: border-box;
    width: auto;
    max-height: calc(100dvh - var(--composer-menu-bottom) - var(--space-3));
    overflow-x: hidden;
    overflow-y: auto;
  }
}
</style>
