<template>
  <!-- user:“注意出入口”+(抽屉是自绘弹层：传送到 body，避免被外壳的层叠与裁剪吃掉)。 -->
  <Teleport to="body">
    <div v-if="open" class="mobile-tabs" data-mobile-tabs @click.self="emit('close')">
    <section class="mobile-tabs__sheet" role="dialog" aria-modal="true" :aria-label="t('标签页')">
      <header class="mobile-tabs__head">
        <h2 class="mobile-tabs__heading">{{ t("标签页") }}</h2>
        <button
          type="button"
          class="mobile-tabs__done"
          data-mobile-tabs-done
          @click="emit('close')"
        >{{ t("完成") }}</button>
      </header>

      <ul class="mobile-tabs__list">
        <!-- user:“桌面的分屏标签页对于手机来说，等于换页”+(会话本身也算一页：
             它始终排在最前，选中它就是回到对话)。 -->
        <li class="mobile-tabs__row" :class="{ 'is-active': !activeId }">
          <button
            type="button"
            class="mobile-tabs__pick"
            data-mobile-tabs-conversation
            :aria-current="!activeId ? 'page' : undefined"
            @click="emit('select', '')"
          >
            <MessageCircle :size="17" :stroke-width="1.8" aria-hidden="true" />
            <span class="mobile-tabs__title">{{ sessionTitle || t("会话") }}</span>
          </button>
        </li>

        <li
          v-for="item in tabs"
          :key="item.id"
          class="mobile-tabs__row"
          :class="{ 'is-active': item.id === activeId }"
          :data-mobile-tabs-row="item.id"
        >
          <button
            type="button"
            class="mobile-tabs__pick"
            :data-mobile-tabs-item="item.id"
            :aria-current="item.id === activeId ? 'page' : undefined"
            @click="emit('select', item.id)"
          >
            <component :is="iconFor(item.kind)" :size="17" :stroke-width="1.8" aria-hidden="true" />
            <span class="mobile-tabs__title">{{ item.title || t("标签页") }}</span>
          </button>
          <button
            type="button"
            class="mobile-tabs__close"
            :aria-label="t('关闭页面')"
            :data-mobile-tabs-close="item.id"
            @click.stop="emit('close-tab', item.id)"
          >
            <X :size="16" :stroke-width="2" aria-hidden="true" />
          </button>
        </li>
      </ul>

      <p v-if="!tabs.length" class="mobile-tabs__empty">{{ t("还没有打开别的页面") }}</p>
    </section>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { FileText, Globe, MessageCircle, SquareTerminal, X } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'

/**
 * user:“会话内右上角有没有标签页抽屉？在手机端……应该收进标签页抽屉”+
 * “注意出入口，进来页之后要能切、能返回”+(手机没有并排分屏：标签就是页；
 * 这张抽屉同时是入口(从会话切到某一页)、切换器(页与页之间)和出口(回到会话、关掉某一页))。
 */
interface MobileTabItem {
  id: string
  title: string
  kind: string
}

const props = defineProps<{
  open: boolean
  /** 当前正在显示的页面 id；空字符串表示正停在会话上。 */
  activeId: string
  /** 会话自己的名字，让“回到会话”这一行说得清楚。 */
  sessionTitle: string
  tabs: MobileTabItem[]
}>()

const emit = defineEmits<{
  close: []
  select: [id: string]
  'close-tab': [id: string]
}>()

function iconFor(kind: string) {
  if (kind === 'browser') return Globe
  if (kind === 'page') return SquareTerminal
  return FileText
}
</script>

<style scoped>
.mobile-tabs {
  position: fixed;
  inset: 0;
  /* 手机主界面那一层在 300：抽屉必须压在上面，否则会被会话层盖住。 */
  z-index: 400;
  display: flex;
  align-items: flex-end;
  background: color-mix(in srgb, var(--theme-main-text, #222) 30%, transparent);
}

.mobile-tabs__sheet {
  width: 100%;
  max-height: 70vh;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 12px calc(16px + var(--safe-area-bottom, 0px));
  background: var(--theme-main-background, #fff);
  color: var(--theme-main-text, #222);
  border-radius: 18px 18px 0 0;
  box-shadow: 0 -12px 32px color-mix(in srgb, var(--foreground) 18%, transparent);
}

.mobile-tabs__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 4px 6px;
}

.mobile-tabs__heading {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.mobile-tabs__done {
  border: 0;
  background: none;
  color: var(--theme-main-text, #222);
  font-size: 14px;
  padding: 4px 6px;
}

.mobile-tabs__list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow-y: auto;
}

.mobile-tabs__row {
  display: flex;
  align-items: center;
  gap: 4px;
  border-radius: 12px;
}

.mobile-tabs__row.is-active {
  background: color-mix(in srgb, var(--theme-main-text, #222) 8%, transparent);
}

.mobile-tabs__pick {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 10px;
  border: 0;
  background: none;
  color: inherit;
  font-size: 14px;
  text-align: left;
}

.mobile-tabs__title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mobile-tabs__close {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  margin-right: 4px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 999px;
  background: none;
  color: color-mix(in srgb, var(--theme-main-text, #222) 62%, transparent);
}

.mobile-tabs__empty {
  margin: 4px 6px 8px;
  font-size: 12.5px;
  color: color-mix(in srgb, var(--theme-main-text, #222) 55%, transparent);
}
</style>
