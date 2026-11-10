<template>
  <div ref="cardRef" class="tray-panel" :data-material="material" role="menu" aria-label="Sunday 托盘面板">
    <template v-for="row in rows" :key="row.id">
      <!-- 开关行：整行可点，控件仍然是主界面那套 SundaySwitch，不另做一个。 -->
      <div
        v-if="row.kind === 'toggle'"
        class="tray-row tray-row--toggle"
        role="menuitemcheckbox"
        :aria-checked="row.value ? 'true' : 'false'"
        :class="{ 'is-busy': pending === row.id }"
        @click="onToggleRow(row)"
      >
        <component :is="iconOf(row.id)" class="tray-row__icon" :size="14" aria-hidden="true" />
        <span class="tray-row__title">{{ row.title }}</span>
        <span class="tray-row__control" @click.stop>
          <SundaySwitch
            size="sm"
            :label="row.title"
            :model-value="Boolean(row.value)"
            :disabled="pending === row.id"
            @update:model-value="onToggleRow(row)"
          />
        </span>
      </div>

      <button
        v-else
        type="button"
        class="tray-row tray-row--button"
        :class="{ 'tray-row--danger': row.kind === 'danger' }"
        role="menuitem"
        @click="onActionRow(row)"
      >
        <component :is="iconOf(row.id)" class="tray-row__icon" :size="14" aria-hidden="true" />
        <span class="tray-row__title">{{ row.title }}</span>
      </button>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * 自绘托盘面板。
 *
 * user:“托盘样式重做”“只做自绘面板”
 * “上面不需要标题和状态，多此一举了”“这个东西不需要小字，看着很多余”
 * “还有你的字号，还有图标，什么都太大了”“也不用刻意去做圆角”
 * “你撑死搞个云母”+
 * (只有四行可点项：图标加标签，开关用主界面同一套 SundaySwitch；
 *  不做标题栏、不做说明小字、不做自定义圆角，材质交给系统云母。)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { AppWindow, Bot, LogOut, PenTool } from 'lucide-vue-next'
import SundaySwitch from '@/components/SundaySwitch.vue'
import { useOverlayTheme } from '@/pet/ui/overlayTheme.ts'
import * as bridge from './bridge.ts'
import { trayRows, type TrayRow } from './model.ts'

useOverlayTheme()

const POLL_MS = 800
/** 开覆盖层要建窗，等它出现的最长时间。 */
const TOGGLE_TIMEOUT_MS = 8000
/** 面板的设计宽度（CSS 像素）；高度按实际排版算。 */
const PANEL_WIDTH = 176

const petOpen = ref(false)
const overlayOpen = ref(false)
const pending = ref<'' | 'pet' | 'overlay'>('')
const cardRef = ref<HTMLElement | null>(null)
/** mica：系统云母铺底；solid：系统没有云母，页面自己画不透明底。 */
const material = ref<'mica' | 'solid'>('solid')

const rows = computed(() => trayRows({ petOpen: petOpen.value, overlayOpen: overlayOpen.value }))

let timer: ReturnType<typeof setInterval> | null = null
let disposed = false

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

function iconOf(id: TrayRow['id']) {
  switch (id) {
    case 'main':
      return AppWindow
    case 'pet':
      return Bot
    case 'overlay':
      return PenTool
    default:
      return LogOut
  }
}

async function refresh(): Promise<void> {
  if (disposed) return
  try {
    const snapshot = await bridge.panelState()
    petOpen.value = snapshot.pet_open
    overlayOpen.value = snapshot.overlay_open
  } catch {
    // 后端/宿主暂时不应答时保持上一次状态，不把开关乱翻。
  }
}

async function waitFor(target: 'pet' | 'overlay', want: boolean): Promise<void> {
  const deadline = Date.now() + TOGGLE_TIMEOUT_MS
  while (Date.now() < deadline && !disposed) {
    await sleep(300)
    await refresh()
    if ((target === 'pet' ? petOpen.value : overlayOpen.value) === want) return
  }
}

