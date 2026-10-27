<script setup>
import { computed, onMounted, ref } from "vue";
import { ArrowLeftRight, Search, RefreshCw } from "lucide-vue-next";
const props = defineProps({ session: Object });
const filter = ref(""),
  rows = ref([]),
  total = ref(0),
  limit = ref(150),
  loading = ref(true);
async function query() {
  loading.value = true;
  const result = await props.session.read("connections", {
    filter: filter.value,
  });
  if (result) {
    rows.value = result.connections || [];
    total.value = result.total || rows.value.length;
    limit.value = 150;
  }
  loading.value = false;
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
</script>
<template>
  <div class="nx-view-stack">
    <div class="nx-section-heading">
      <div>
        <h2>应用正在连接什么</h2>
        <p>按应用、地址或端口查找当前连接。</p>
      </div>
      <span class="nx-subtle">{{ total }} 个连接</span>
    </div>
    <form class="nx-inline-form nx-searchbar" @submit.prevent="query">
      <label class="nx-input-with-icon"
        ><Search :size="16" /><input
          v-model="filter"
          class="nx-input"
          placeholder="搜索应用、IP 或端口"
          aria-label="搜索连接" /></label
      ><button class="nx-button nx-secondary" :disabled="loading">
        <RefreshCw :size="14" />刷新
      </button>
    </form>
    <section class="nx-panel nx-table-panel">
      <div v-if="loading" class="nx-table-loading">
        <div v-for="n in 5" :key="n" class="nx-skeleton nx-skeleton-row" />
      </div>
      <div v-else class="nx-table-scroll">
        <table class="nx-table">
          <thead>
            <tr>
              <th>应用</th>
              <th>本地端口</th>
              <th>远端地址</th>
              <th>协议</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in visible" :key="index">
              <td :title="row.path || ''">
                <strong>{{ row.process || "未知应用" }}</strong
                ><small v-if="row.pid">PID {{ row.pid }}</small>
              </td>
              <td>{{ row.local_port }}</td>
              <td class="nx-data-cell">
                {{
                  row.remote_address
                    ? `${row.remote_address}:${row.remote_port}`
                    : "—"
                }}
              </td>
              <td>
                <span class="nx-protocol">{{ row.protocol }}</span>
              </td>
              <td>
                <span
                  class="nx-connection-state"
                  :class="{ 'is-live': row.state === 'Established' }"
                  >{{ status(row.state) }}</span
                >
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="!rows.length" class="nx-empty">
          <ArrowLeftRight :size="28" /><strong>没有匹配的连接</strong>
          <p>试着输入其他应用名称、地址或端口。</p>
        </div>
      </div>
      <button
        v-if="rows.length > limit"
        class="nx-button nx-quiet nx-load-more"
        @click="limit += 150"
      >
        再显示 150 个连接
      </button>
    </section>
    <p class="nx-help">这里显示连接和端口，不代表每个应用的流量大小。</p>
  </div>
</template>
