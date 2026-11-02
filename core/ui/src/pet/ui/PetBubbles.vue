<script setup lang="ts">
/**
 * 桌宠头顶的交互气泡：单卡 + 胶囊。
 *
 * user:"多请求时，依旧只显示一张卡，右上角显示几杠几，左上角显示来源：
 * 项目-会话-子代理，几杠几左右加上箭头可切换"+
 * "小，小，小，小，能多小就多小，折叠为小圆，只显示待选择数量"+
 * "这个东西不要用玻璃样式，用纯黑和纯白"+
 * (卡片象牙白底黑字、折叠球黄底黑字、无模糊；展开态一张卡只显示当前一条请求：来源面包屑 +
 *  页码/箭头 + 一句话请求 + 编号选项 + 回答框；折叠态是一枚只显示待处理
 *  数量的胶囊，点它展开。)
 */
import { computed, onBeforeUnmount, reactive, ref, watch, type PropType } from 'vue'
import type { BubbleState, PetRuntime } from './usePetRuntime.ts'

const props = defineProps<{ runtime: PetRuntime }>()
const drafts = ref<Record<string, string>>({})

const scale = computed(() => Math.max(0.1, props.runtime.overlay.width / Math.max(1, window.innerWidth)))
const visible = computed(() => props.runtime.bubbles.value.filter(bubble => !bubble.dismissed))

/** 展开态 / 折叠成胶囊；activeId 是当前翻到的那一条。 */
const ui = reactive({ expanded: true, activeId: '' })

const activeIndex = computed(() => {
  const list = visible.value
  if (list.length === 0) return -1
  const index = list.findIndex(bubble => bubble.id === ui.activeId)
  return index >= 0 ? index : 0
})
const active = computed<BubbleState | null>(() => visible.value[activeIndex.value] ?? null)
const pendingCount = computed(() => visible.value.length)
// user:"主窗口聚焦时不显示气泡"+(用户在 Sunday 主界面里，气泡让位给主界面。)
const hidden = computed(() => props.runtime.mainFocused.value)

// user:"这个5秒自动折叠，应该是我的鼠标离开了它再折叠。如果我的鼠标只要挪上去了，
// 就重新计时啊！"+
// (倒计时只在鼠标不在卡片上、也没有输入焦点时走：进入卡片/聚焦立刻清零，
//  离开/失焦才重新开始 5 秒。鼠标悬停时永远不折叠。)
const hovering = ref(false)
const editing = ref(false)
let collapseTimer = 0
function clearCollapse(): void {
  if (collapseTimer) window.clearTimeout(collapseTimer)
  collapseTimer = 0
}
function scheduleCollapse(): void {
  clearCollapse()
  if (!ui.expanded || hovering.value || editing.value) return
  collapseTimer = window.setTimeout(() => {
    collapseTimer = 0
    if (!hovering.value && !editing.value) ui.expanded = false
  }, 5000)
}
function onPointerEnter(): void {
  hovering.value = true
  clearCollapse()
}
function onPointerLeave(): void {
  hovering.value = false
  scheduleCollapse()
}
function onFocusIn(): void {
  editing.value = true
  clearCollapse()
}
function onFocusOut(): void {
  editing.value = false
  scheduleCollapse()
}
watch(() => [ui.expanded, ui.activeId, pendingCount.value], scheduleCollapse, { immediate: true })
onBeforeUnmount(() => {
  clearCollapse()
})

watch(active, value => {
  if (value && value.id !== ui.activeId) ui.activeId = value.id
}, { immediate: true })

function step(delta: number): void {
  const list = visible.value
  if (list.length === 0) return
  const next = (activeIndex.value + delta + list.length) % list.length
  ui.activeId = list[next].id
  ui.expanded = true
}

function optionsFor(bubble: BubbleState): BubbleState['options'] {
  if (bubble.options.length > 0) return bubble.options
  if (bubble.requestId && !bubble.isQuestion) {
    return [
      { id: 'approve', label: '允许', response: 'approve' },
      { id: 'deny', label: '拒绝', response: 'deny' },
    ]
  }
  return []
}

function submit(bubbleId: string): void {
  const text = (drafts.value[bubbleId] || '').trim()
  if (!text) return
  void props.runtime.answerBubble(bubbleId, text)
  drafts.value[bubbleId] = ''
}

// 实测尺寸：胶囊宽度随数字变化，展开卡高度随内容变化；定位按真实尺寸算。
const size = ref({ width: 260, height: 160 })
const element = ref<HTMLElement | null>(null)
let observer: ResizeObserver | null = null

