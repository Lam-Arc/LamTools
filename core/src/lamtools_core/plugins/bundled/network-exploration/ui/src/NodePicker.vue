<script setup>
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
function latency(name) {
  const value =
    delays.value[name] ??
    props.session.proxy?.proxies?.[name]?.history?.at(-1)?.delay;
  return Number(value) > 0 ? `${value} ms` : "未测速";
}
function delayValue(name) {
  const value =
    delays.value[name] ??
    props.session.proxy?.proxies?.[name]?.history?.at(-1)?.delay;
  return Number(value) > 0 ? Number(value) : 0;
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
  <section class="nx-panel nx-nodes">
    <div class="nx-panel-heading">
      <div>
        <span class="nx-kicker">03 / 线路与测速</span>
        <h2><Radio :size="17" />选择线路</h2>
      </div>
      <div class="nx-node-head-actions">
        <button
          class="nx-button nx-quiet nx-icon-button"
          aria-label="刷新线路"
          :disabled="Boolean(session.busy)"
          @click="session.loadProxy()"
        >
          <RefreshCw :size="15" />
        </button>
        <button
          class="nx-button nx-secondary nx-optimize"
          data-optimize
          :disabled="Boolean(session.busy) || !nodes.length"
          @click="optimize"
        >
          <Zap :size="13" />{{
            session.busy === "proxy.optimize" ? "测速中…" : "选择最快"
          }}
        </button>
      </div>
    </div>
    <p class="nx-help">点一行直接切换；右侧刷新键单独测速。</p>
    <template v-if="groups.length">
      <div class="nx-line-groups" role="group" aria-label="线路分组">
        <button
          v-for="[name] in groups"
          :key="name"
          class="nx-line-group"
          :class="{ 'is-active': chosenGroup === name }"
          :aria-pressed="chosenGroup === name"
          @click="chosenGroup = name"
        >
          {{ name }}
          <span>{{ groups.length > 1 ? "" : "" }}</span>
        </button>
        <span class="nx-subtle">{{ nodes.length }} 条</span>
      </div>
      <input
        v-if="nodes.length > 8"
        v-model="filter"
        class="nx-input nx-node-search"
        placeholder="搜索线路"
        aria-label="搜索线路"
      />
      <div class="nx-line-list" :class="{ 'nx-node-list--compact': compact }">
        <div
          v-for="name in nodes"
          :key="name"
          class="nx-line-row"
          :class="{ 'is-selected': group.now === name }"
        >
          <button
            class="nx-line-choice"
            :data-node="name"
            :aria-pressed="group.now === name"
            :disabled="Boolean(session.busy)"
            @click="session.selectNode(chosenGroup, name)"
          >
            <span class="nx-line-radio"
              ><Check v-if="group.now === name" :size="11" /></span
            >
            <span class="nx-line-name">{{
              name === "DIRECT"
                ? "直接连接"
                : name === "REJECT"
                  ? "阻止连接"
                  : name
            }}</span>
            <span class="nx-line-meter" :class="tone(name)"
              ><i :style="{ width: `${quality(name)}%` }"
            /></span>
            <span class="nx-line-ms">{{ latency(name) }}</span>
          </button>
          <button
            v-if="!compact"
            class="nx-button nx-quiet nx-icon-button nx-line-refresh"
            :disabled="Boolean(session.busy)"
            :aria-label="`测试 ${name} 的延迟`"
            @click="testNode(name)"
          >
            <RefreshCw :size="13" />
          </button>
        </div>
      </div>
      <button
        class="nx-button nx-quiet nx-add-profile"
        @click="$emit('import')"
      >
        <Plus :size="14" />添加或更新订阅
      </button>
    </template>
    <div v-else class="nx-empty nx-empty--small">
      <Radio :size="24" /><strong>{{
        session.state?.proxy?.running
          ? "尚未找到可选线路"
          : "开启代理后可切换线路"
      }}</strong>
      <p>添加订阅，使用你已有的代理节点。</p>
      <button class="nx-button nx-secondary" @click="$emit('import')">
        <Plus :size="14" />添加订阅
      </button>
    </div>
  </section>
</template>
