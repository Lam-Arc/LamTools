// user:“常用功能放在首页 切梯子/网络加速”+(首页与各功能页共享真实状态，常用开关调用既有审批接口)。
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  shallowRef,
  watch,
} from "vue";
import { networkStore, bytes } from "../store.mjs";
export { bytes };
export const rate = (value) => (value == null ? "—" : `${bytes(value)}/s`);
export const taskLabel = (state) =>
  ({
    active: "下载中",
    waiting: "等待中",
    paused: "已暂停",
    complete: "已完成",
    removed: "已取消",
    error: "下载失败",
    recoverable: "待恢复",
  })[state] || "等待中";
export const dateLabel = (value) =>
  value
    ? new Date(value).toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "刚刚";
export const nodeLabel = (name) =>
  name === "DIRECT"
    ? "直接连接"
    : name === "REJECT"
      ? "阻止连接"
      : name || "尚未选择线路";
// user:“三个块分别是加速代理下载的快捷操作”+(下载块只让用户粘贴链接，文件名从链接里推导并清理 Windows 非法字符)。
export function filenameFromUrl(value) {
  let name;
  try {
    const path = new URL(String(value).trim()).pathname;
    name = decodeURIComponent(path.split("/").pop() || "");
  } catch {
    return "";
  }
  name = name
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_")
    .replace(/[. ]+$/g, "")
    .slice(0, 200);
  return name || "download.bin";
}
// user:“样式示例：不必照抄，只是方向”+(首页显示真实出口名称，嵌套分组继续解析到具体节点)。
export function resolveProxyNode(proxies, name, depth = 0) {
  const entry = proxies?.[name];
  if (!entry || !Array.isArray(entry.all) || !entry.now || depth > 4)
    return name;
  return resolveProxyNode(proxies, entry.now, depth + 1);
}
export function primaryNode(proxy) {
  const proxies = proxy?.proxies;
  if (!proxies) return "";
  const entries = Object.entries(proxies).filter(
    ([, node]) => Array.isArray(node.all) && node.now,
  );
  const chosen =
    entries.find(([name]) => name === "GLOBAL") ||
    entries.find(([, node]) => node.type === "Selector") ||
    entries[0];
  return chosen ? resolveProxyNode(proxies, chosen[1].now) : "";
}
// user:“样式示例：不必照抄，只是方向”+(首页计时使用控制器记录的真实启动时刻)。
export function uptime(started, now = Date.now()) {
  if (!started) return "";
  const time = new Date(started).getTime();
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, Math.floor((now - time) / 1000));
  return [Math.floor(seconds / 3600), Math.floor((seconds % 3600) / 60), seconds % 60]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}
