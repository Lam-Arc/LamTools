<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“你应当设计的是一个高级、简洁、现代的网络工具界面，不用管跟 sunday 是否适配”+(使用独立深色视觉和简洁导航，不继承宿主面板布局)。
// user:“概览、下载、互联、诊断四个视图，代理和高级网络设置放进设置页”+(左栏只留四件常用事，其余收进设置，不再有进不去的页面)。
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  Network,
  Home,
  Download,
  Activity,
  Settings2,
  RefreshCw,
  X,
} from "lucide-vue-next";
import { useNetwork } from "./session.mjs";
import HomeView from "./HomeView.vue";
import TransferView from "./TransferView.vue";
import InterconnectView from "./InterconnectView.vue";
import DiagnoseView from "./DiagnoseView.vue";
import SettingsView from "./SettingsView.vue";
const props = defineProps({ context: { type: Object, required: true } });
const s = useNetwork(props.context),
  report = ref(null);
// user:“概览/下载/互联/诊断”+(四个平级视图；设置是独立入口，不占用第四个以上的平级位置)。
const items = [
  {
    id: "overview",
    title: "概览",
    hint: "网络状态、速率与常用操作",
    icon: Home,
    component: HomeView,
  },
  {
    id: "transfer",
    title: "下载",
    hint: "任务、进度与文件",
    icon: Download,
    component: TransferView,
  },
  {
    id: "devices",
    title: "互联",
    hint: "我的设备与文件互传",
    icon: Network,
    component: InterconnectView,
  },
  {
    id: "diagnose",
    title: "诊断",
    hint: "检查网络并定位问题",
    icon: Activity,
    component: DiagnoseView,
  },
];
const settingsItem = {
  id: "settings",
  title: "设置",
  hint: "代理、加速与高级网络设置",
  icon: Settings2,
  component: SettingsView,
};
const navItems = items;
// user:“代理和高级网络设置置于设置页，不新增大量平级入口”+(设置页用分区切换，六个分区都在同一页)。
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
// 旧入口（快捷胶囊、卡片链接）用功能名指路；统一在这里翻译成新结构，避免出现进不去的页面。
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
  page.value === "settings"
    ? settingsItem
    : items.find((item) => item.id === page.value) || items[0],
);
function diagnostic(value) {
  report.value = value;
  page.value = "diagnose";
}
onMounted(() =>
  window.addEventListener("sunday:network-plugin-page", quickPage),
);
onBeforeUnmount(() =>
  window.removeEventListener("sunday:network-plugin-page", quickPage),
);
</script>
<template>
  <div class="nx-app" :aria-busy="Boolean(s.busy)">
    <aside class="nx-sidebar">
      <div class="nx-brand" title="EasyNet">
        <Network :size="25" :stroke-width="1.7" /><span>EasyNet</span>
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
        <div class="nx-nav-divider" />
        <button
          class="nx-nav-item"
          :class="{ 'is-active': page === 'settings' }"
          data-settings
          :aria-current="page === 'settings' ? 'page' : undefined"
          :title="settingsItem.hint"
          @click="openSettings()"
        >
          <component
            :is="settingsItem.icon"
            :size="20"
            :stroke-width="1.65"
          /><span>{{ settingsItem.title }}</span>
        </button>
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
            class="btn nx-button btn--quiet nx-icon-button"
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
        ><button class="btn nx-button btn--quiet" @click="s.refresh()">重试</button>
      </div>
      <div
        v-if="s.error || s.notice"
        class="nx-notice"
        :class="{ 'nx-notice--error': s.error }"
        :role="s.error ? 'alert' : 'status'"
      >
        <span>{{ s.error || s.notice }}</span
        ><button
          class="btn nx-button btn--quiet nx-icon-button"
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
            :section="section"
            :sections="SECTIONS"
            @navigate="show"
            @diagnostic="diagnostic"
            @settings="openSettings"
            @section="section = $event"
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
              class="btn nx-button btn--secondary"
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
