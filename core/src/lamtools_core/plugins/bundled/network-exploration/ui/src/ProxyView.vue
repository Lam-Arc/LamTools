<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络工具复用应用开关，保留原有操作与禁用条件)。
import SundaySwitch from "../../../../../../../ui/src/components/SundaySwitch.vue";
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
// user:“代理的功能挺简单的，就是：1 订阅分组 2 节点分组 3 节点测速 4 选择节点”+(代理页只保留这四件事)。
import { computed, ref } from "vue";
import { Link, Power } from "lucide-vue-next";
import NodePicker from "./NodePicker.vue";
import { dateLabel } from "./session.mjs";
import ImportProfile from "./ImportProfile.vue";
const props = defineProps({ session: Object });
const importing = ref(false);
const switching = ref(false);
const saved = computed(() => Boolean(props.session.state?.proxy?.config_saved));
const modeOptions = [
  { value: 'rule', label: '规则模式' },
  { value: 'global', label: '全局代理' },
  { value: 'direct', label: '全部直连' },
];
const running = computed(() => Boolean(props.session.state?.proxy?.running));
// user:“怎么切换订阅”+(记住导入过的订阅来源，随时切回去；列表只显示主机，不显示带令牌的原始链接)。
const subscriptions = computed(() => props.session.state?.subscriptions || []);
const activeSubscription = computed(
  () => subscriptions.value.find((row) => row.active) || null,
);
async function activateSubscription(row) {
  const result = await props.session.run(
    "proxy.subscriptions",
    { action: "activate", id: row.id },
    `已切换到 ${row.host}`,
  );
  if (result) {
    switching.value = false;
    await props.session.loadProxy();
  }
}
async function removeSubscription(row) {
  await props.session.run(
    "proxy.subscriptions",
    { action: "remove", id: row.id },
    "已删除这条订阅记录",
  );
}
</script>
<template>
  <div class="nx2-page">
    <!-- 订阅：当前用的是哪一条，一眼看到；更换与切换都在这一行。 -->
    <section class="nx2-station" data-proxy-subscription>
      <div class="nx2-station-top">
        <span class="nx2-station-icon"><Link :size="18" :stroke-width="1.8" /></span>
        <span class="nx2-station-title">订阅
          <small v-if="activeSubscription" class="nx2-row-hint" data-active-subscription>{{ activeSubscription.host }}</small>
          <small v-else-if="saved" class="nx2-row-hint">本地导入的配置</small>
          <small v-else class="nx2-row-hint">还没有订阅</small>
        </span>
        <button class="nx2-btn" :class="{ 'nx2-btn--primary': !saved }" @click="importing = !importing">
          {{ saved ? "更新订阅" : "添加订阅" }}
        </button>
        <button v-if="subscriptions.length" class="nx2-btn nx2-btn--ghost" data-toggle-subscriptions :aria-expanded="switching" @click="switching = !switching">
          切换（{{ subscriptions.length }}）
        </button>
      </div>
      <div v-if="switching && subscriptions.length" class="nx2-rows" data-subscription-list>
        <div v-for="row in subscriptions" :key="row.id" class="nx2-row nx2-row--cols" :data-subscription="row.id">
          <span class="nx2-row-value">{{ row.host }}</span>
          <span class="nx2-row-hint">{{ dateLabel(row.saved_at) }}</span>
          <span v-if="row.active" class="nx2-tag is-ok">当前</span>
          <button v-else class="nx2-link" :disabled="Boolean(session.busy)" @click="activateSubscription(row)">切换</button>
          <button class="nx2-link nx2-bad" :disabled="Boolean(session.busy)" @click="removeSubscription(row)">删除</button>
        </div>
      </div>
      <ImportProfile v-if="importing" :session="session" @close="importing = false" />
    </section>

    <!-- 连接：开关就是答案；开了才显示模式。 -->
    <section class="nx2-station" data-proxy-connection>
      <div class="nx2-station-top">
        <span class="nx2-station-icon" :class="{ 'is-on': running }"><Power :size="18" :stroke-width="1.8" /></span>
        <span class="nx2-station-title">连接
          <small class="nx2-row-hint">{{ running ? "已连接" : saved ? "未连接" : "先添加订阅" }}</small>
        </span>
        <SundaySwitch
          data-proxy-switch
          label="代理连接"
          :model-value="running"
          :disabled="Boolean(session.busy) || !saved"
          @update:model-value="session.toggleProxy()"
        />
      </div>
      <div v-if="saved" class="nx2-row nx2-row--cols">
        <span class="nx2-row-label">模式</span>
        <UiSelect
          :model-value="session.proxy?.mode || 'rule'"
          :options="modeOptions"
          :disabled="Boolean(session.busy) || !running"
          aria-label="代理模式"
          data-proxy-mode
          :menu-min-width="150"
          @update:model-value="session.setMode($event)"
        />
        <span class="nx2-row-hint">规则只让匹配的站点走代理；全局全部走代理。</span>
      </div>
    </section>

    <NodePicker :session="session" @import="importing = true" />
  </div>
</template>
