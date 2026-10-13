<template>
  <!-- 子代理活动指示：composer 工具行里、权限/模式芯片右侧的一格。
       永远占住同一格宽度，只在运行时显形——出现/消失都不推动旁边的控件。 -->
  <span
    class="sub-agent-activity"
    :class="{ 'sub-agent-activity--active': active }"
    role="img"
    :aria-label="label"
    :title="label"
    data-sub-agent-activity
  >
    <Bot class="sub-agent-activity-icon" :size="15" :stroke-width="1.8" aria-hidden="true" />
  </span>
</template>

<script setup lang="ts">
import { t } from '../i18n/index'

import { computed } from 'vue'
import { Bot } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  /** 仅当子代理在运行。 */
  active?: boolean
  /** 正在运行的子代理名字（用于无障碍标签）。 */
  names?: string[]
}>(), {
  active: false,
  names: () => [],
})

const label = computed(() => (
  props.names.length ? t("子代理运行中：{0}", { 0: props.names.join('、') }) : t("子代理运行中")
))
</script>

<style scoped>
.sub-agent-activity {
  --text: var(--theme-composer-text);
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 26px;
  color: color-mix(in srgb, var(--text) 78%, transparent);
  /* 隐藏只走 visibility/opacity：盒子始终占位，旁边的控件不会被推动。 */
  visibility: hidden;
  opacity: 0;
}
.sub-agent-activity--active {
  visibility: visible;
  opacity: 1;
}
/* 动画只挂在激活态上：不运行时连 CSS 动画都不存在，后台没有持续的逐帧工作。 */
.sub-agent-activity--active .sub-agent-activity-icon {
  animation: sub-agent-activity-breathe 2.6s ease-in-out infinite;
}
/* 一次长而柔的呼吸（不是硬闪）：明暗与极小的缩放一起往返。 */
@keyframes sub-agent-activity-breathe {
  0%, 100% { opacity: .5; transform: scale(.94); }
  50% { opacity: 1; transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .sub-agent-activity-icon { animation: none; opacity: .85; }
}
</style>
