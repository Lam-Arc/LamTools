<script setup>
// user:“右侧栏…直接把该要的那 3 个胶囊镶上去…1. 加速：一个开启键。2. 代理：一个点击更换节点，和一个开启键。3. 下载：一个 URL 输入框，和一个下载键”“能用图标表示的地方就不用写文字”+(去掉内嵌卡片，只放三行胶囊；操作控件直接放在胶囊里)。
import { computed, ref } from "vue";
import {
  Zap,
  Globe,
  Download,
  Power,
  ChevronsUpDown,
  ArrowDownToLine,
} from "lucide-vue-next";
import { useNetwork } from "./session.mjs";
const props = defineProps({ context: Object });
const context = Object.create(props.context);
context.compact = true;
const s = useNetwork(context);
const url = ref("");
const saved = computed(() => Boolean(s.state?.proxy?.config_saved));
const proxyRunning = computed(() => Boolean(s.state?.proxy?.running));
const groups = computed(() =>
  Object.entries(s.proxy?.proxies || {}).filter(
    ([name, node]) =>
      name !== "GLOBAL" && Array.isArray(node.all) && node.type === "Selector",
  ),
);
const group = computed(() => groups.value[0] || null);
const nodes = computed(() => group.value?.[1]?.all || []);
const currentNode = computed(() => group.value?.[1]?.now || "");
const accelerationText = computed(() =>
  !s.systemProxyReady ? "读取中" : s.accelerated ? "已开启" : "未开启",
);
function open(page) {
  try {
    sessionStorage.setItem("network-exploration:page", page);
  } catch {
    // 没有 sessionStorage 时仍然可以打开插件页。
  }
  window.dispatchEvent(
    new CustomEvent("sunday:open-plugin-page", {
      detail: { plugin: "network-exploration", id: "network" },
    }),
  );
  window.dispatchEvent(
    new CustomEvent("sunday:network-plugin-page", { detail: { page } }),
  );
}
function toggleProxy() {
  if (!saved.value) {
    open("proxy");
    return;
  }
  s.toggleProxy();
}
async function chooseNode(event) {
  const name = event.target.value;
  if (!name || !group.value || name === currentNode.value) return;
  await s.selectNode(group.value[0], name);
}
async function startDownload() {
  const link = url.value.trim();
  // user:“修”+(快捷入口只提交链接，文件名、默认参数与线路由后台决定)。
  const result = await s.run("transfer.add", { url: link }, "已开始下载");
  if (!result) return;
  url.value = "";
  await s.loadTasks();
}
</script>
<template>
  <section class="nx-app nx-quick-app" aria-label="网络快捷操作">
    <div class="nx-pill-list">
      <div
        class="nx-quick-pill"
        :class="{ 'is-on': s.accelerated }"
        data-quick="acceleration"
      >
        <span class="nx-pill-icon" title="加速"><Zap :size="16" /></span>
        <span class="nx-pill-value" :class="{ 'is-live': s.accelerated }">{{
          accelerationText
        }}</span>
        <button
          class="nx-mini-action"
          :class="{ 'is-on': s.accelerated }"
          :aria-pressed="s.accelerated"
          :aria-label="s.accelerated ? '关闭加速' : '开启加速'"
          :title="s.accelerated ? '关闭加速' : '开启加速'"
          :disabled="Boolean(s.busy) || !s.state || !s.systemProxyReady"
          data-quick-action="acceleration"
          @click="s.toggleAcceleration()"
        >
          <Power :size="14" />
        </button>
      </div>

      <div
        class="nx-quick-pill"
        :class="{ 'is-on': proxyRunning }"
        data-quick="proxy"
      >
        <span class="nx-pill-icon" title="代理"><Globe :size="16" /></span>
        <div class="nx-node-wrap">
          <select
            class="nx-node-select"
            :value="currentNode"
            :disabled="Boolean(s.busy) || !nodes.length"
            aria-label="更换节点"
            title="更换节点"
            @change="chooseNode"
          >
            <option v-if="!nodes.length" value="">无可用节点</option>
            <option v-for="name in nodes" :key="name" :value="name">
              {{ name === "DIRECT" ? "直接连接" : name }}
            </option>
          </select>
          <ChevronsUpDown :size="12" class="nx-chevron" />
        </div>
        <button
          class="nx-mini-action"
          :class="{ 'is-on': proxyRunning }"
          :aria-pressed="proxyRunning"
          :aria-label="proxyRunning ? '关闭代理' : '开启代理'"
          :title="proxyRunning ? '关闭代理' : '开启代理'"
          :disabled="Boolean(s.busy) || !s.state"
          data-quick-action="proxy"
          @click="toggleProxy"
        >
          <Power :size="14" />
        </button>
      </div>

      <div class="nx-quick-pill" data-quick="download">
        <span class="nx-pill-icon" title="下载"><Download :size="16" /></span>
        <form class="nx-download-form" @submit.prevent="startDownload">
          <input
            v-model="url"
            type="url"
            aria-label="下载链接"
            placeholder="URL"
            required
          />
          <button
            class="nx-mini-action"
            :class="{ 'is-ready': url.trim() }"
            :disabled="Boolean(s.busy) || !url.trim()"
            aria-label="开始下载"
            title="开始下载"
          >
            <ArrowDownToLine :size="14" />
          </button>
        </form>
      </div>
    </div>
    <p v-if="s.error || s.connectionError" class="nx-quick-error" role="alert">
      {{ s.error || "暂时无法连接网络服务" }}
    </p>
    <p v-else-if="s.notice" class="nx-quick-note" role="status">
      {{ s.notice }}
    </p>
  </section>
</template>
