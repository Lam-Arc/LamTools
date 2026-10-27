<script setup>
// user:“可交互式网络工具界面，不需要太专业”+(网络信息按接口展示，需要修改时才展开表单)。
import { ref } from "vue";
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
  if (result) {
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
  <div class="nx-view-stack">
    <div class="nx-section-heading">
      <div>
        <h2>本机网络</h2>
        <p>查看当前地址和正在使用的 DNS。</p>
      </div>
      <button
        class="nx-button nx-secondary"
        :aria-expanded="editing"
        @click="editing = !editing"
      >
        <Settings2 :size="15" />调整 DNS
      </button>
    </div>
    <section class="nx-panel nx-interface-list">
      <article
        v-for="adapter in session.interfaces"
        :key="adapter.index"
        class="nx-interface"
      >
        <span class="nx-control-icon"><Monitor :size="20" /></span>
        <div>
          <strong>{{ adapter.name }}</strong>
          <dl>
            <div>
              <dt>本机地址</dt>
              <dd>{{ adapter.ipv4?.join("、") || "没有 IPv4 地址" }}</dd>
            </div>
            <div>
              <dt>DNS</dt>
              <dd>{{ adapter.dns?.join("、") || "由系统提供" }}</dd>
            </div>
            <div v-if="adapter.gateway?.length">
              <dt>网关</dt>
              <dd>{{ adapter.gateway.join("、") }}</dd>
            </div>
          </dl>
        </div>
      </article>
      <div v-if="!session.interfaces.length" class="nx-empty nx-empty--small">
        <Monitor :size="25" /><span>暂时没有读取到网络接口。</span>
      </div>
    </section>
    <form v-if="editing" class="nx-panel nx-form" @submit.prevent="saveDns">
      <h2>调整 DNS</h2>
      <div class="nx-form-grid">
        <label
          ><span>网络接口</span
          ><select
            v-model="interfaceIndex"
            class="nx-input"
            required
            aria-label="网络接口"
          >
            <option disabled value="">选择正在使用的网络</option>
            <option
              v-for="adapter in session.interfaces"
              :key="adapter.index"
              :value="adapter.index"
            >
              {{ adapter.name }}
            </option>
          </select></label
        ><label
          ><span>DNS 地址</span
          ><input
            v-model="servers"
            class="nx-input"
            required
            placeholder="多个地址用逗号隔开"
        /></label>
      </div>
      <p class="nx-help">修改前会保存原设置，之后可在“防护”中恢复。</p>
      <button class="nx-button nx-secondary" :disabled="Boolean(session.busy)">
        确认并申请修改
      </button>
    </form>
    <section class="nx-panel nx-form">
      <div class="nx-panel-heading">
        <h2><Globe :size="17" />查询网站地址</h2>
      </div>
      <form class="nx-inline-form" @submit.prevent="lookup">
        <input
          v-model="query"
          class="nx-input"
          placeholder="输入域名"
          aria-label="查询域名"
          required
        /><select
          v-model="provider"
          class="nx-input nx-fit-select"
          aria-label="查询方式"
        >
          <option value="system">系统 DNS</option>
          <option value="cloudflare">Cloudflare</option>
          <option value="google">Google</option></select
        ><button
          class="nx-button nx-secondary"
          :disabled="Boolean(session.busy)"
        >
          <Search :size="14" />查询
        </button>
      </form>
      <div v-if="answers" class="nx-query-result">
        <span class="nx-subtle"
          >{{ answers.domain }} · {{ answers.ms || 0 }} ms</span
        >
        <div
          v-for="(answer, index) in answers.addresses || answers.answers || []"
          :key="index"
          class="nx-query-address"
        >
          {{ typeof answer === "string" ? answer : answer.data }}
        </div>
        <span v-if="!(answers.addresses || answers.answers || []).length"
          >没有查到地址</span
        >
      </div>
    </section>
    <section class="nx-settings-fold">
      <button
        class="nx-button nx-quiet"
        :aria-expanded="ruleEditor"
        @click="editRules"
      >
        网站规则匹配预览<ChevronDown :size="13" />
      </button>
      <div v-if="ruleEditor" class="nx-panel nx-form">
        <p class="nx-help">
          用于检查匹配结果；实际代理分流以订阅中的规则为准。
        </p>
        <div v-for="(rule, index) in rules" :key="index" class="nx-rule-row">
          <input
            v-model="rule.domain"
            class="nx-input"
            placeholder="例如 github.com"
            aria-label="规则域名"
          /><select
            v-model="rule.outbound"
            class="nx-input"
            aria-label="规则出口"
          >
            <option value="DIRECT">直接连接</option>
            <option value="PROXY">通过代理</option>
            <option value="REJECT">阻止连接</option></select
          ><button
            class="nx-button nx-quiet nx-icon-button"
            aria-label="删除规则"
            @click="rules.splice(index, 1)"
          >
            <X :size="14" />
          </button>
        </div>
        <div class="nx-actions">
          <button
            class="nx-button nx-quiet"
            @click="rules.push({ domain: '', outbound: 'DIRECT' })"
          >
            <Plus :size="14" />添加规则</button
          ><button
            class="nx-button nx-secondary"
            :disabled="Boolean(session.busy)"
            @click="saveRules"
          >
            保存规则
          </button>
        </div>
        <form class="nx-inline-form" @submit.prevent="testRules">
          <input
            v-model="domain"
            class="nx-input"
            required
            placeholder="输入域名，看看会匹配到哪里"
            aria-label="测试规则域名"
          /><button
            class="nx-button nx-secondary"
            :disabled="Boolean(session.busy)"
          >
            测试匹配
          </button>
        </form>
        <p v-if="matched">
          {{
            matched.matched
              ? `匹配到 ${matched.matched.domain}`
              : "未匹配到专属规则"
          }}
          ·
          {{
            { DIRECT: "直接连接", PROXY: "通过代理", REJECT: "阻止连接" }[
              matched.outbound
            ]
          }}
        </p>
      </div>
    </section>
  </div>
</template>
