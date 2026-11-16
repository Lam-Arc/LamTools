<script setup lang="ts">
// user:“胶囊式（Pill）列表：横向流式排列多个结果胶囊（Favicon + 截断标题），点击跳转原文”+
// (联网搜索/知识库命中不再堆成整块卡片，一行胶囊就能扫完标题，点一下离开应用看原文。)
// user:“点击用 helpers/openUrl.ts，不要裸调 window.open”+
// (外链统一走 openExternalUrl，桌面端由 Rust 打开系统浏览器，webview 自身不导航。)
// user:“favicon 加载失败降级成首字母圆点”+(取不到站标就画标题首字母，胶囊不会塌成空白方块。)
import { ref } from 'vue'
import { openExternalUrl } from '@/helpers/openUrl'
import { t } from '@/i18n/index.ts'

interface ProcessPillResult {
  title: string
  url?: string
  favicon?: string
  snippet?: string
  source?: string
}

const props = defineProps<{ results: ProcessPillResult[] }>()
const emit = defineEmits<{ open: [result: ProcessPillResult] }>()

/** 站标加载失败的下标；按位记，同一条结果的失败不影响其它胶囊。 */
const failedFavicons = ref<number[]>([])

function isFaviconFailed(index: number): boolean {
  return failedFavicons.value.includes(index)
}

function failFavicon(index: number): void {
  if (!failedFavicons.value.includes(index)) failedFavicons.value = [...failedFavicons.value, index]
}

function displayTitle(result: ProcessPillResult): string {
  const title = String(result.title || '').trim()
  if (title) return title
  return String(result.url || '').trim() || t('未命名结果')
}

function initialOf(result: ProcessPillResult): string {
  return displayTitle(result).slice(0, 1).toUpperCase()
}

async function open(result: ProcessPillResult): Promise<void> {
  emit('open', result)
  const url = String(result.url || '').trim()
  if (url) await openExternalUrl(url)
}
</script>

<template>
  <div v-if="results.length" class="process-pills">
    <button
      v-for="(result, index) in results"
      :key="`${index}-${result.url || result.title}`"
      type="button"
      class="process-pills__pill"
      :title="displayTitle(result)"
      @click="open(result)"
    >
      <span class="process-pills__favicon" aria-hidden="true">
        <img
          v-if="result.favicon && !isFaviconFailed(index)"
          :src="result.favicon"
          alt=""
          loading="lazy"
          @error="failFavicon(index)"
        />
        <span v-else class="process-pills__initial">{{ initialOf(result) }}</span>
      </span>
      <!-- 标题单行截断，完整标题留在 button 的 title 属性上，悬停可读。 -->
      <span class="process-pills__title">{{ displayTitle(result) }}</span>
      <span v-if="result.source" class="process-pills__source">{{ result.source }}</span>
    </button>
  </div>
</template>

<style scoped>
.process-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
  min-width: 0;
}

.process-pills__pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  box-sizing: border-box;
  max-width: 100%;
  height: 24px;
  padding: 0 10px 0 4px;
  border: 1px solid var(--ms-proc-border-color, var(--line, currentColor));
  border-radius: 999px;
  background: color-mix(
    in srgb,
    var(--ms-proc-fill-color, var(--theme-main-text, currentColor)) calc(var(--ms-proc-fill-alpha, 0) * 100%),
    transparent
  );
  color: inherit;
  font: inherit;
  font-size: var(--ms-proc-body-font-size, 12px);
  line-height: 1;
  cursor: pointer;
  backdrop-filter: blur(var(--ms-proc-blur, 0px));
  -webkit-backdrop-filter: blur(var(--ms-proc-blur, 0px));
  transition: border-color 0.16s ease, color 0.16s ease;
}

.process-pills__pill:hover {
  border-color: color-mix(in srgb, var(--blue, currentColor) 46%, transparent);
}

.process-pills__pill:focus-visible {
  outline: var(--focus-ring-width, 2px) solid var(--focus-ring-color, currentColor);
  outline-offset: var(--focus-ring-offset, 2px);
}

.process-pills__favicon {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  width: 16px;
  height: 16px;
  overflow: hidden;
  border-radius: var(--ms-proc-radius-sm, 8px);
}

.process-pills__favicon img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.process-pills__initial {
  display: inline-grid;
  place-items: center;
  width: 100%;
  height: 100%;
  background: color-mix(in srgb, var(--blue, currentColor) 26%, transparent);
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 88%, transparent);
  font-size: calc(var(--ms-proc-body-font-size, 12px) - 3px);
  font-weight: 600;
}

.process-pills__title {
  min-width: 0;
  max-width: 22ch;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 82%, transparent);
}

.process-pills__source {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--theme-main-text, currentColor) 48%, transparent);
  font-size: calc(var(--ms-proc-body-font-size, 12px) - 2px);
}

@media (prefers-reduced-motion: reduce) {
  .process-pills__pill {
    transition: none;
  }
}
</style>
