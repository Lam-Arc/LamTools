<template>
  <div v-if="props.open" class="mobile-context" data-mobile-context-picker>
    <button
      type="button"
      class="mobile-context__backdrop"
      :aria-label="t('关闭')"
      @click="emit('close')"
    ></button>
    <section
      class="mobile-context__sheet"
      role="dialog"
      aria-modal="true"
      :aria-label="t('运行环境')"
    >
      <header class="mobile-context__head">
        <strong>{{ t('运行环境') }}</strong>
        <button type="button" class="mobile-context__close" :aria-label="t('关闭')" data-mobile-context-close @click="emit('close')">
          <X :size="18" :stroke-width="2" aria-hidden="true" />
        </button>
      </header>

      <!-- user:“项目不应该和环境放在一个选项内”+(这张面板只说“在哪台设备上跑”；
           项目是会话列表里可折叠的父级，不再和这里混在一起)。 -->
      <button type="button" class="mobile-context__row is-active" :aria-current="'true'" data-mobile-context-env>
        <MonitorSmartphone :size="18" :stroke-width="1.8" aria-hidden="true" />
        <span class="mobile-context__row-body">
          <span class="mobile-context__row-title">{{ props.environmentName || t('本机 Android') }}</span>
          <span class="mobile-context__row-sub">{{ t('Agent 在这台设备上执行') }}</span>
        </span>
        <Check :size="16" :stroke-width="2.2" aria-hidden="true" />
      </button>
      <!-- user:“连接的入口在哪里？点击选择环境应该提供入口，这样才够直觉”+
           (选环境的面板里直接给一条可点的「连接电脑」：扫码/粘贴票据 → 设置里的设备连接页；已连上时同一行改成「管理连接」)。 -->
      <button
        type="button"
        class="mobile-context__row"
        data-mobile-context-connect
        @click="emit('connect')"
      >
        <Link2 :size="18" :stroke-width="1.8" aria-hidden="true" />
        <span class="mobile-context__row-body">
          <span class="mobile-context__row-title">{{ props.remoteConnected ? t('管理连接') : t('连接电脑') }}</span>
          <span class="mobile-context__row-sub">{{ props.remoteConnected ? t('已连接电脑 · 查看状态或断开') : t('扫码或粘贴票据，把手机接到电脑上') }}</span>
        </span>
        <ChevronRight :size="16" :stroke-width="2" aria-hidden="true" />
      </button>
      <p class="mobile-context__hint" data-mobile-context-remote-hint>
        {{ t('远程电脑接入后，会在这里列出它的设备。') }}
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { Check, ChevronRight, Link2, MonitorSmartphone, X } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'

/**
 * user:“点击后打开环境与项目选择面板”→“项目不应该和环境放在一个选项内”+
 * (这里只负责运行环境：目前只有本机 Android，远程电脑接入后在同一面板里列出；
 *  项目与会话在列表里以可折叠分组呈现，不在这张面板里选)。
 */
const props = defineProps<{
  open: boolean
  environmentName?: string
  /** 当前是否已经连着电脑：同一行在「连接电脑 / 管理连接」之间切换。 */
  remoteConnected?: boolean
}>()

const emit = defineEmits<{
  close: []
  connect: []
}>()
</script>

<style scoped>
.mobile-context {
  position: fixed;
  inset: 0;
  z-index: var(--z-popover);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
}

.mobile-context__backdrop {
  position: absolute;
  inset: 0;
  border: 0;
  padding: 0;
  background: rgba(0, 0, 0, .48);
}

.mobile-context__sheet {
  position: relative;
  z-index: 1;
  max-height: 78vh;
  overflow-y: auto;
  /* user:“这里中间没有对齐，改一下”+(这张面板在 .workspace-shell 之外，拿不到壳里定义的
     --safe-area-bottom；整个 padding 简写会因为一个未定义变量被判无效、全部退成 0，
     标题于是贴着屏幕左缘被裁掉。这里给每个变量兜底，底部再多留一档避开系统手势条)。 */
  padding: var(--space-3) var(--space-4) calc(var(--space-5) + var(--safe-area-bottom, 0px));
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  background: var(--theme-main-background);
  color: var(--theme-main-text);
  box-shadow: var(--shadow-md);
}

.mobile-context__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 44px;
}

.mobile-context__close {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
}

.mobile-context__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 48px;
  padding: 6px var(--space-2);
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-context__row.is-active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.mobile-context__row-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.mobile-context__row-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
}

.mobile-context__row-sub {
  font-size: 12px;
  color: color-mix(in srgb, var(--theme-main-text) 55%, transparent);
}

.mobile-context__hint {
  margin: var(--space-1) var(--space-2);
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
  font-size: 12px;
  line-height: 1.45;
}
</style>
