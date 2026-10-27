<script setup>
// user:“你应当设计的是一个高级、简洁、现代的网络工具界面，不用管跟 sunday 是否适配”+(使用独立深色视觉和简洁导航，不继承宿主面板布局)。
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  Network,
  Home,
  Zap,
  Globe,
  Download,
  Activity,
  Settings2,
  ArrowLeftRight,
  ShieldCheck,
  SlidersHorizontal,
  RefreshCw,
  X,
  ChevronRight,
} from "lucide-vue-next";
import { useNetwork } from "./session.mjs";
import HomeView from "./HomeView.vue";
import DashboardView from "./DashboardView.vue";
import ProxyView from "./ProxyView.vue";
import TransferView from "./TransferView.vue";
import DiagnoseView from "./DiagnoseView.vue";
import NetworkSettings from "./NetworkSettings.vue";
import ConnectionsView from "./ConnectionsView.vue";
import SecurityView from "./SecurityView.vue";
import AdvancedView from "./AdvancedView.vue";
const props = defineProps({ context: { type: Object, required: true } });
const s = useNetwork(props.context),
  report = ref(null);
const items = [
  {
    id: "home",
    title: "首页",
    hint: "实时数据与常用操作",
    icon: Home,
    component: HomeView,
  },
  {
    id: "overview",
    title: "加速",
    hint: "本机加速开关与运行状态",
    icon: Zap,
    component: DashboardView,
  },
  {
    id: "proxy",
    title: "代理",
    hint: "订阅、节点与连接方式",
    icon: Globe,
    component: ProxyView,
  },
  {
    id: "transfer",
    title: "下载",
    hint: "文件下载与任务",
    icon: Download,
    component: TransferView,
  },
  {
    id: "diagnose",
    title: "检测",
    hint: "检查网站连接",
    icon: Activity,
    component: DiagnoseView,
  },
  {
    id: "network",
    title: "网络",
    hint: "接口与 DNS",
    icon: Settings2,
    component: NetworkSettings,
  },
  {
    id: "traffic",
    title: "连接",
    hint: "应用与端口",
    icon: ArrowLeftRight,
    component: ConnectionsView,
  },
  {
    id: "security",
    title: "防护",
    hint: "应用联网与恢复",
    icon: ShieldCheck,
    component: SecurityView,
  },
  {
    id: "advanced",
    title: "更多",
    hint: "定时检测与记录",
    icon: SlidersHorizontal,
    component: AdvancedView,
  },
];
// user:“左侧入口就保留3个就行 加速 代理 下载”+(其余页面保留内部入口，不再占用左侧导航)。
const navItems = items.filter((item) =>
  ["home", "overview", "proxy", "transfer"].includes(item.id),
);
// user:“右侧栏…三行 3 个胶囊…易交互”+(胶囊点下载/代理时直接落到对应页；页面已打开时用事件切页)。
const PAGE_STORAGE = "network-exploration:page";
function requestedPage() {
  try {
    const value = sessionStorage.getItem(PAGE_STORAGE);
    sessionStorage.removeItem(PAGE_STORAGE);
    return items.some((item) => item.id === value) ? value : "home";
  } catch {
    return "home";
  }
}
const page = ref(requestedPage());
function quickPage(event) {
  const id = event.detail?.page;
  if (items.some((item) => item.id === id)) {
    show(id);
    try {
      sessionStorage.removeItem(PAGE_STORAGE);
    } catch {
      // 页面没有 sessionStorage 时仍按事件切换。
    }
  }
}
onMounted(() =>
  window.addEventListener("sunday:network-plugin-page", quickPage),
);
onBeforeUnmount(() =>
  window.removeEventListener("sunday:network-plugin-page", quickPage),
);
const current = computed(() => items.find((item) => item.id === page.value));
function show(id) {
  page.value = id;
  s.notice = "";
  s.error = "";
}
function diagnostic(value) {
  report.value = value;
  page.value = "diagnose";
}
</script>
<template>
  <div class="nx-app" :aria-busy="Boolean(s.busy)">
    <aside class="nx-sidebar">
      <div class="nx-brand" title="Network Exploration">
        <Network :size="25" :stroke-width="1.7" /><span>Network</span>
      </div>
      <nav aria-label="网络工具">
        <template v-for="item in navItems" :key="item.id">
          <button
            class="nx-nav-item"
            :class="{ 'is-active': page === item.id }"
            :data-page="item.id"
            :aria-current="page === item.id ? 'page' : undefined"
            :title="item.hint"
            @click="show(item.id)"
          >
            <component
              :is="item.icon"
              :size="20"
              :stroke-width="1.65"
            /><span>{{ item.title }}</span>
          </button></template
        >
      </nav>
      <div class="nx-sidebar-foot">
        <span
          class="nx-live-dot"
          :class="{ 'is-offline': Boolean(s.connectionError) || !s.state }"
        /><span>{{
          s.connectionError ? "离线" : s.state ? "监测中" : "连接中"
        }}</span>
      </div>
    </aside>
    <div class="nx-workspace">
      <header class="nx-header">
        <div>
          <span class="nx-eyebrow">NETWORK CONSOLE</span>
          <h1>{{ current.title }}</h1>
          <p>{{ current.hint }}</p>
        </div>
        <div class="nx-header-actions">
          <span v-if="s.busy" class="nx-working">正在处理…</span
          ><span v-else-if="s.state && !s.connectionError" class="nx-live-label"
            ><span class="nx-live-dot" />实时更新</span
          ><button
            class="nx-button nx-quiet nx-icon-button"
            :disabled="Boolean(s.busy)"
            aria-label="刷新网络状态"
            @click="s.refresh()"
          >
            <RefreshCw :size="17" />
          </button>
        </div>
      </header>
      <div
        v-if="s.connectionError"
        class="nx-notice nx-notice--error"
        role="alert"
      >
        <span>暂时无法连接网络服务，请稍后重试。</span
        ><button class="nx-button nx-quiet" @click="s.refresh()">重试</button>
      </div>
      <div
        v-if="s.error || s.notice"
        class="nx-notice"
        :class="{ 'nx-notice--error': s.error }"
        :role="s.error ? 'alert' : 'status'"
      >
        <span>{{ s.error || s.notice }}</span
        ><button
          class="nx-button nx-quiet nx-icon-button"
          aria-label="关闭提示"
          @click="
            s.error = '';
            s.notice = '';
          "
        >
          <X :size="14" />
        </button>
      </div>
      <main class="nx-content ne-content">
        <Transition name="nx-page">
          <component
            :is="current.component"
            v-if="s.state"
            :key="page"
            :session="s"
            :report="report"
            @navigate="show"
            @diagnostic="diagnostic"
          />
          <div v-else key="loading" class="nx-loading" aria-live="polite">
            <div class="nx-skeleton nx-loading-banner" />
            <div class="nx-loading-grid">
              <div class="nx-skeleton nx-loading-chart" />
              <div class="nx-skeleton nx-loading-chart" />
            </div>
            <p>正在读取网络状态…</p>
            <button
              v-if="s.connectionError"
              class="nx-button nx-secondary"
              @click="s.refresh()"
            >
              重新连接
            </button>
          </div>
        </Transition>
      </main>
    </div>
  </div>
</template>
