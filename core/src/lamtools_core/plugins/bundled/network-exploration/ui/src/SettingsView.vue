<script setup>
// user:“代理和高级网络设置置于设置页，不新增大量平级入口”+(加速、代理、DNS、连接、防护、定时检查都在设置页里切换，不再各占一个左栏位置)。
import { computed } from "vue";
import {
  Zap,
  Globe,
  Settings2,
  ArrowLeftRight,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-vue-next";
import DashboardView from "./DashboardView.vue";
import ProxyView from "./ProxyView.vue";
import NetworkSettings from "./NetworkSettings.vue";
import ConnectionsView from "./ConnectionsView.vue";
import SecurityView from "./SecurityView.vue";
import AdvancedView from "./AdvancedView.vue";
const props = defineProps({
  session: Object,
  section: { type: String, default: "acceleration" },
  sections: { type: Array, default: () => [] },
});
const emit = defineEmits(["navigate", "diagnostic", "section"]);
const icons = {
  acceleration: Zap,
  proxy: Globe,
  network: Settings2,
  connections: ArrowLeftRight,
  security: ShieldCheck,
  advanced: SlidersHorizontal,
};
const views = {
  acceleration: DashboardView,
  proxy: ProxyView,
  network: NetworkSettings,
  connections: ConnectionsView,
  security: SecurityView,
  advanced: AdvancedView,
};
const tabs = computed(() =>
  (props.sections || []).map((row) => ({
    ...row,
    icon: icons[row.id] || Settings2,
  })),
);
const currentId = computed(() =>
  views[props.section] ? props.section : "acceleration",
);
const view = computed(() => views[currentId.value]);
</script>
<template>
  <div class="nx2-page nx2-settings" data-settings-page>
    <nav class="nx2-settings-tabs" aria-label="设置分区">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="nx2-settings-tab"
        :class="{ 'is-active': currentId === tab.id }"
        :data-settings-section="tab.id"
        :aria-current="currentId === tab.id ? 'page' : undefined"
        @click="emit('section', tab.id)"
      >
        <component :is="tab.icon" :size="16" :stroke-width="1.7" /><span>{{
          tab.title
        }}</span>
      </button>
    </nav>
    <section class="nx2-settings-body">
      <component
        :is="view"
        :key="currentId"
        :session="session"
        @navigate="emit('navigate', $event)"
        @diagnostic="emit('diagnostic', $event)"
      />
    </section>
  </div>
</template>
