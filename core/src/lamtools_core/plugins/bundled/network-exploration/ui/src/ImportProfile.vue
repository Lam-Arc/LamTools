<script setup>
// user:“可交互式网络工具界面，不需要太专业”+(订阅为默认导入方式，配置文件作为可选入口)。
import { ref } from "vue";
import { Link, FileUp, X, Eye, EyeOff } from "lucide-vue-next";
const props = defineProps({ session: Object, autoStart: Boolean });
const emit = defineEmits(["close"]);
const url = ref(""),
  visible = ref(false),
  fileInput = ref(null),
  advanced = ref(false),
  content = ref("");
async function save(payload) {
  // user:“添加不了订阅”“把操作傻瓜化”+(保存订阅时自动暂停并重连，不再要求先手动关闭连接)。
  const wasRunning = Boolean(props.session.state?.proxy?.running);
  const wasAccelerated = Boolean(props.session.accelerated);
  if (wasRunning) {
    const stopped = await props.session.run("proxy.stop", {}, "");
    if (!stopped) return;
  }
  const result = await props.session.run("proxy.config", payload, "");
  if (!result) return;
  url.value = "";
  content.value = "";
  emit("close");
  if (wasRunning) {
    const started = await props.session.run("proxy.start", {}, "");
    if (started) {
      props.session.notice = "订阅已更新，线路已重新连接";
      await props.session.loadProxy();
      if (wasAccelerated) await props.session.toggleAcceleration();
    }
  } else if (props.autoStart) {
    // user:“就像是用 watt toolkit 一样，点一下‘一键加速’”+(添加完订阅直接开启加速，不用再点第二次)。
    await props.session.toggleAcceleration();
  } else {
    props.session.notice = "订阅已保存，现在可以开启加速";
  }
}
async function readFile(event) {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    props.session.error = "配置文件不能超过 2 MB";
    return;
  }
  await save({ content: await file.text() });
}
</script>
<template>
  <section class="nx-panel nx-import" data-profile-import>
    <div class="nx-panel-heading">
      <h2><Link :size="17" />添加订阅</h2>
      <button
        class="nx-button nx-quiet nx-icon-button"
        aria-label="收起订阅设置"
        @click="$emit('close')"
      >
        <X :size="16" />
      </button>
    </div>
    <p class="nx-help">粘贴你的订阅链接。已有配置文件也可以直接导入。</p>
    <form
      class="nx-inline-form"
      @submit.prevent="save({ subscription: url.trim() })"
    >
      <label class="nx-input-with-action"
        ><input
          v-model="url"
          :type="visible ? 'text' : 'password'"
          class="nx-input"
          required
          placeholder="https://…"
          aria-label="订阅链接"
          autocomplete="off" /><button
          class="nx-button nx-quiet nx-icon-button"
          type="button"
          :aria-label="visible ? '隐藏订阅链接' : '显示订阅链接'"
          @click="visible = !visible"
        >
          <component :is="visible ? EyeOff : Eye" :size="16" /></button></label
      ><button
        class="nx-button nx-primary"
        :disabled="Boolean(session.busy) || !url.trim()"
      >
        {{ session.busy === "proxy.config" ? "正在下载…" : "保存订阅" }}
      </button>
    </form>
    <p v-if="session.busy === 'proxy.config'" class="nx-help">
      正在下载订阅。慢速订阅可能需要几十秒，请不要关闭页面。
    </p>
    <div class="nx-import-options">
      <button
        class="nx-button nx-quiet"
        :disabled="Boolean(session.busy)"
        @click="fileInput.click()"
      >
        <FileUp :size="14" />导入配置文件</button
      ><button
        class="nx-button nx-quiet"
        :aria-expanded="advanced"
        @click="advanced = !advanced"
      >
        {{ advanced ? "收起文本配置" : "粘贴配置文本" }}</button
      ><input
        ref="fileInput"
        type="file"
        accept=".yaml,.yml,.txt"
        hidden
        @change="readFile"
      />
    </div>
    <form v-if="advanced" class="nx-form" @submit.prevent="save({ content })">
      <textarea
        v-model="content"
        class="nx-input nx-code"
        rows="7"
        aria-label="代理配置文本"
        placeholder="粘贴 Mihomo / Clash YAML 配置"
        required
      /><button
        class="nx-button nx-secondary"
        :disabled="Boolean(session.busy)"
      >
        保存配置
      </button>
    </form>
    <p v-if="session.state?.proxy?.running" class="nx-help">
      当前连接已开启。保存订阅或配置时会自动断开并重新连接，不需要手动关闭。
    </p>
  </section>
</template>
