<script setup>
// user:“互联：我的设备、文件传输、私人网络”“不再开发 EasyNet 专属配对系统”+(设备与互传沿用宿主的设备连接页，这里只做入口和本机局域网概览)。
import { computed, onMounted, ref } from "vue";
import { Network, ArrowUpRight, Send, Lock, RefreshCw } from "lucide-vue-next";
const props = defineProps({ session: Object });
const neighbors = ref([]),
  loading = ref(false),
  error = ref("");
const localAddresses = computed(() =>
  (props.session.interfaces || [])
    .flatMap((row) => (row.ipv4 || []).map((ip) => ({ name: row.name, ip })))
    .filter((row) => row.ip && !row.ip.startsWith("127.")),
);
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
// user:“只放跳转链接到现有设备连接页”+(不在插件里再造一套配对与设备状态；交给宿主的设备页)。
function openDevicePage() {
  window.dispatchEvent(
    new CustomEvent("sunday:open-app-page", { detail: { view: "account" } }),
  );
}
onMounted(loadNeighbors);
</script>
<template>
  <div class="nx-view-stack">
    <section class="nx-panel nx-interconnect-hero">
      <div class="nx-quick-icon"><Network :size="20" :stroke-width="1.7" /></div>
      <div class="nx-control-copy">
        <h2>我的设备</h2>
        <p>
          手机与电脑的配对、扫码和解除绑定都在「设备连接」里完成，这里不重复一套。
        </p>
      </div>
      <button
        class="btn nx-button btn--primary"
        data-open-device-page
        @click="openDevicePage"
      >
        打开设备连接<ArrowUpRight :size="14" />
      </button>
    </section>

    <div class="nx-interconnect-grid">
      <section class="nx-panel">
        <div class="nx-panel-heading">
          <h2><Send :size="17" />文件互传</h2>
        </div>
        <p class="nx-help">
          发送文件走「设备连接」里的设备列表：只允许已信任设备，传输有进度、可取消。
          接收到的文件落在对方约定的目录，重名不会覆盖。
        </p>
        <div class="nx-actions">
          <button class="btn nx-button btn--secondary" @click="openDevicePage">
            选择设备发送
          </button>
        </div>
      </section>

      <section class="nx-panel">
        <div class="nx-panel-heading">
          <h2><Lock :size="17" />私人网络（虚拟局域网）</h2>
          <span class="nx-subtle">尚未提供</span>
        </div>
        <p class="nx-help">
          让异地设备像在同一局域网里互访（共享文件夹、NAS、局域网应用）属于可选增强，
          需要先评估内核许可与资源占用，当前版本没有实现，界面也不会假装已开启。
        </p>
      </section>
    </div>

    <section class="nx-panel">
      <div class="nx-panel-heading">
        <h2>本机在局域网中的地址</h2>
        <button
          class="btn nx-button btn--quiet nx-icon-button"
          aria-label="刷新局域网设备"
          :disabled="loading"
          @click="loadNeighbors"
        >
          <RefreshCw :size="15" />
        </button>
      </div>
      <div v-if="localAddresses.length" class="nx-fact-list">
        <div v-for="row in localAddresses" :key="row.ip" class="nx-fact">
          <span>{{ row.name }}</span><strong>{{ row.ip }}</strong>
        </div>
      </div>
      <p v-else class="nx-help">还没有读到本机地址，稍后刷新一次。</p>
      <p v-if="error" class="nx-help nx-danger-text" role="alert">{{ error }}</p>
      <p class="nx-help">
        同一局域网内已知设备 {{ neighbors.length }} 台（来自系统邻居缓存，不代表全部在线）。
      </p>
    </section>
  </div>
</template>
