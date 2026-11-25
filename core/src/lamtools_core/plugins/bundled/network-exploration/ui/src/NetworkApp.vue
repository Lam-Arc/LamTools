<script setup>
// user:“你应当设计的是一个高级、简洁、现代的网络工具界面”+(独立、克制的网络控制台：数据行优先，不做卡片堆)。
// user:“设置里面什么叫留空以保持默认目录？目录这种属于是必要信息吧 为什么要藏起来”+(凡是有默认值的地方都直接写出来)。
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  Gauge,
  Network,
  Home,
  Download,
  Activity,
  Settings2,
  RefreshCw,
  X,
} from "lucide-vue-next";
import { useNetwork, bytes } from "./session.mjs";
import HomeView from "./HomeView.vue";
import TransferView from "./TransferView.vue";
import InterconnectView from "./InterconnectView.vue";
import DiagnoseView from "./DiagnoseView.vue";
import SettingsView from "./SettingsView.vue";
const props = defineProps({ context: { type: Object, required: true } });
const s = useNetwork(props.context),
  report = ref(null);
const items = [
  { id: "overview", title: "概览", icon: Home, component: HomeView },
  { id: "transfer", title: "下载", icon: Download, component: TransferView },
  { id: "devices", title: "互联", icon: Network, component: InterconnectView },
  { id: "diagnose", title: "诊断", icon: Activity, component: DiagnoseView },
];
const settingsItem = { id: "settings", title: "设置", icon: Settings2, component: SettingsView };
const navItems = items;
const SECTIONS = [
  { id: "acceleration", title: "加速" },
  { id: "proxy", title: "代理与线路" },
  { id: "network", title: "网络与 DNS" },
  { id: "connections", title: "连接" },
  { id: "security", title: "防护" },
  { id: "advanced", title: "高级与记录" },
];
const PAGE_STORAGE = "easynet:page";
const section = ref("acceleration");
const SECTION_ALIASES = {
  proxy: "proxy",
  acceleration: "acceleration",
  network: "network",
  connections: "connections",
  traffic: "connections",
  security: "security",
  advanced: "advanced",
  settings: "acceleration",
};
function requestedPage() {
  try {
    const value = sessionStorage.getItem(PAGE_STORAGE);
    sessionStorage.removeItem(PAGE_STORAGE);
    if (!value) return "overview";
    if (value === "home") return "overview";
    if (SECTION_ALIASES[value]) {
      section.value = SECTION_ALIASES[value];
      return "settings";
    }
    return items.some((item) => item.id === value) ? value : "overview";
  } catch {
    return "overview";
  }
}
const page = ref(requestedPage());
function target(id) {
  if (items.some((item) => item.id === id)) return { page: id };
  if (id === "home") return { page: "overview" };
  if (SECTION_ALIASES[id]) return { page: "settings", section: SECTION_ALIASES[id] };
  return { page: "overview" };
}
function show(id) {
  const next = target(id);
  page.value = next.page;
  if (next.section) section.value = next.section;
  s.notice = "";
  s.error = "";
}
function openSettings(id) {
  page.value = "settings";
  if (id) section.value = SECTION_ALIASES[id] || id;
}
function quickPage(event) {
  const id = event.detail?.page;
  if (typeof id === "string" && id) show(id);
}
const current = computed(() =>
  page.value === "settings" ? settingsItem : items.find((item) => item.id === page.value) || items[0],
);
function diagnostic(value) {
  report.value = value;
  page.value = "diagnose";
}
// user:“实时速率和累计流量必须区分”+(顶栏只放会变的三个数，累计与口径留在概览里说明)。
const liveDown = computed(() => Number(s.state?.traffic?.download || 0));
const liveUp = computed(() => Number(s.state?.traffic?.upload || 0));
const liveDelay = computed(() => {
  const node = s.proxy?.proxies?.[s.proxy?.proxies?.Auto?.now] || null;
  return Number(node?.history?.at(-1)?.delay || 0);
});
onMounted(() => window.addEventListener("sunday:network-plugin-page", quickPage));
onBeforeUnmount(() => window.removeEventListener("sunday:network-plugin-page", quickPage));
</script>
<template>
  <div class="nx-app nx2" :aria-busy="Boolean(s.busy)">
    <aside class="nx2-rail">
      <div class="nx2-brand" title="EasyNet"><Gauge :size="19" :stroke-width="1.8" /><span>EasyNet</span></div>
      <nav aria-label="网络工具">
        <button
          v-for="item in navItems"
          :key="item.id"
          class="nx2-rail-item"
          :class="{ 'is-active': page === item.id }"
          :data-page="item.id"
          :aria-current="page === item.id ? 'page' : undefined"
          :title="item.title"
          @click="show(item.id)"
        >
          <component :is="item.icon" :size="18" :stroke-width="1.7" /><span>{{ item.title }}</span>
        </button>
      </nav>
      <button
        class="nx2-rail-item nx2-rail-settings"
        :class="{ 'is-active': page === 'settings' }"
        data-settings
        :aria-current="page === 'settings' ? 'page' : undefined"
        title="设置"
        @click="openSettings()"
      >
        <Settings2 :size="18" :stroke-width="1.7" /><span>设置</span>
      </button>
    </aside>

    <div class="nx2-main">
      <header class="nx2-top">
        <h1>{{ current.title }}</h1>
        <div class="nx2-top-live" aria-label="实时网络数据">
          <span>↓ <b>{{ bytes(liveDown) }}/s</b></span>
          <span>↑ <b>{{ bytes(liveUp) }}/s</b></span>
          <span v-if="liveDelay">线路 <b>{{ liveDelay }} ms</b></span>
          <button
            class="nx2-icon"
            :disabled="Boolean(s.busy)"
            aria-label="刷新网络状态"
            title="刷新"
            @click="s.refresh()"
          >
            <RefreshCw :size="14" />
          </button>
        </div>
      </header>

      <p v-if="s.connectionError" class="nx2-banner nx2-banner--error" role="alert">
        与服务断开，正在重试。<button class="nx2-link" @click="s.refresh()">立即重试</button>
      </p>
      <p v-else-if="s.error || s.notice" class="nx2-banner" :class="{ 'nx2-banner--error': s.error }" :role="s.error ? 'alert' : 'status'">
        {{ s.error || s.notice }}
        <button class="nx2-icon" aria-label="关闭提示" @click="(s.error = ''), (s.notice = '')"><X :size="13" /></button>
      </p>

      <main class="nx2-body">
        <Transition name="nx-page">
          <component
            :is="current.component"
            v-if="s.state"
            :key="page"
            :session="s"
            :report="report"
            :section="section"
            :sections="SECTIONS"
            @navigate="show"
            @diagnostic="diagnostic"
            @settings="openSettings"
            @section="section = $event"
          />
          <div v-else class="nx2-loading" aria-live="polite">
            <p>正在读取网络状态…</p>
            <button v-if="s.connectionError" class="nx2-link" @click="s.refresh()">重新连接</button>
          </div>
        </Transition>
      </main>
    </div>
  </div>
</template>
