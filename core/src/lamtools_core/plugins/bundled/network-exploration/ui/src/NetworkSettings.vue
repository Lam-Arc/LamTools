<script setup>
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络按钮复用共享角色样式，保留原操作与紧凑尺寸)。
// user:“可交互式网络工具界面，不需要太专业”+(网络信息按接口展示，需要修改时才展开表单)。
import { computed, ref } from "vue";
// user:“统一与去重：建立统一的 Design Tokens 和可复用组件体系”+(网络接口、查询方式和规则出口使用共享下拉)。
import UiSelect from "../../../../../../../ui/src/components/UiSelect.vue";
import {
  Monitor,
  Globe,
  Search,
  ChevronDown,
  Settings2,
  Plus,
  X,
} from "lucide-vue-next";
const props = defineProps({ session: Object });
const editing = ref(false),
  interfaceIndex = ref(""),
  servers = ref("1.1.1.1,8.8.8.8"),
  query = ref("github.com"),
  provider = ref("system"),
  answers = ref(null),
  ruleEditor = ref(false),
  rules = ref(null),
  domain = ref(""),
  outbound = ref("DIRECT"),
  matched = ref(null);
const interfaceOptions = computed(() => props.session.interfaces.map(adapter => ({ value: String(adapter.index), label: adapter.name })));
const providerOptions = [{ value: 'system', label: '系统 DNS' }, { value: 'cloudflare', label: 'Cloudflare' }, { value: 'google', label: 'Google' }];
const outboundOptions = [{ value: 'DIRECT', label: '直接连接' }, { value: 'PROXY', label: '通过代理' }, { value: 'REJECT', label: '阻止连接' }];
async function lookup() {
  answers.value = await props.session.run("dns.query", {
    domain: query.value.trim(),
    provider: provider.value,
    type: "A",
  });
}
async function saveDns() {
  if (!interfaceIndex.value) return;
  const result = await props.session.run(
    "system.apply",
    {
      kind: "dns",
      interface_index: Number(interfaceIndex.value),
      servers: servers.value
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean),
    },
    "DNS 设置已更新",
  );
  // user:“确保视觉、功能和交互不退化”+(取消修改后保留编辑表单，不能误报完成)。
  if (result && !result.cancelled) {
    editing.value = false;
    const response = await props.session.read("interfaces");
    if (response) props.session.interfaces = response.interfaces || [];
  }
}
function editRules() {
  rules.value = (props.session.state.rules || []).map((row) => ({ ...row }));
  ruleEditor.value = !ruleEditor.value;
}
async function saveRules() {
  await props.session.run(
    "rules.save",
    { revision: props.session.state.revision, rules: rules.value },
    "规则已保存",
  );
}
async function testRules() {
  matched.value = await props.session.run("rules.test", {
    domain: domain.value,
  });
}
</script>
<template>
  <div class="nx2-page">
    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>本机网络</h2>
        <button class="nx2-btn" data-dns-toggle :aria-expanded="editing" @click="editing = !editing">
          <Settings2 :size="14" />{{ editing ? "收起 DNS 修改" : "调整 DNS" }}
        </button>
      </header>
      <table class="nx2-table">
        <thead><tr><th>网卡</th><th>地址</th><th>网关</th><th>DNS</th></tr></thead>
        <tbody>
          <tr v-for="adapter in session.interfaces" :key="adapter.index">
            <td>{{ adapter.name }}</td>
            <td class="nx2-mono">{{ (adapter.ipv4 || []).join("、") || "—" }}</td>
            <td class="nx2-mono">{{ (adapter.gateway || []).join("、") || "—" }}</td>
            <td class="nx2-mono nx2-dim">{{ (adapter.dns || []).join("、") || "—" }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="editing" class="nx2-station">
      <div class="nx2-station-top">
        <span class="nx2-station-icon"><Settings2 :size="18" /></span>
        <span class="nx2-station-title">调整 DNS<small class="nx2-row-hint">修改前会保存原设置，可恢复</small></span>
      </div>
      <div class="nx2-form-grid">
        <div><span>网络接口</span><UiSelect v-model="interfaceIndex" :options="interfaceOptions" placeholder="选择正在使用的网络" aria-label="网络接口" data-network-interface :menu-min-width="180" /></div>
        <label><span>DNS 地址（逗号分隔）</span><input v-model="servers" class="nx2-input" placeholder="1.1.1.1, 8.8.8.8" /></label>
        <div class="nx2-form-actions"><button class="nx2-btn nx2-btn--primary" data-dns-apply :disabled="Boolean(session.busy) || !interfaceIndex" @click="saveDns">应用</button></div>
      </div>
      <p class="nx2-note">之后可在「防护 → 网络设置记录」里恢复原设置。</p>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head"><h2>查询网站地址</h2></header>
      <form class="nx2-composer nx2-composer--inline" @submit.prevent="lookup">
        <input v-model="query" class="nx2-input" placeholder="输入域名" aria-label="查询域名" />
        <UiSelect v-model="provider" :options="providerOptions" aria-label="查询方式" data-network-dns-provider :menu-min-width="150" />
        <button class="nx2-btn" :disabled="Boolean(session.busy)"><Search :size="13" />查询</button>
      </form>
      <div v-if="answers" class="nx2-rows" data-dns-result>
        <div v-if="answers.addresses?.length" class="nx2-row"><span class="nx2-row-label">地址</span><span class="nx2-row-value nx2-mono">{{ answers.addresses.join("、") }}</span><span class="nx2-row-hint">{{ answers.ms }} ms</span></div>
        <div v-else-if="answers.answers?.length" class="nx2-row"><span class="nx2-row-label">记录</span><span class="nx2-row-value nx2-mono">{{ answers.answers.slice(0, 4).map((row) => row.data || row.IPAddress || "").join("、") }}</span><span class="nx2-row-hint">{{ answers.ms }} ms</span></div>
        <p v-else class="nx2-empty-line">没有取到解析结果。</p>
      </div>
    </section>

    <section class="nx2-group">
      <header class="nx2-group-head">
        <h2>域名规则</h2>
        <button class="nx2-btn nx2-btn--ghost" data-rules-edit :aria-expanded="ruleEditor" @click="editRules">{{ ruleEditor ? "收起" : "编辑规则" }}</button>
      </header>
      <div v-if="ruleEditor" class="nx2-rows">
        <div v-for="(rule, index) in rules" :key="index" class="nx2-row nx2-row--cols">
          <input v-model="rule.domain" class="nx2-input" placeholder="例如 github.com" aria-label="规则域名" />
          <UiSelect v-model="rule.outbound" :options="outboundOptions" aria-label="规则出口" data-network-rule-outbound :menu-min-width="140" />
          <button class="nx2-icon" aria-label="删除规则" @click="rules.splice(index, 1)"><X :size="14" /></button>
        </div>
        <div class="nx2-actions">
          <button class="nx2-btn nx2-btn--ghost" @click="rules.push({ domain: '', outbound: 'DIRECT' })"><Plus :size="13" />添加规则</button>
          <button class="nx2-btn" :disabled="Boolean(session.busy)" @click="saveRules">保存规则</button>
        </div>
      </div>
      <form class="nx2-composer nx2-composer--inline" @submit.prevent="testRules">
        <input v-model="domain" class="nx2-input" placeholder="输入域名，看看会匹配到哪里" aria-label="测试规则域名" />
        <button class="nx2-btn" :disabled="Boolean(session.busy)">测试匹配</button>
      </form>
      <p v-if="matched" class="nx2-note">匹配结果：{{ matched.outbound }}（未应用到系统代理）。</p>
    </section>
  </div>
</template>
