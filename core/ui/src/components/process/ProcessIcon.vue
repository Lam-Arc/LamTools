<template>
  <span
    class="process-icon"
    :class="stateClass"
    :data-process-icon-kind="kind"
    :style="{ width: `${size}px`, height: `${size}px` }"
  >
    <!-- user:“所有内置及系统级能力必须映射至语义明确的专属图标”+(过程行的图标由语义类别决定，
         状态只做叠加，不再让扳手之类的通用图标混进过程行。) -->
    <component
      :is="icon"
      class="process-icon__glyph"
      :size="size"
      :stroke-width="stroke"
      aria-hidden="true"
    />
    <!-- user:“执行中图标带微弱呼吸脉冲或外圈细环旋转；完成转静态；失败着色警戒红并角标提示”
         +(运行态靠外圈细环旋转表达，完成态静态降透明度，失败态染色并加右下角标点。) -->
  </span>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import {
  processIconComponent,
  processIconStroke,
  resolveProcessIconKind,
  type ProcessIconInput,
  type ProcessIconKind,
} from '@/helpers/processIcons.ts'

const props = withDefaults(defineProps<{
  kind?: ProcessIconKind
  partType?: string
  toolName?: string
  label?: string
  args?: unknown
  result?: unknown
  status?: 'running' | 'completed' | 'failed' | 'pending' | 'error'
  size?: number
  strokeWidth?: number
}>(), {
  kind: undefined,
  partType: '',
  toolName: '',
  label: '',
  args: undefined,
  result: undefined,
  status: 'completed',
  size: 16,
  strokeWidth: undefined,
})

const input = computed<ProcessIconInput>(() => ({
  partType: props.partType,
  toolName: props.toolName,
  label: props.label,
  args: props.args,
  result: props.result,
}))

// 外部显式给了 kind 就用它，否则按 partType / 工具名 / 文件后缀自行解析。
const kind = computed<ProcessIconKind>(() => props.kind ?? resolveProcessIconKind(input.value))
const icon = computed(() => processIconComponent(kind.value, input.value))
const stroke = computed(() => props.strokeWidth ?? processIconStroke(kind.value))
const isFailed = computed(() => props.status === 'failed' || props.status === 'error')
const stateClass = computed(() => `process-icon--${props.status || 'completed'}`)
</script>
<script lang="ts">
import { defineComponent, h } from 'vue'
import { ChevronRight } from 'lucide-vue-next'

/**
 * user:“加一个折叠态展开指示箭头的导出，供主代理统一用”+(过程行的图标和展开箭头同源，
 * 主代理一处 import 就能同时拿到两者，不必每个页面自己拼旋转样式和动效降级。)
 *
 * 具名导出：`import ProcessIcon, { ProcessChevron } from '@/components/process/ProcessIcon.vue'`
 */
export const ProcessChevron = defineComponent({
  name: 'ProcessChevron',
  props: {
    expanded: { type: Boolean, default: false },
    size: { type: Number, default: 16 },
  },
  setup(props) {
    return () => h(ChevronRight, {
      class: { 'process-chevron': true, 'is-expanded': props.expanded },
      size: props.size,
      'stroke-width': 1.6,
      'aria-hidden': 'true',
    })
  },
})
</script>
<style scoped>
/* user:“过程行的那个思考怎么又变成紫色了？”+(语义图标跟随所在行的文字色，不再套
   「过程图标专用色」——那个字段是给非语义的状态图标用的，套上来整排图标会变紫。
   运行态用正文色、失败态用警戒红，颜色不写死 hex。) */
.process-icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: currentColor;
  transition: color var(--dur-base) var(--ease-out), opacity var(--dur-base) var(--ease-out);
}

.process-icon__glyph {
  display: block;
}

.process-icon--running {
  color: var(--theme-main-text);
}

.process-icon--pending {
  opacity: .55;
}

.process-icon--completed {
  opacity: .72;
}

.process-icon--failed,
.process-icon--error {
  color: var(--red);
  opacity: 1;
}

/* 外圈细环：只描上边，转起来像一段弧，不抢图标的视线。 */
/* user:“我不是说错误标红吗？…就是仅仅简简单单地标红就行了”+(失败只把图标与摘要
   标红，不再额外挂右下角小点。) */
</style>
<style>
/* ProcessChevron 是同文件的具名导出组件，拿不到本 SFC 的 scoped 作用域标记，
   所以它的规则放在独立的非 scoped 块里，用 .process-chevron 前缀限定，不污染其它元素。 */
/* user:“transition: transform 160ms ease-out; .is-expanded { transform: rotate(90deg) }”+(折叠箭头
   展开时右转 90°，颜色跟随文字色)。 */
.process-chevron {
  color: currentColor;
  flex: 0 0 auto;
  transition: transform 160ms ease-out;
}

.process-chevron.is-expanded {
  transform: rotate(90deg);
}

@media (prefers-reduced-motion: reduce) {
  .process-chevron {
    transition: none;
  }
}
</style>
