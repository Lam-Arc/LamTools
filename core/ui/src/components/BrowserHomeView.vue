<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ArrowRight, BookOpen, ChevronDown, Globe } from 'lucide-vue-next'
import { t } from '@/i18n'
// user:“browser 首页 UI参考，核心仅为中间的输入栏，上方的网址栏和标签页，其余均为可选自定义组件或不实现”+
// (首页只做三件：可关闭的问候语、中间那个大号输入栏、可选快捷入口。参考图里的 Explore / Quick actions /
//  Weather / Notes 一律不做，改在底部留一个扩展位，后续卡片挂在那里，首页本身不再长东西)。
import { greetingText, homeQuickActionIds, readOptionalVisible, writeOptionalVisible, type BrowserHomeActionId, type HomeOptionalId } from '@/split/browserHome'
import { getStoredSearchEngine, SEARCH_ENGINES, setStoredSearchEngine, type SearchEngineId } from '@/split/browserAddress'
import type { WorkspaceController } from '@/workspace/types'

const props = defineProps<{ controller?: WorkspaceController; pane?: string; busy?: boolean }>()
const emit = defineEmits<{ submit: [text: string] }>()

const query = ref('')
const field = ref<HTMLInputElement | null>(null)
const engineMenuOpen = ref(false)
const activeEngine = ref(getStoredSearchEngine())
function selectEngine(id: SearchEngineId) {
  activeEngine.value = setStoredSearchEngine(id)
  engineMenuOpen.value = false
  field.value?.focus()
}
// user:“问候语…可关闭并记住偏好”+(开关从存储起步：关过就一直是关的，直到用户自己再打开)。
const greetingOn = ref(readOptionalVisible('greeting'))
// user:“四个方形快捷入口做成可选…可关闭并记住偏好”+(同一条存储规则，关掉之后首页不再摆按钮)。
const actionsOn = ref(readOptionalVisible('actions'))
const customizeOpen = ref(false)
function setOptional(id: HomeOptionalId, visible: boolean) {
  if (id === 'greeting') greetingOn.value = visible
  else actionsOn.value = visible
  writeOptionalVisible(id, visible)
}
// user:“问候语（按时段：早上好/下午好/晚上好）+ 一行副标题，可关闭并记住偏好”+
// (时段判定在 browserHome.greetingSlot，这里只把结论翻成当前语言的一句问候)。
const greeting = computed(() => t(greetingText(new Date().getHours())))
const actionIds = computed(() => actionsOn.value
  ? homeQuickActionIds({ hasController: Boolean(props.controller), hasPane: Boolean(props.pane) })
  : [])
const actions = computed(() => actionIds.value.map(id => ({
  id,
  label: t(id === 'web' ? '网页' : '资料库'),
  hint: t(id === 'web' ? '回到输入栏' : '打开资料库页面'),
})))

/** 进入首页即聚焦；切回这个标签时父组件还会再调一次。 */
function focus() { void nextTick(() => { field.value?.focus(); field.value?.select() }) }
function clearAndKeepFocus() { query.value = ''; field.value?.focus() }
// user:“可选组件做成可关闭并记住偏好”+(两个 × 都只是“关掉并记住”，真正的开关在下面的首页设置里，
//  所以关掉之后还能打开 —— 不会出现“点没了就再也找不回来”)。
function dismissGreeting() { setOptional('greeting', false) }
function dismissActions() { setOptional('actions', false); customizeOpen.value = true }
function toggleOptional(id: HomeOptionalId) { setOptional(id, id === 'greeting' ? !greetingOn.value : !actionsOn.value) }
/**
 * user:“Enter 提交 → 创建/导航该标签的 webview”+
 * (首页不自己解析地址：只把原话交给父组件，由它走地址栏那条唯一的 navigate ——
 *  于是“像网址就打开、否则搜索”的规则只有一份，两处永远一致)。
 */
