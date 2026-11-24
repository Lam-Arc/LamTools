<template>
  <div v-if="props.open" class="mobile-session" data-mobile-session-settings>
    <section
      class="mobile-session__page"
      role="dialog"
      aria-modal="true"
      :aria-label="t('会话信息')"
    >
      <header class="mobile-session__head">
        <button
          type="button"
          class="mobile-session__back"
          :aria-label="t('返回')"
          data-mobile-session-back
          @click="emit('close')"
        >
          <ChevronLeft :size="22" :stroke-width="2" aria-hidden="true" />
        </button>
        <h1>{{ t('会话信息') }}</h1>
      </header>

      <div class="mobile-session__body">
        <!-- user:“显示会话名称、参与者 / Agent、关联项目或工作区、当前执行设备、
             创建时间等必要信息”+(信息按组排列；名称点开才进入重命名)。 -->
        <section class="mobile-session__card">
          <button type="button" class="mobile-session__row" data-mobile-session-rename @click="emit('rename')">
            <span class="mobile-session__label">{{ t('会话名称') }}</span>
            <span class="mobile-session__value">{{ props.title || t('新会话') }}</span>
            <ChevronRight :size="16" :stroke-width="2" aria-hidden="true" />
          </button>
          <div class="mobile-session__row is-static">
            <span class="mobile-session__label">{{ t('项目') }}</span>
            <span class="mobile-session__value">{{ props.projectName || t('未归属项目') }}</span>
          </div>
          <div class="mobile-session__row is-static" data-mobile-session-device>
            <span class="mobile-session__label">{{ t('执行设备') }}</span>
            <span class="mobile-session__value" :data-device-state="props.deviceState">{{ props.deviceLabel }}</span>
          </div>
          <div v-if="createdLabel" class="mobile-session__row is-static">
            <span class="mobile-session__label">{{ t('创建时间') }}</span>
            <span class="mobile-session__value">{{ createdLabel }}</span>
          </div>
        </section>

        <section class="mobile-session__card">
          <button
            type="button"
            class="mobile-session__row"
            role="switch"
            :aria-checked="props.pinned ? 'true' : 'false'"
            data-mobile-session-pin
            @click="emit('toggle-pin')"
          >
            <span class="mobile-session__label">{{ t('置顶会话') }}</span>
            <span class="mobile-session__switch" :class="{ 'is-on': props.pinned }" aria-hidden="true"></span>
          </button>
          <button type="button" class="mobile-session__row" data-mobile-session-export @click="emit('export')">
            <span class="mobile-session__label">{{ t('导出会话（Markdown）') }}</span>
            <ChevronRight :size="16" :stroke-width="2" aria-hidden="true" />
          </button>
        </section>

        <!-- user:“删除会话必须是明确的管理操作”+(单独一组、红色，点了还要二次确认)。 -->
        <section class="mobile-session__card">
          <button type="button" class="mobile-session__row is-danger" data-mobile-session-delete @click="emit('delete')">
            <span class="mobile-session__label">{{ t('删除会话') }}</span>
          </button>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'

/**
 * user:“L3 会话设置：顶部 `··· → 会话信息`”+(会话信息单独一页：
 * 基础信息、置顶、导出、删除。执行设备沿用 L2 顶栏的那份状态，不另说一套话)。
 */
const props = defineProps<{
  open: boolean
  title?: string
  projectName?: string
  deviceLabel: string
  deviceState?: 'local' | 'remote' | 'offline'
  createdAt?: string
  pinned?: boolean
}>()

const emit = defineEmits<{
  close: []
  rename: []
  'toggle-pin': []
  export: []
  delete: []
}>()

function formatCreatedAt(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}/${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const createdLabel = computed(() => formatCreatedAt(props.createdAt))
</script>

<style scoped>
.mobile-session {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  background: var(--theme-main-background);
  color: var(--theme-main-text);
}

.mobile-session__page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding-top: var(--native-safe-area-top, 0px);
}

.mobile-session__head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex: 0 0 auto;
  min-height: 52px;
  padding: 0 var(--space-2);
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
}

.mobile-session__head h1 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.mobile-session__back {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-session__back:active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.mobile-session__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4) calc(var(--space-6) + var(--safe-area-bottom));
}

.mobile-session__card {
  overflow: hidden;
  margin-bottom: var(--space-3);
  border-radius: var(--radius);
  background: color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.mobile-session__row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 48px;
  padding: 0 var(--space-3);
  /* width:100% 与左右内边距同用时必须算边框盒，否则每行比卡片宽出一截、右侧文字被裁掉。 */
  box-sizing: border-box;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: inherit;
  text-align: left;
  font: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-session__row + .mobile-session__row {
  border-top: 1px solid color-mix(in srgb, var(--theme-main-text) 6%, transparent);
}

.mobile-session__row:not(.is-static):active {
  background: color-mix(in srgb, var(--theme-main-text) 8%, transparent);
}

.mobile-session__row.is-static {
  cursor: default;
}

/* 没有值的一行（导出）：箭头自己靠到最右，不贴着文字。 */
.mobile-session__row > svg:last-child {
  margin-left: auto;
  color: color-mix(in srgb, var(--theme-main-text) 45%, transparent);
}

.mobile-session__label {
  flex: 0 0 auto;
  font-size: 14px;
}

.mobile-session__value {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
  color: color-mix(in srgb, var(--theme-main-text) 58%, transparent);
  font-size: 14px;
}

.mobile-session__value[data-device-state='offline'] {
  color: color-mix(in srgb, var(--red) 68%, var(--theme-main-text));
}

/* 置顶开关：只有两种状态，不做成可拖动的滑块，点整行即切换。 */
.mobile-session__switch {
  position: relative;
  flex: 0 0 auto;
  width: 40px;
  height: 24px;
  margin-left: auto;
  border-radius: 999px;
  background: color-mix(in srgb, var(--theme-main-text) 22%, transparent);
  transition: background var(--dur-fast, 140ms) ease;
}

.mobile-session__switch::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0, 0, 0, .28);
  transition: transform var(--dur-fast, 140ms) ease;
}

.mobile-session__switch.is-on {
  background: var(--green);
}

.mobile-session__switch.is-on::after {
  transform: translateX(16px);
}

.mobile-session__row.is-danger .mobile-session__label {
  color: color-mix(in srgb, var(--red) 74%, var(--theme-main-text));
}
</style>
