<template>
  <!-- user:“把标题栏取消，主区自然向上填充，右侧预留出最小化，最大化，关闭的按钮区域”+(只保留右上角系统按钮和一小块窗口拖动区)。 -->
  <div
    v-if="visible || $slots.default"
    class="window-controls"
    :class="{ 'window-controls--preview': props.inline }"
    data-window-controls
    :data-native-window-controls="visible || undefined"
    data-ui-id="shell.window-controls"
    @pointerdown="startWindowDragFromBlank"
  >
    <!-- user:“不再留拖拽的空位”+(这一簇里不再单独占一段可拖拽空白；拖窗交给标题带的空白区域)。 -->
    <!-- user:“与最大化、最小化以及关闭并列”+(工作区按钮放在系统窗口按钮之前，和它们共用一行)。 -->
    <slot />
    <!-- user:“对当前的标题按钮（最小化/最大化/关闭处使用一个胶囊底包裹…填充底色采用墨黑色/石英白）”+
         (三枚系统按钮共用一只胶囊底，描边与填充都由令牌给出，深浅主题各自成立)。 -->
    <template v-if="visible">
      <div class="window-control-capsule" data-window-control-capsule>
        <button type="button" class="ctrl-btn window-control-button" data-window-control="minimize" :title="t('最小化')" :aria-label="t('最小化')" @click="onMinimize">
          <svg viewBox="0 0 14 14"><rect x="2" y="6" width="10" height="1.5" rx="0.75" /></svg>
        </button>
        <button
          type="button"
          class="ctrl-btn window-control-button"
          data-window-control="maximize"
          :title="t('最大化')"
          :aria-label="t('最大化')"
          @click="onMaximize"
        >
          <svg viewBox="0 0 14 14"><rect x="2" y="2" width="10" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.5" /></svg>
        </button>
        <button type="button" class="ctrl-btn window-control-button close" data-window-control="close" :title="t('关闭')" :aria-label="t('关闭')" @click="onClose">
          <svg viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" /></svg>
        </button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { t } from '@/i18n/index.ts'
// user:“非圆/胶囊区是否可拖拽移动？”+(深灰底这层也算标题带的空白：按住就拖窗，按钮照旧)。 
import { startWindowDragFromBlank } from '@/composables/useWindowDrag.ts'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { isTauri } from '@tauri-apps/api/core'
import { computed } from 'vue'

const props = defineProps<{ showInPreview?: boolean; hideOnMobile?: boolean; inline?: boolean }>()
const visible = computed(() => !props.hideOnMobile && (isTauri() || props.showInPreview))

type WindowAction = 'minimize' | 'toggleMaximize' | 'close'

// user:“改用官方 window API，不再依赖全局注入”+
// (三个按钮分别调 getCurrentWindow() 的 minimize / toggleMaximize / close；
//  非 Tauri 环境（展厅、纯浏览器预览、单测）里 getCurrentWindow() 会抛，这里包一层，
//  dev 里留一条 error 日志，生产静默，不影响预览与测试)。
// user:“保留一条日志，但用 console.error”+(前端落盘只收 warn/error，之前用 info 所以一条都看不到)。
function runWindowAction(action: WindowAction): void {
  if (props.inline) return
  try {
    const win = getCurrentWindow()
    const pending = action === 'minimize' ? win.minimize() : action === 'toggleMaximize' ? win.toggleMaximize() : win.close()
    void Promise.resolve(pending).then(
      () => console.error('[window-ctl]', { command: action, ok: true }),
      (error: unknown) => console.error('[window-ctl]', { command: action, ok: false, error: String(error) }),
    )
  } catch (error) {
    if (import.meta.env?.DEV) console.error('[window-ctl]', { command: action, ok: false, error: String(error) })
  }
}

function onMinimize() { runWindowAction('minimize') }
function onMaximize() { runWindowAction('toggleMaximize') }
function onClose() { runWindowAction('close') }
</script>

<style scoped>
/* user:“此四控件与其左侧的可拖拽空白区域，使用深灰色底”+
   “不再留拖拽的空位，而是非交互区域均可拖拽”+
   (右上角这一簇 = 标签页抽屉圆底 + 三键胶囊，只有这一簇吃深灰底；
    颜色走主题注入的令牌，深浅主题都保持深灰)。 */
.window-controls {
  position: fixed;
  inset: 0 0 auto auto;
  z-index: var(--z-popover);
  display: flex;
  align-items: center;
  gap: var(--window-control-gap);
  height: var(--window-cluster-height);
  /* user:“稍微给留一点点白，现在那个圆和左边已经紧贴了，光学中心式留白”+
   (左右同样留 8px：圆键不再贴边，整簇在深灰底里居中)。 */
  padding: 0 var(--space-2);
  /* user:“右上那个组的背景，你考虑过深浅变化吗？”+
     (底色是主题派生的一档灰；再叠一层对角深浅：上缘掺一点字色、下缘压一档暗，
      深色主题是“微亮到更深”，浅色主题是“微深到更沉”，不再是整块平涂)。 */
  background-color: var(--theme-window-chrome-background);
  background-image: linear-gradient(
    155deg,
    color-mix(in srgb, var(--theme-main-text) 6%, transparent) 0%,
    transparent 52%,
    color-mix(in srgb, #000 18%, transparent) 100%
  );
  border-bottom-left-radius: var(--radius-lg);
  /* 图标色 = 72% 主区文字色，与按钮静默态一致。
     user:“边再淡一点，（统一）”+(圆键与胶囊共用同一档描边：只用一条变量、比图标淡一档，
       不再各算各的 alpha——一个 40%、一个 72% 的差就是从这里来的)。 */
  --window-capsule-border: color-mix(in srgb, var(--theme-main-text) 28%, transparent);
  color: color-mix(in srgb, var(--theme-main-text) 72%, transparent);
  user-select: none;
}

.window-controls--preview {
  position: static;
  width: fit-content;
  padding: 0 var(--space-2);
  border-radius: var(--radius-lg);
}

.ctrl-btn.close:hover {
  background: var(--red);
  color: white;
}

.ctrl-btn svg { fill: currentColor; }
</style>
