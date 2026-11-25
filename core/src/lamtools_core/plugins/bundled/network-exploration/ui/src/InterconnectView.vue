<script setup>
// user:“互联设置那些 UI 都是狗屎吧！重新设计”+(互联页按「本机 → 局域网 → 我的设备 → 私人网络」排，全是可核对的行与表)。
import { computed, onMounted, ref } from "vue";
import { RefreshCw, ArrowUpRight } from "lucide-vue-next";
const props = defineProps({ session: Object });
const neighbors = ref([]),
  loading = ref(false),
  error = ref("");
const interfaces = computed(() => props.session.interfaces || []);
const localRows = computed(() =>
  interfaces.value.flatMap((row) => (row.ipv4 || []).map((ip) => ({
    name: row.name,
    ip,
    gateway: (row.gateway || [])[0] || "",
    dns: (row.dns || []).join("、"),
  }))),
);
const reachable = computed(() => neighbors.value.filter((row) => String(row.state || "").toLowerCase() === "reachable").length);
async function loadNeighbors() {
  loading.value = true;
  error.value = "";
  try {
    const result = await props.session.read("lan");
    if (result) neighbors.value = result.devices || [];
  } finally {
    loading.value = false;
  }
}
// user:“只放跳转链接到现有设备连接页”+(配对与互传仍由宿主的设备页负责)。
function openDevicePage() {
  window.dispatchEvent(new CustomEvent("sunday:open-app-page", { detail: { view: "account" } }));
}
onMounted(loadNeighbors);
</script>
<template>
  <div class="nx2-page">
    <section class="nx2-group">
      <header class="nx2-group-head"><h2>本机</h2><span class="nx2-row-hint">这台电脑在局域网里的身份</span></header>
      <div v-if="localRows.length" class="nx2-rows">
        <div v-for="row in localRows" :key="row.name + row.ip" class="nx2-row nx2-row--cols">
          <span class="nx2-row-label">{{ row.name }}</span>
          <b class="nx2-mono">{{ row.ip }}</b>
          <span class="nx2-row-hint">网关 {{ row.gateway || "—" }}</span>
          <span class="nx2-row-hint nx2-ellipsis" :title="row.dns">DNS {{ row.dns || "—" }}</span>
        </div>
      </div>
      <p v-else class="nx2-empty-line">还没有读到本机地址，稍后刷新一次。</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>局域网设备</h2>
        <span class="nx2-row-hint">{{ neighbors.length }} 台，其中 {{ reachable }} 台可达</span>
        <button class="nx2-icon" aria-label="刷新局域网设备" :disabled="loading" @click="loadNeighbors"><RefreshCw :size="14" /></button>
      </header>
      <table v-if="neighbors.length" class="nx2-table">
        <thead><tr><th>地址</th><th>物理地址</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="row in neighbors" :key="row.IPAddress">
            <td class="nx2-mono">{{ row.IPAddress }}</td>
            <td class="nx2-mono nx2-dim">{{ row.LinkLayerAddress || "—" }}</td>
            <td>{{ row.state === "Reachable" ? "可达" : row.state === "Stale" ? "过期缓存" : row.state || "未知" }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="nx2-empty-line">邻居缓存里还没有设备。</p>
      <p class="nx2-note">来自系统邻居缓存，只能说明近期通信过，不代表现在都在线。</p>
      <p v-if="error" class="nx2-note nx2-bad" role="alert">{{ error }}</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>我的设备</h2></header>
      <div class="nx2-rows">
        <div class="nx2-row nx2-row--action">
          <span class="nx2-row-value">配对、发文件、远程操作都在「设备连接」里完成，这里不重复一套。</span>
          <button class="nx2-btn" data-open-device-page @click="openDevicePage">打开设备连接<ArrowUpRight :size="13" /></button>
        </div>
      </div>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>私人网络（虚拟局域网）</h2><span class="nx2-tag">尚未提供</span></header>
      <p class="nx2-note">
        让异地设备像在同一局域网里互访（共享文件夹、NAS、局域网应用）属于可选增强，
        需要先评估内核许可与资源占用。当前版本没有实现，界面也不会假装已开启。
      </p>
    </section>
  </div>
</template>
