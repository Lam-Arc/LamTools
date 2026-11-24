<template>
  <header class="mobile-chat-header" data-mobile-chat-header>
    <!-- user:“左侧返回会话列表，中间会话名称与设备状态，右侧更多菜单”+
         (L2 顶部栏独立成条：返回在左、标题居中、··· 在右，消息区在它下面滚动)。 -->
    <button
      type="button"
      class="mobile-chat-header__button"
      :aria-label="t('返回会话列表')"
      data-mobile-chat-back
      @click="emit('back')"
    >
      <ChevronLeft :size="22" :stroke-width="2" aria-hidden="true" />
    </button>

    <div class="mobile-chat-header__body">
      <!-- user:“进来页之后要能切、能返回”+(停在某个页面上时，标题写这一页的名字；
           左侧返回键由宿主解释成“先回会话”，再按一次才回列表)。 -->
      <span class="mobile-chat-header__title" data-mobile-chat-header-title>{{ props.pageTitle || props.title || t('新会话') }}</span>
      <span class="mobile-chat-header__sub" data-mobile-chat-header-device :data-device-state="props.deviceState">
        <span class="mobile-chat-header__dot" aria-hidden="true"></span>
        <span v-if="props.pageTitle" class="mobile-chat-header__project">{{ props.title || t('会话') }}</span>
        <span v-if="props.pageTitle" class="mobile-chat-header__sep" aria-hidden="true">·</span>
        <span v-else-if="props.projectName" class="mobile-chat-header__project">{{ props.projectName }}</span>
        <span v-if="!props.pageTitle && props.projectName" class="mobile-chat-header__sep" aria-hidden="true">·</span>
        <span>{{ props.deviceLabel }}</span>
      </span>
    </div>

    <!-- user:“会话内右上角有没有标签页抽屉？”+(手机端标签即页面：这枚入口列出全部页面，
         点哪一项就切到哪一页；没有任何页面时不占位置)。 -->
    <button
      v-if="(props.tabsCount ?? 0) > 0"
      type="button"
      class="mobile-chat-header__button mobile-chat-header__button--tabs"
      :aria-label="t('标签页')"
      aria-haspopup="dialog"
      data-mobile-chat-tabs
      @click="emit('tabs', $event)"
    >
      <Layers :size="20" :stroke-width="1.9" aria-hidden="true" />
      <span class="mobile-chat-header__badge" data-mobile-chat-tabs-count>{{ props.tabsCount }}</span>
    </button>

    <button
      type="button"
      class="mobile-chat-header__button"
      :aria-label="t('会话操作')"
      aria-haspopup="menu"
      data-mobile-chat-more
      @click="emit('more', $event)"
    >
      <MoreHorizontal :size="22" :stroke-width="2" aria-hidden="true" />
    </button>
  </header>
</template>

<script setup lang="ts">
import { ChevronLeft, MoreHorizontal } from 'lucide-vue-next'
import { t } from '@/i18n/index.ts'

/**
 * user:“顶部栏：左侧返回会话列表，中间会话名称，次级文字显示 Agent / 设备状态，
 * 右侧 `···` 更多菜单”+(手机 L2 顶部栏：设备状态必须一眼能认出来是在本机还是电脑上跑；
 * 栏位独立，不压在消息上，也不随消息滚走)。
 */
const props = defineProps<{
  title?: string
  /** 当前页面名；非空表示“正停在一个标签页上”，返回键先回会话。 */
  pageTitle?: string
  /** 抽屉里可切换的页面数（不含会话本身）；为 0 时不显示入口。 */
  tabsCount?: number
  /** 当前会话所属项目，作为次级文字的前半段。 */
  projectName?: string
  /** 设备状态文案：本机 Android / 电脑 · 已连接 / 电脑离线。 */
  deviceLabel: string
  /** local / remote / offline：决定状态点颜色。 */
  deviceState?: 'local' | 'remote' | 'offline'
}>()

const emit = defineEmits<{
  back: []
  more: [event: Event]
  tabs: [event: Event]
}>()
</script>

<style scoped>
.mobile-chat-header {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 0 0 auto;
  /* 和消息区一样吃掉主区左右内边距：分割线通到屏幕两边，按钮仍留一点内缩。
     宽度交给 flex 交叉轴拉伸（width:auto），负外边距把两侧补到屏幕边缘；
     不要在 width:100% 上再加内边距，否则整条比屏幕宽、右边按钮被裁。 */
  margin-inline: calc(-1 * var(--main-x-padding));
  min-height: calc(52px + var(--native-safe-area-top, 0px));
  padding: var(--native-safe-area-top, 0px) calc(var(--main-x-padding) - var(--space-2)) 0;
  border-bottom: 1px solid color-mix(in srgb, var(--theme-main-text) 8%, transparent);
  /* 透明让主界面的主题背景（含图片/玻璃）继续铺到状态栏后面，不另复制一层。 */
  background: transparent;
  color: var(--theme-main-text);
}

.mobile-chat-header__button {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 44px;
  height: 44px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mobile-chat-header__button:active {
  background: color-mix(in srgb, var(--theme-main-text) var(--alpha-hover), transparent);
}

.mobile-chat-header__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-width: 0;
  padding: 0 var(--space-1);
}

.mobile-chat-header__title {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.25;
}

.mobile-chat-header__sub {
  display: flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  color: color-mix(in srgb, var(--theme-main-text) 52%, transparent);
  font-size: 11px;
  line-height: 1.2;
}

.mobile-chat-header__dot {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--green);
}

.mobile-chat-header__sub[data-device-state='offline'] .mobile-chat-header__dot {
  background: var(--red);
}

.mobile-chat-header__project {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 34vw;
}

.mobile-chat-header__sep {
  color: color-mix(in srgb, var(--theme-main-text) 28%, transparent);
}

/* 标签抽屉入口：图标右下角一枚小计数，告诉用户“还有几页在抽屉里”。 */
.mobile-chat-header__button--tabs {
  position: relative;
}

.mobile-chat-header__badge {
  position: absolute;
  top: 1px;
  right: 0;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 999px;
  background: var(--theme-main-text);
  color: var(--theme-main-background, var(--background));
  font-size: 9.5px;
  line-height: 14px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
</style>