async function onToggleRow(row: TrayRow): Promise<void> {
  if (row.id !== 'pet' && row.id !== 'overlay') return
  if (pending.value) return
  const target = row.id
  const want = !(target === 'pet' ? petOpen.value : overlayOpen.value)
  pending.value = target
  try {
    // 宿主在后台线程建窗，这里立刻返回，随后轮询到真实状态。
    await bridge.toggleTarget(target)
    await waitFor(target, want)
  } catch {
    await refresh()
  } finally {
    pending.value = ''
  }
}

async function onActionRow(row: TrayRow): Promise<void> {
  if (row.id === 'main') {
    await bridge.revealMain().catch(() => undefined)
    return
  }
  if (row.id === 'quit') await bridge.quitApp().catch(() => undefined)
}

/** 把窗口调到刚好装下内容，避免缩放不同把最后一行裁掉。 */
async function fitPanel(): Promise<void> {
  await nextTick()
  const card = cardRef.value
  if (!card) return
  const height = Math.ceil(card.scrollHeight + 2)
  if (Math.abs(window.innerHeight - height) <= 1) return
  await bridge.fitPanel(PANEL_WIDTH, height, window.devicePixelRatio).catch(() => undefined)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Escape') return
  event.preventDefault()
  void bridge.closePanel().catch(() => undefined)
}

const onWindowFocus = (): void => {
  void refresh()
}

onMounted(() => {
  void bridge.panelMaterial().then(value => (material.value = value)).catch(() => undefined)
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('focus', onWindowFocus)
  void refresh().then(() => fitPanel())
  timer = setInterval(() => void refresh(), POLL_MS)
})

onBeforeUnmount(() => {
  disposed = true
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('focus', onWindowFocus)
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
/* user:“也不用刻意去做圆角”“你撑死搞个云母”+(方角、系统材质，页面只画文字和开关)。 */
.tray-panel {
  --text: var(--theme-main-text);

  display: flex;
  flex-direction: column;
  /* 高度由内容决定：页面量出来再让宿主把窗口收成刚好这么大。 */
  width: 100%;
  padding: 4px;
  border: 1px solid color-mix(in srgb, var(--text) 12%, transparent);
  background: transparent;
  color: var(--text);
  font-family: var(--font-sans);
  overflow: hidden;
}

/* 云母已经铺好底，只压一层很薄的同色蒙版保证文字对比度。 */
.tray-panel[data-material='mica'] {
  background: color-mix(in srgb, var(--theme-main-background) 34%, transparent);
}

/* 没有云母的系统：一张不透明面板。 */
.tray-panel[data-material='solid'] {
  background: var(--theme-main-background);
}

.tray-row {
  position: relative;
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 30px;
  padding: 0 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

/* 行高亮是行本身的处理：不用圆角块，两侧按 --row-fade 渐隐。 */
.tray-row::before {
  content: '';
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--text) var(--alpha-hover), transparent);
  opacity: 0;
  transition: opacity 120ms ease-out;
  mask: linear-gradient(
    to right,
    transparent 0,
    #000 var(--row-fade),
    #000 calc(100% - var(--row-fade)),
    transparent 100%
  );
  pointer-events: none;
}

.tray-row:hover::before,
.tray-row:focus-visible::before {
  opacity: 1;
}

.tray-row:active::before {
  background: color-mix(in srgb, var(--text) var(--alpha-active), transparent);
  opacity: 1;
}

.tray-row:focus-visible {
  outline: none;
}

.tray-row__icon {
  color: color-mix(in srgb, var(--text) 70%, transparent);
}

.tray-row__title {
  font-size: 12px;
  line-height: 1.2;
  font-weight: 500;
}

.tray-row--danger .tray-row__title,
.tray-row--danger .tray-row__icon {
  color: var(--red);
}

.tray-row.is-busy {
  opacity: 0.55;
}
</style>