function setElement(value: unknown): void {
  const next = value instanceof HTMLElement ? value : null
  // 内联 ref 每次渲染都会以同一个元素再调一次；只有元素真的换了才重置尺寸，
  // 否则会 size → 渲染 → ref → size 的递归更新。
  if (next === element.value) return
  element.value = next
  if (observer) observer.disconnect()
  if (!next) return
  // 换元素时先给该形态的兜底尺寸，再由观察器量真实值；不要在 RO 回调里
  // 改同一元素的尺寸（会触发 "ResizeObserver loop" 通知）。
  size.value = ui.expanded ? { width: 260, height: 160 } : { width: 20, height: 20 }
  if (typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(entries => {
    const target = entries[0]?.target as HTMLElement | undefined
    if (!target) return
    // 必须用边框盒：contentRect 是内容盒，拿它回写卡片宽度会每帧缩掉
    // padding+border，卡片会一路缩成一条竖线（2026-11-01 用户截图）。
    const rect = target.getBoundingClientRect()
    const width = Math.ceil(rect.width)
    const height = Math.ceil(rect.height)
    if (width > 0 && height > 0 && (size.value.width !== width || size.value.height !== height)) {
      size.value = { width, height }
    }
  })
  observer.observe(next)
}

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
})

const position = computed(() => {
  // user:"气泡跟随桌宠走"+(读取每帧计数，角色移动/被拖走时位置重算。)
  void props.runtime.frameTick.value
  const bubble = active.value
  const world = props.runtime.world.value
  const overlay = props.runtime.overlay
  if (!bubble || !world) return null
  const state = world.renderStates().find(item => item.id === bubble.petId)
  const pet = world.get(bubble.petId)
  const scaleValue = scale.value
  const anchorX = pet ? pet.position.x : overlay.x + overlay.width / 2
  const anchorY = state ? state.rect.y : (pet ? pet.position.y : overlay.y + overlay.height / 2)
  const anchorCssX = (anchorX - overlay.x) / scaleValue
  const anchorCssY = (anchorY - overlay.y) / scaleValue
  const petCssHeight = state ? state.rect.height / scaleValue : 0
  const width = Math.min(size.value.width, window.innerWidth - 16)
  const height = size.value.height
  // user:"默认显示位置在桌宠左上方而不是正上方"+
  // (卡片右下角贴着宠物中线左侧 8px；左边放不下时翻到右上方。)
  const gap = 8
  const preferredLeft = anchorCssX - width - gap
  let left = preferredLeft >= 8
    ? preferredLeft
    : Math.min(anchorCssX + gap, window.innerWidth - width - 8)
  left = Math.min(Math.max(8, left), window.innerWidth - width - 8)
  let top = anchorCssY - 10 - height
  if (top < 8) {
    top = Math.max(8, Math.min(anchorCssY + petCssHeight + 10, window.innerHeight - height - 8))
  }
  return { left, top, width }
})
</script>

<template>
  <div class="pet-bubbles" data-region="pet-bubbles">
    <!-- 折叠态：只显示待选择数量的胶囊 -->
    <button
      v-if="active && !hidden && !ui.expanded"
      :ref="setElement"
      type="button"
      class="pet-bubble-badge"
      data-pet-hit
      :style="position ? { left: `${position.left}px`, top: `${position.top}px` } : undefined"
      :title="`${pendingCount} 项待处理，点击展开`"
      :aria-label="`${pendingCount} 项待处理`"
      @click="ui.expanded = true"
    >{{ pendingCount > 9 ? '9+' : pendingCount }}</button>

    <!-- 展开态：一张卡，只显示当前一条 -->
    <section
      v-else-if="active && !hidden && position"
      :ref="setElement"
      class="pet-bubble"
      data-pet-hit
      :style="{ left: `${position.left}px`, top: `${position.top}px`, width: `${position.width}px` }"
      @pointerenter="onPointerEnter"
      @pointerleave="onPointerLeave"
      @focusin="onFocusIn"
      @focusout="onFocusOut"
    >
      <header class="pet-bubble__meta">
        <span class="pet-bubble__source" :title="active.source || active.sessionId">{{ active.source || active.sessionId }}</span>
        <span v-if="pendingCount > 1" class="pet-bubble__pager">
          <button type="button" aria-label="上一条" @click.stop="step(-1)">‹</button>
          <span>{{ activeIndex + 1 }}/{{ pendingCount }}</span>
          <button type="button" aria-label="下一条" @click.stop="step(1)">›</button>
        </span>
        <button type="button" class="pet-bubble__close" title="折叠为胶囊（不会拒绝审批或取消任务）" @click.stop="ui.expanded = false">×</button>
      </header>

      <p class="pet-bubble__subject">{{ active.subject || active.title }}</p>

      <div class="pet-bubble__body">
        <p v-if="active.body && active.body !== active.subject" class="pet-bubble__detail">{{ active.body }}</p>
        <div v-if="optionsFor(active).length" class="pet-bubble__options">
          <div v-for="(option, index) in optionsFor(active)" :key="option.id" class="pet-bubble__option-row">
            <span class="pet-bubble__option-index" aria-hidden="true">{{ index + 1 }}</span>
            <button
              type="button"
              class="pet-bubble__option"
              :disabled="active.handling"
              @click="runtime.decideBubble(active.id, option)"
            >{{ option.label }}</button>
          </div>
        </div>
        <div class="pet-bubble__reply">
          <input
            v-model="drafts[active.id]"
            type="text"
            :placeholder="active.isQuestion ? '输入你的回答…' : '直接回复这条请求…'"
            @keydown.enter.prevent="submit(active.id)"
          >
          <button type="button" :disabled="active.handling" @click="submit(active.id)">发送</button>
        </div>
        <div v-if="active.error" class="pet-bubble__error">{{ active.error }}</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pet-bubbles {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

/* user:"能多小就多小"+(纯黑纯白、无模糊；卡片宽度 280，字号与内边距全部收紧。) */
.pet-bubble {
  position: absolute;
  pointer-events: auto;
  box-sizing: border-box;
  padding: 6px 8px 8px;
  border-radius: var(--radius);
  border: 1px solid rgba(0, 0, 0, 0.14);
  background: #f6f1e7;
  color: #111;
  box-shadow: 0 8px 18px rgba(0, 0, 0, 0.28);
  overflow: hidden;
}

/* 来源 + 页码 + 折叠：一行小字，不抢请求正文。 */
.pet-bubble__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 10px;
  line-height: 1.4;
  color: rgba(0, 0, 0, 0.55);
}

