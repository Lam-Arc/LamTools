<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ArrowLeftRight, Search, RefreshCw } from "lucide-vue-next";
const props = defineProps({ session: Object });
const filter = ref(""),
  rows = ref([]),
  total = ref(0),
  limit = ref(150),
  loading = ref(true);
let generation = 0;
async function query() {
  // user:“确保视觉、功能和交互不退化”+(只接受最近一次搜索结果，旧请求不能提前结束加载)。
  const current = ++generation;
  loading.value = true;
  try {
    const result = await props.session.read("connections", {
      filter: filter.value,
    });
    if (current !== generation) return;
    if (result) {
      rows.value = result.connections || [];
      total.value = result.total ?? rows.value.length;
      limit.value = 150;
    }
  } finally {
    if (current === generation) loading.value = false;
  }
}
const visible = computed(() => rows.value.slice(0, limit.value));
function status(value) {
  return (
    {
      Established: "已连接",
      Listen: "监听中",
      Bound: "等待连接",
      TimeWait: "连接结束",
      CloseWait: "正在关闭",
      SynSent: "正在连接",
    }[value] || value
  );
}
onMounted(query);
onBeforeUnmount(() => { generation += 1; });
</script>
<template>
  <div class="nx2-page">
    <form class="nx2-composer nx2-composer--inline" data-connections-searchbar @submit.prevent="query">
      <input v-model="filter" class="nx2-input" placeholder="搜索应用、IP 或端口" aria-label="搜索连接" />
      <button class="nx2-btn" :disabled="loading"><RefreshCw :size="13" />刷新</button>
      <span class="nx2-row-hint">{{ total }} 个连接</span>
    </form>

    <section class="nx2-group">
      <table v-if="visible.length" class="nx2-table">
        <thead><tr><th>应用</th><th>本地端口</th><th>远端</th><th>协议</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="(row, index) in visible" :key="index">
            <td :title="row.path || ''"><strong>{{ row.process || "未知应用" }}</strong><small class="nx2-row-hint" v-if="row.pid"> PID {{ row.pid }}</small></td>
            <td class="nx2-mono">{{ row.local_port }}</td>
            <td class="nx2-mono nx2-dim">{{ row.remote_address ? `${row.remote_address}:${row.remote_port}` : "—" }}</td>
            <td><span class="nx2-tag">{{ row.protocol }}</span></td>
            <td><span class="nx2-tag" :class="{ 'is-ok': row.state === 'Established' }">{{ status(row.state) }}</span></td>
          </tr>
        </tbody>
      </table>
      <div v-else-if="loading" class="nx2-rows" data-connections-loading>
        <div v-for="n in 5" :key="n" class="nx2-row"><span class="nx2-skeleton-line" /></div>
      </div>
      <p v-else class="nx2-empty-line">没有匹配的连接。换个应用名、地址或端口试试。</p>
      <button v-if="rows.length > limit" class="nx2-btn nx2-btn--ghost nx2-wide" @click="limit += 150">再多显示 150 条</button>
    </section>
  </div>
</template>