function submit() {
  const text = query.value.trim()
  if (!text || props.busy) return
  emit('submit', text)
}
/** user:“把库和easy file统合到一起”+(同一个入口打开包含项目文件的资料库)。 */
function runAction(id: BrowserHomeActionId) {
  if (id === 'web') { focus(); return }
  const controller = props.controller, pane = props.pane
  if (!controller || !pane) return
  controller.add('page', 'library', t('资料库'), pane)
}
defineExpose({ focus })
</script>
<template>
  <div class="browser-home" data-browser-home>
    <div class="browser-home-main">
      <header v-if="greetingOn" class="browser-home-greeting">
        <h2 class="browser-home-title" data-browser-home-greeting>{{ greeting }}</h2>
        <p class="browser-home-subtitle">{{ t('输入网址开始，或者把想查的东西写在这里') }}</p>
      </header>
      <!-- 中央输入栏是这张首页唯一的视觉重点：大号、圆角、宽度随 pane 收窄。 -->
      <form class="browser-home-search" role="search" @submit.prevent="submit">
        <!-- user:“左侧的那个图标可以切换引擎，bing，谷歌，百度”+(点击左侧图标打开引擎切换菜单并持久化选择) -->
        <div class="browser-home-engine-wrap">
          <button
            class="browser-home-engine-btn"
            type="button"
            data-browser-engine-switch
            :title="t('切换搜索引擎：{0}', { 0: activeEngine.name })"
            :aria-label="t('切换搜索引擎')"
            :aria-expanded="engineMenuOpen"
            @click.stop="engineMenuOpen = !engineMenuOpen"
          >
            <Globe :size="16" :stroke-width="1.6" aria-hidden="true" />
            <span class="browser-home-engine-name">{{ activeEngine.name }}</span>
            <ChevronDown :size="11" :stroke-width="1.8" aria-hidden="true" />
          </button>
          <div v-if="engineMenuOpen" class="browser-home-engine-menu" role="menu">
            <button
              v-for="eng in SEARCH_ENGINES"
              :key="eng.id"
              type="button"
              role="menuitem"
              class="browser-home-engine-item"
              :class="{ 'is-active': eng.id === activeEngine.id }"
              :data-browser-engine-option="eng.id"
              @click="selectEngine(eng.id)"
            >{{ eng.name }}</button>
          </div>
        </div>
        <input
          ref="field"
          v-model="query"
          type="text"
          inputmode="url"
          autocomplete="off"
          spellcheck="false"
          :aria-label="t('搜索或输入网址')"
          :placeholder="t('搜索或输入网址')"
          @keydown.esc.stop.prevent="clearAndKeepFocus"
        />
        <button class="browser-home-open" type="submit" :disabled="!query.trim() || busy" :title="t('打开')" :aria-label="t('打开')"><ArrowRight :size="15" /></button>
      </form>
      <p v-if="busy" class="browser-home-status" role="status">{{ t('正在打开…') }}</p>
    </div>
    <!-- user:“四个方形快捷入口…可关闭并记住偏好”+(快捷入口组不再显示右上角 × 按钮，保留左下设置开关)。 -->
    <div v-if="actions.length" class="browser-home-actions">
      <button v-for="action in actions" :key="action.id" class="browser-home-action" type="button" :title="action.hint" :data-browser-home-action="action.id" @click="runAction(action.id)">
        <component :is="action.id === 'web' ? Globe : BookOpen" :size="16" :stroke-width="1.7" aria-hidden="true" />
        <span>{{ action.label }}</span>
      </button>
    </div>
    <!-- user:“可选组件…可关闭并记住偏好”+(一个常驻的小设置入口：两块的开关都在这里，关了能打开回来)。 -->
    <div class="browser-home-customize">
      <div v-if="customizeOpen" class="browser-home-customize-panel" role="group" :aria-label="t('首页设置')" @keydown.esc.stop.prevent="customizeOpen = false">
        <button class="browser-home-customize-row" type="button" role="switch" :aria-checked="greetingOn" data-browser-home-toggle="greeting" @click="toggleOptional('greeting')">
          <span>{{ t('问候语') }}</span><i class="browser-home-switch" aria-hidden="true"></i>
        </button>
        <button class="browser-home-customize-row" type="button" role="switch" :aria-checked="actionsOn" data-browser-home-toggle="actions" @click="toggleOptional('actions')">
          <span>{{ t('快捷入口') }}</span><i class="browser-home-switch" aria-hidden="true"></i>
        </button>
      </div>
      <button class="browser-home-customize-toggle" type="button" :title="t('首页设置')" :aria-label="t('首页设置')" :aria-expanded="customizeOpen" @click="customizeOpen = !customizeOpen">⋯</button>
    </div>
    <!-- 自定义组件扩展位：后续卡片（参考图里的 Explore / 天气 / 便签）挂这里，接不上真实数据的就不加。 -->
    <slot name="cards" />
  </div>
