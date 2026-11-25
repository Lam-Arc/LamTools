<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“常用功能放在首页 切梯子/网络加速”+(首页直接选择真实节点，不要求填写代理组或节点参数)。
import { computed, ref, watch } from "vue";
import { Check, Radio, Plus, RefreshCw, Zap } from "lucide-vue-next";
const props = defineProps({ session: Object, compact: Boolean });
defineEmits(["import"]);
const chosenGroup = ref(""),
  filter = ref(""),
  delays = ref({});
const groups = computed(() => {
  const choices = Object.entries(props.session.proxy?.proxies || {}).filter(
    ([, node]) => Array.isArray(node.all) && node.type === "Selector",
  );
  const globalFirst = props.session.proxy?.mode === "global";
  return choices.sort(
    ([a], [b]) =>
      Number(b === "GLOBAL") * (globalFirst ? 1 : -1) -
      Number(a === "GLOBAL") * (globalFirst ? 1 : -1),
  );
});
watch(
  groups,
  (list) => {
    if (!list.some(([name]) => name === chosenGroup.value))
      chosenGroup.value = list[0]?.[0] || "";
  },
  { immediate: true },
);
const group = computed(
  () => groups.value.find(([name]) => name === chosenGroup.value)?.[1],
);
const nodes = computed(() =>
  (group.value?.all || []).filter((name) =>
    name.toLowerCase().includes(filter.value.toLowerCase()),
  ),
);
// user:“你需要确保插件内节点正确出现，延迟正常显示，可切换”+(可选分组里放的常常是子分组，子分组自身没有 history，延迟要顺着它当前出口节点取，否则整列都显示未测速)。
function resolveDelay(name, depth = 0) {
  const node = props.session.proxy?.proxies?.[name];
  if (!node) return 0;
  const own = Number(node.history?.at(-1)?.delay);
  if (own > 0) return own;
  const child = node.now;
  if (depth >= 4 || !child || child === name) return 0;
  return resolveDelay(child, depth + 1);
}
function delayValue(name) {
  const value = delays.value[name] ?? resolveDelay(name);
  return Number(value) > 0 ? Number(value) : 0;
}
function latency(name) {
  const value = delayValue(name);
  return value > 0 ? `${value} ms` : "未测速";
}
// user:“你需要确保插件内节点正确出现”+(分组行要标出它当前真正走的节点，用户才知道选中的这行背后是谁)。
function currentExit(name) {
  const node = props.session.proxy?.proxies?.[name];
  if (!node || !Array.isArray(node.all)) return "";
  const now = node.now;
  return now && now !== name ? now : "";
}
function quality(name) {
  const value = delayValue(name);
  if (!value) return 8;
  return Math.max(8, Math.round(100 - Math.min(100, value / 3)));
}
function tone(name) {
  const value = delayValue(name);
  if (!value) return "is-unknown";
  if (value <= 90) return "is-fast";
  if (value <= 200) return "is-mid";
  return "is-slow";
}
async function testNode(name) {
  const result = await props.session.run("proxy.delay", { name });
  if (result?.delay != null) delays.value[name] = result.delay;
}
async function optimize() {
  const result = await props.session.optimizeNode(chosenGroup.value);
  if (!result) return;
  for (const row of result.candidates || [])
    if (Number(row.delay) > 0) delays.value[row.name] = row.delay;
}
</script>
<template>
  <section class="nx2-group nx-nodes">
    <header class="nx2-group-head">
      <h2>线路</h2>
      <span class="nx2-row-hint">{{ nodes.length }} 条</span>
      <button class="nx2-btn" data-optimize :disabled="Boolean(session.busy) || !nodes.length" @click="optimize">
        <Zap :size="13" />{{ session.busy === "proxy.optimize" ? "测速中…" : "选择最快" }}
      </button>
    </header>

    <div v-if="groups.length > 1" class="nx-filter-tabs" role="group" aria-label="线路分组">
      <button v-for="[name] in groups" :key="name" :class="{ active: chosenGroup === name }" :aria-pressed="chosenGroup === name" @click="chosenGroup = name">{{ name }}</button>
    </div>
    <input v-if="nodes.length > 8" v-model="filter" class="nx2-input" placeholder="搜索线路" aria-label="搜索线路" />

    <div class="nx2-rows">
      <div v-for="name in nodes" :key="name" class="nx2-row nx2-row--node">
        <button class="nx2-node-choice" :data-node="name" :aria-pressed="group.now === name" :disabled="Boolean(session.busy)" @click="session.selectNode(chosenGroup, name)">
          <span class="nx2-node-check"><Check v-if="group.now === name" :size="12" :stroke-width="2.4" /></span>
          <span class="nx2-node-name">{{ name === "DIRECT" ? "直接连接" : name === "REJECT" ? "阻止连接" : name }}</span>
          <span v-if="currentExit(name)" class="nx2-row-hint nx2-ellipsis">{{ currentExit(name) }}</span>
          <span class="nx2-node-meter"><i :class="tone(name)" :style="{ width: `${quality(name)}%` }" /></span>
          <span class="nx2-node-ms">{{ latency(name) }}</span>
        </button>
        <button v-if="!compact" class="nx2-icon" :disabled="Boolean(session.busy)" :aria-label="`测试 ${name} 的延迟`" @click="testNode(name)">
          <RefreshCw :size="13" />
        </button>
      </div>
      <p v-if="!nodes.length" class="nx2-empty-line">开启代理后加载线路。</p>
    </div>
  </section>
</template>