.pet-bubble__source {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pet-bubble__pager {
  display: flex;
  flex: none;
  align-items: center;
  gap: 1px;
  color: rgba(0, 0, 0, 0.68);
  font-variant-numeric: tabular-nums;
}

.pet-bubble__pager button {
  width: 16px;
  height: 16px;
  padding: 0;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: rgba(0, 0, 0, 0.68);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
}

.pet-bubble__pager button:hover {
  background: rgba(0, 0, 0, 0.08);
  color: #000;
}

.pet-bubble__close {
  flex: none;
  padding: 0 1px;
  border: 0;
  background: transparent;
  color: rgba(0, 0, 0, 0.55);
  font-size: 12px;
  line-height: 1.4;
  cursor: pointer;
}

.pet-bubble__close:hover {
  color: #000;
}

/* 一句话请求：最多三行，再多也不撑大卡片。 */
.pet-bubble__subject {
  display: -webkit-box;
  margin: 4px 0 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  color: #111;
  font-size: 11.5px;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.pet-bubble__body {
  display: grid;
  gap: 6px;
  margin-top: 6px;
}

.pet-bubble__detail {
  margin: 0;
  color: rgba(0, 0, 0, 0.62);
  font-size: 11px;
  line-height: 1.4;
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow-wrap: anywhere;
}

.pet-bubble__options {
  display: grid;
  gap: 1px;
}

.pet-bubble__option-row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr);
  align-items: center;
  gap: 6px;
}

.pet-bubble__option-index {
  color: rgba(0, 0, 0, 0.4);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

.pet-bubble__option {
  min-height: 24px;
  padding: 2px 6px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: #111;
  font: inherit;
  font-size: 11.5px;
  font-weight: 550;
  text-align: left;
  cursor: pointer;
}

.pet-bubble__option:hover:not(:disabled) {
  background: rgba(0, 0, 0, 0.07);
}

.pet-bubble__option:active:not(:disabled) {
  background: rgba(0, 0, 0, 0.11);
}

.pet-bubble__option:disabled {
  opacity: 0.45;
  cursor: default;
}

.pet-bubble__reply {
  display: flex;
  gap: 6px;
}

.pet-bubble__reply input {
  flex: 1;
  min-width: 0;
  padding: 5px 8px;
  border: 1px solid rgba(0, 0, 0, 0.18);
  border-radius: var(--radius-sm);
  background: transparent;
  color: #111;
  font: inherit;
  font-size: 11px;
  outline: none;
}

.pet-bubble__reply input::placeholder {
  color: rgba(0, 0, 0, 0.4);
}

/* 唯一的实心按钮：白底黑字。 */
.pet-bubble__reply button {
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: #111;
  color: #f6f1e7;
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}

.pet-bubble__reply button:disabled {
  opacity: 0.45;
  cursor: default;
}

.pet-bubble__error {
  color: rgba(0, 0, 0, 0.72);
  font-size: 10.5px;
  line-height: 1.35;
}

/* user:"折叠不要胶囊了，一个小圆即可"+(只显示待处理数量的小圆点。) */
.pet-bubble-badge {
  position: absolute;
  pointer-events: auto;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 1px solid rgba(0, 0, 0, 0.16);
  border-radius: 50%;
  background: #f6f1e7;
  color: #000;
  font: inherit;
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1;
  cursor: pointer;
}

.pet-bubble-badge:hover {
  border-color: rgba(0, 0, 0, 0.4);
}
</style>