</template>
<style scoped>
/* 首页占满 pane：没有辅助内容时也不会出现滚动条抖动（高度只由父级给，自己不再撑高）。 */
.browser-home { box-sizing: border-box; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-4); width: 100%; height: 100%; min-height: 0; padding: var(--space-4); overflow: auto; color: var(--theme-main-text); background: linear-gradient(180deg, color-mix(in srgb, var(--theme-main-text) 4%, transparent) 0%, transparent 55%); }
.browser-home-main { display: flex; flex-direction: column; align-items: center; gap: var(--space-3); width: 100%; max-width: 640px; }
/* user:“一句大标题问候 + 一句副标题”+(浅色深色都只看主文字色，不引入新颜色)。 */
.browser-home-greeting { position: relative; display: flex; flex-direction: column; align-items: center; gap: 4px; text-align: center; }
.browser-home-title { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: .01em; }
.browser-home-subtitle { margin: 0; font-size: 12px; color: color-mix(in srgb, var(--theme-main-text) 62%, transparent); }
.browser-home-dismiss { position: absolute; top: -4px; right: -22px; display: grid; place-items: center; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: color-mix(in srgb, var(--theme-main-text) 50%, transparent); font: inherit; font-size: 13px; line-height: 1; cursor: pointer; }
.browser-home-dismiss:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); color: var(--theme-main-text); }
/* user:“居中、大号、圆角（参考图比例，宽约 520–640px，随 pane 收窄自适应）”+ */
.browser-home-search { display: flex; align-items: center; gap: var(--space-2); box-sizing: border-box; width: min(100%, 640px); min-height: 54px; padding: 0 var(--space-2) 0 var(--space-3); border: 1px solid color-mix(in srgb, var(--theme-main-text) 16%, transparent); border-radius: 999px; background: var(--theme-composer-background); color: var(--theme-composer-text); box-shadow: 0 10px 30px color-mix(in srgb, #000 12%, transparent); }
.browser-home-search:focus-within { border-color: color-mix(in srgb, var(--theme-main-text) 40%, transparent); }
.browser-home-engine-wrap { position: relative; flex: 0 0 auto; }
.browser-home-engine-btn { display: inline-flex; align-items: center; gap: 4px; height: 32px; padding: 0 8px; border: 0; border-radius: 999px; background: color-mix(in srgb, var(--theme-composer-text) 8%, transparent); color: color-mix(in srgb, var(--theme-composer-text) 82%, transparent); font: inherit; font-size: 12px; cursor: pointer; }
.browser-home-engine-btn:hover { background: color-mix(in srgb, var(--theme-composer-text) 14%, transparent); color: var(--theme-composer-text); }
.browser-home-engine-name { font-weight: 500; }
.browser-home-engine-menu { position: absolute; left: 0; top: calc(100% + 6px); z-index: 10; display: flex; flex-direction: column; min-width: 112px; padding: 4px; border: 1px solid color-mix(in srgb, var(--theme-main-text) 16%, transparent); border-radius: var(--radius-sm); background: var(--theme-main-background, var(--theme-composer-background)); box-shadow: 0 10px 26px color-mix(in srgb, #000 22%, transparent); }
.browser-home-engine-item { padding: 6px 10px; border: 0; border-radius: calc(var(--radius-sm) - 2px); background: transparent; color: var(--theme-main-text); font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.browser-home-engine-item:hover, .browser-home-engine-item.is-active { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
.browser-home-search input { flex: 1; min-width: 0; border: 0; outline: none !important; background: transparent; color: inherit; font: inherit; font-size: 15px; }
.browser-home-search input::placeholder { color: color-mix(in srgb, currentColor 60%, transparent); }
.browser-home-open { display: grid; flex: 0 0 auto; place-items: center; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 50%; background: color-mix(in srgb, var(--theme-composer-text) 10%, transparent); color: inherit; cursor: pointer; }
.browser-home-open:hover:not(:disabled) { background: color-mix(in srgb, var(--theme-composer-text) 18%, transparent); }
.browser-home-open:disabled { opacity: .4; cursor: default; }
.browser-home-status { margin: 0; font-size: 11px; color: color-mix(in srgb, var(--theme-main-text) 60%, transparent); }
.browser-home-actions { display: flex; flex-wrap: wrap; justify-content: center; gap: var(--space-2); width: 100%; max-width: 640px; }
.browser-home-action { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; box-sizing: border-box; width: 78px; height: 66px; border: 1px solid color-mix(in srgb, var(--theme-main-text) 10%, transparent); border-radius: var(--radius-sm); background: color-mix(in srgb, var(--theme-main-text) 5%, transparent); color: color-mix(in srgb, var(--theme-main-text) 76%, transparent); font: inherit; font-size: 11px; cursor: pointer; }
.browser-home-action:hover { background: color-mix(in srgb, var(--theme-main-text) 10%, transparent); color: var(--theme-main-text); }
/* 快捷入口的关闭按钮贴在按钮组右上角（与问候语同一个 × 手感，但相对的是这一组）。 */
.browser-home-actions { position: relative; }
.browser-home-dismiss-actions { top: -10px; right: -18px; }
/* 首页设置：常驻的小入口 + 一个只含两个开关的轻面板（不做弹窗、不遮页面）。 */
.browser-home-customize { position: relative; display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.browser-home-customize-toggle { display: grid; place-items: center; width: 24px; height: 24px; padding: 0; border: 0; border-radius: 50%; background: transparent; color: color-mix(in srgb, var(--theme-main-text) 45%, transparent); font: inherit; font-size: 14px; line-height: 1; cursor: pointer; }
.browser-home-customize-toggle:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); color: var(--theme-main-text); }
.browser-home-customize-panel { position: absolute; bottom: 30px; right: 0; z-index: 1; display: flex; flex-direction: column; min-width: 132px; padding: 4px; border: 1px solid color-mix(in srgb, var(--theme-main-text) 14%, transparent); border-radius: var(--radius-sm); background: var(--theme-main-background, var(--theme-composer-background)); box-shadow: 0 8px 24px color-mix(in srgb, #000 16%, transparent); }
.browser-home-customize-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); padding: 4px 6px; border: 0; border-radius: calc(var(--radius-sm) - 2px); background: transparent; color: var(--theme-main-text); font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.browser-home-customize-row:hover { background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent); }
/* 开关只有开/关两种画法，颜色全部来自主文字色。 */
.browser-home-switch { position: relative; flex: 0 0 auto; width: 22px; height: 12px; border-radius: 999px; background: color-mix(in srgb, var(--theme-main-text) 22%, transparent); }
.browser-home-switch::after { content: ''; position: absolute; top: 2px; left: 2px; width: 8px; height: 8px; border-radius: 50%; background: var(--theme-main-background, #fff); transition: transform .12s ease; }
.browser-home-customize-row[aria-checked="true"] .browser-home-switch { background: color-mix(in srgb, var(--theme-main-text) 62%, transparent); }
.browser-home-customize-row[aria-checked="true"] .browser-home-switch::after { transform: translateX(10px); }
</style>
