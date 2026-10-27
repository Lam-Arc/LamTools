<script setup>
import { Route, Globe, ArrowRight } from "lucide-vue-next";
defineProps({ session: Object });
const modes = [
  { value: "rule", label: "智能分流", help: "按已有规则选择线路", icon: Route },
  {
    value: "global",
    label: "全部走代理",
    help: "所有代理请求使用选中线路",
    icon: Globe,
  },
  {
    value: "direct",
    label: "直接连接",
    help: "不经过代理节点",
    icon: ArrowRight,
  },
];
</script>
<template>
  <section class="nx-panel nx-modes">
    <div class="nx-panel-heading">
      <h2><Route :size="17" />连接方式</h2>
    </div>
    <div class="nx-mode-options" role="radiogroup" aria-label="连接方式">
      <button
        v-for="mode in modes"
        :key="mode.value"
        class="nx-mode"
        role="radio"
        :aria-checked="session.proxy?.mode === mode.value"
        :disabled="!session.state?.proxy?.running || Boolean(session.busy)"
        @click="session.setMode(mode.value)"
      >
        <component :is="mode.icon" :size="17" /><span
          ><strong>{{ mode.label }}</strong
          ><small>{{ mode.help }}</small></span
        ><span class="nx-mode-dot" />
      </button>
    </div>
    <p v-if="!session.state?.proxy?.running" class="nx-help">
      开启代理后可以调整连接方式。
    </p>
  </section>
</template>