export function useNetwork(context) {
  const state = shallowRef(null),
    proxy = ref(null),
    interfaces = ref([]),
    tasks = ref([]),
    systemProxy = ref(null);
  const busy = ref(""),
    error = ref(""),
    notice = ref(""),
    connectionError = ref("");
  const autoStartedProxy = ref(false);
  let disposed = false,
    proxyRequest;
  const rpc = async (method, params = {}) => {
    if (disposed || context.signal?.aborted) throw new Error("页面已关闭");
    const result = await context.rpc(`network-exploration.${method}`, params);
    if (disposed || context.signal?.aborted) throw new Error("页面已关闭");
    return result;
  };
  async function read(method, params = {}) {
    try {
      return await rpc(method, params);
    } catch (cause) {
      if (!disposed)
        error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    }
  }
  async function loadProxy() {
    if (!state.value?.proxy?.running) {
      proxy.value = null;
      return;
    }
    if (proxyRequest) return proxyRequest;
    proxyRequest = rpc("proxy.inspect")
      .then((result) => {
        proxy.value = result;
      })
      .catch((cause) => {
        if (!disposed) error.value = String(cause);
      })
      .finally(() => {
        proxyRequest = undefined;
      });
    return proxyRequest;
  }
  async function loadSystemProxy() {
    const result = await read("system.inspect", { kind: "proxy" });
    if (result) systemProxy.value = result;
  }
  async function loadTasks() {
    const result = await read("transfer.list");
    if (result) tasks.value = result.tasks || [];
  }
  async function run(method, params = {}, message = "") {
    if (busy.value) return null;
    busy.value = method;
    error.value = "";
    notice.value = "";
    try {
      const result = await rpc(method, params);
      notice.value = result.cancelled ? "已取消操作" : message;
      await networkStore.refresh();
      return result;
    } catch (cause) {
      if (!disposed)
        error.value = cause instanceof Error ? cause.message : String(cause);
      return null;
    } finally {
      if (!disposed) busy.value = "";
    }
  }
  async function toggleProxy() {
    // 用户手动接管代理后，停止加速时不再替用户关掉线路。
    autoStartedProxy.value = false;
    const running = state.value?.proxy?.running;
    const result = await run(
      running ? "proxy.stop" : "proxy.start",
      {},
      running ? "代理已关闭" : "代理已开启",
    );
    if (result) {
      await loadProxy();
      await loadSystemProxy();
    }
  }
  const ownedProxy = computed(() =>
    (state.value?.transactions || []).find(
      (row) => row.request?.kind === "proxy" && row.status === "applied",
    ),
  );
  // user:“加速页里头不用分什么线路加速，本机加速的意思就是本机加速选线路的事儿，去代理里面”+(加速页只做本机加速；订阅、节点和选线路都在代理页)。
  const accelerated = computed(() =>
    Boolean(
      state.value?.accelerator?.running &&
        systemProxy.value?.enabled === 1 &&
        systemProxy.value?.server ===
          `127.0.0.1:${state.value.accelerator.port}`,
    ),
  );
  const systemProxyReady = computed(() => systemProxy.value !== null);
  async function toggleAcceleration() {
    if (busy.value) return;
    if (accelerated.value) {
      if (!ownedProxy.value) {
        error.value = "当前系统代理不是由这里设置的，请在系统设置中关闭";
        return;
      }
      await run(
        "system.restore",
        { id: ownedProxy.value.id },
        "已恢复原来的系统代理",
      );
      await run("accelerator.stop", {}, "");
      if (autoStartedProxy.value) {
        autoStartedProxy.value = false;
        await run("proxy.stop", {}, "");
        await loadProxy();
      }
    } else {
      // user:“加速和代理要不要改成智能进行”+(有订阅时自动拉起线路内核做兜底，但不改系统代理；用户手动操作代理后不再替用户关闭)。
      if (state.value?.proxy?.config_saved && !state.value?.proxy?.running) {
        const fallback = await run("proxy.start", {}, "");
        if (fallback && !fallback.cancelled) {
          autoStartedProxy.value = true;
          await loadProxy();
        }
      }
      const started = await run("accelerator.start", {}, "");
      const port = Number(started?.port || 0);
      if (!port) return;
      const fallbackReady = Boolean(state.value?.proxy?.running);
      const applied = await run(
        "system.apply",
        { kind: "proxy", server: `127.0.0.1:${port}` },
        fallbackReady ? "本机加速已开启，线路兜底已就绪" : "本机加速已开启",
      );
      if (!applied || applied.cancelled) {
        // 系统代理没改成功就不要留下一个空转的加速器；保留失败原因或取消提示。
        const failure = error.value;
        await run("accelerator.stop", {}, "");
        if (autoStartedProxy.value) {
          autoStartedProxy.value = false;
          await run("proxy.stop", {}, "");
          await loadProxy();
        }
        if (failure) error.value = failure;
        else notice.value = "已取消操作";
        await loadSystemProxy();
        await networkStore.refresh();
        return;
      }
    }
    await loadSystemProxy();
    await networkStore.refresh();
  }
  async function setMode(mode) {
    if (!state.value?.proxy?.running) return;
    const result = await run("proxy.mode", { mode }, "连接模式已更新");
    if (result) await loadProxy();
  }
  async function selectNode(group, name) {
    const result = await run(
      "proxy.select",
      { group, name },
      `已切换到 ${name}`,
    );
    if (result) await loadProxy();
  }
  // user:“继续进行网络工具插件的开发”+(自动选择只使用真实测速结果；全部失败时保留当前线路)。
  async function optimizeNode(group) {
    const result = await run("proxy.optimize", { group });
    if (!result) return null;
    if (result.selected) {
      notice.value = `已自动选择 ${result.selected}${
        result.delay ? `（${result.delay} ms）` : ""
      }`;
      await loadProxy();
    } else {
      notice.value = "没有可用线路，已保留当前选择";
    }
    return result;
  }
  async function diagnose(target, kind = "basic") {
    let domain = target.trim();
    try {
      if (domain.includes("://")) domain = new URL(domain).hostname;
    } catch {
      error.value = "请输入正确的网址或域名";
      return null;
    }
    return run("diagnose", { target: domain, port: 443, kind });
  }
  const unsubscribe = networkStore.subscribe({
    rpc: context.rpc,
    signal: context.signal,
    visible: () => context.visible !== false,
    update(value, failure) {
      if (!disposed) {
        state.value = value;
        connectionError.value = failure || "";
      }
    },
  });
  const stopVisibility =
    context.onVisibilityChange?.(() => networkStore.visibilityChanged()) ||
    (() => {});
  watch(
    () => state.value?.proxy?.running,
    () => {
      void loadProxy();
    },
    { immediate: true },
  );
  onMounted(async () => {
    await Promise.all([
      loadSystemProxy(),
      context.compact
        ? Promise.resolve()
        : read("interfaces").then((result) => {
            if (result) interfaces.value = result.interfaces || [];
          }),
    ]);
  });
  onBeforeUnmount(() => {
    disposed = true;
    unsubscribe();
    stopVisibility();
  });
  async function refresh() {
    await Promise.all([networkStore.refresh(), loadSystemProxy(), loadProxy()]);
  }
  return reactive({
    state,
    proxy,
    interfaces,
    tasks,
    systemProxy,
    systemProxyReady,
    accelerated,
    ownedProxy,
    busy,
    error,
    notice,
    connectionError,
    run,
    read,
    refresh,
    loadProxy,
    loadTasks,
    loadSystemProxy,
    toggleProxy,
    toggleAcceleration,
    setMode,
    selectNode,
    optimizeNode,
    diagnose,
  });
}
