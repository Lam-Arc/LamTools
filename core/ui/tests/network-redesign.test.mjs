// user:“可交互式网络工具界面，不需要太专业”+(常用操作直接可用，专业参数收起，真实状态以图表和列表呈现)。
import { afterEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import NetworkApp from "../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkApp.vue";
import QuickPanel from "../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/QuickPanel.vue";
import { networkStore } from "../../src/lamtools_core/plugins/bundled/network-exploration/ui/store.mjs";
import {
  filenameFromUrl,
  uptime,
} from "../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/session.mjs";
const mounted = [];
afterEach(() => {
  for (const view of mounted.splice(0)) view.unmount();
  vi.useRealTimers();
  document.body.replaceChildren();
  sessionStorage.clear();
});
const state = () => ({
  revision: 4,
  controller_pid: 45678,
  settings: { mode: "local", sample_seconds: 5 },
  proxy: { running: true, config_saved: true },
  traffic: {
    download: 2097152,
    upload: 1048576,
    received: 10000000,
    sent: 5000000,
  },
  history: [
    { download: 1024, upload: 512 },
    { download: 2048, upload: 1024 },
  ],
  reports: [],
  events: [],
  downloads: [{ gid: "abc", filename: "project.zip", status: "active" }],
  rules: [],
  transactions: [],
  automations: [],
});
async function setup(overrides = {}) {
  const snapshot = { ...state(), ...overrides };
  const rpc = vi.fn(async (method) => {
    if (method.endsWith(".status")) return snapshot;
    if (method.endsWith(".interfaces"))
      return {
        interfaces: [
          {
            index: 4,
            name: "Ethernet",
            ipv4: ["192.168.1.5"],
            dns: ["1.1.1.1"],
          },
        ],
      };
    if (method.endsWith(".proxy.inspect"))
      return {
        mode: "rule",
        proxies: {
          Auto: { type: "Selector", now: "Tokyo", all: ["Tokyo", "Singapore"] },
          Tokyo: { type: "Shadowsocks", history: [{ delay: 26 }] },
          Singapore: { type: "Shadowsocks", history: [{ delay: 58 }] },
        },
      };
    if (method.endsWith(".transfer.list"))
      return {
        tasks: [
          {
            gid: "abc",
            status: "active",
            totalLength: "1000",
            completedLength: "500",
            downloadSpeed: "100",
          },
        ],
      };
    if (method.endsWith(".accelerator.start"))
      return { running: true, port: 49152 };
    if (method.endsWith(".diagnose"))
      return {
        report: {
          id: "new",
          target: "github.com",
          failures: 0,
          checks: [
            { stage: "DNS", ok: true, ms: 12 },
            { stage: "TCP", ok: true, ms: 20 },
            { stage: "TLS / HTTP", ok: true, status: 200, ms: 48 },
          ],
        },
      };
    return {};
  });
  const view = mount(NetworkApp, {
    props: {
      context: {
        rpc,
        visible: true,
        signal: new AbortController().signal,
        onVisibilityChange: () => () => {},
      },
    },
  });
  mounted.push(view);
  await flushPromises();
  return { view, rpc };
}
it("renders one stat bar and three quick action blocks without raw state", async () => {
  // user:“首页重做，放三个块和一个 bar，bar 写数值，三个块分别是加速代理下载的快捷操作”+(首页只保留数值条和三个快捷块)。
  const { view } = await setup();
  expect(view.find("[data-stat-bar]").exists()).toBe(true);
  expect(
    view
      .findAll("[data-home-block]")
      .map((block) => block.attributes("data-home-block")),
  ).toEqual(["acceleration", "proxy", "transfer"]);
  expect(view.text()).toContain("2.0 MB/s");
  expect(view.text()).toContain("1.0 MB/s");
  expect(view.text()).toContain("1 个任务");
  expect(view.text()).not.toContain("45678");
  expect(view.find("textarea").exists()).toBe(false);
  expect(view.find("pre").exists()).toBe(false);
});
it("writes live numeric values into the home stat bar", async () => {
  const { view } = await setup();
  await flushPromises();
  expect(view.get("[data-stat='download']").text()).toContain("2.0 MB/s");
  expect(view.get("[data-stat='upload']").text()).toContain("1.0 MB/s");
  expect(view.get("[data-stat='total']").text()).toContain("14.3 MB");
  expect(view.get("[data-stat='delay']").text()).toContain("26 ms");
});
it("keeps exactly home, acceleration, proxy, and downloads in the left navigation", async () => {
  // user:“左侧分为 4 个：首页、加速、代理和下载”+(只保留这四个入口)。
  const { view } = await setup();
  expect(
    view.findAll("[data-page]").map((button) => button.attributes("data-page")),
  ).toEqual(["home", "overview", "proxy", "transfer"]);
  expect(view.text()).toContain("首页");
  expect(view.text()).toContain("加速");
  expect(view.text()).toContain("代理");
  expect(view.text()).toContain("下载");
});
it("navigates from the home block links", async () => {
  const { view } = await setup();
  await view.get('[data-home-open="proxy"]').trigger("click");
  await flushPromises();
  expect(view.get('[data-page="proxy"]').attributes("aria-current")).toBe(
    "page",
  );
});
it("saves a subscription while connected by reconnecting automatically", async () => {
  // user:“添加不了订阅”“把操作傻瓜化”+(保存时自动断开并重连，不要求用户先手动关闭代理)。
  const { view, rpc } = await setup();
  await view.get('[data-page="proxy"]').trigger("click");
  await flushPromises();
  const add = view
    .findAll("button")
    .find((button) => button.text().includes("更新订阅"));
  await add.trigger("click");
  await flushPromises();
  await view
    .get('input[aria-label="订阅链接"]')
    .setValue("https://example.com/sub");
  await view.get("[data-profile-import] form").trigger("submit");
  await flushPromises();
  const methods = rpc.mock.calls.map(([method]) => method);
  expect(methods).toContain("network-exploration.proxy.stop");
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.config", {
    subscription: "https://example.com/sub",
  });
  expect(methods).toContain("network-exploration.proxy.start");
  expect(view.text()).toContain("订阅已更新，线路已重新连接");
});
it("selects real nodes from a list without asking the user for group names", async () => {
  const { view, rpc } = await setup();
  await view.get('[data-page="proxy"]').trigger("click");
  await flushPromises();
  await view.get('[data-node="Singapore"]').trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.select", {
    group: "Auto",
    name: "Singapore",
  });
  expect(view.find('input[name="group"]').exists()).toBe(false);
});
it("measures a line group and switches to the fastest reachable node", async () => {
  // user:“继续进行网络工具插件的开发”+(线路页一键测速并选择最快可达线路，不要求用户逐条点刷新)。
  const { view, rpc } = await setup();
  const original = rpc.getMockImplementation();
  rpc.mockImplementation(async (method, params) =>
    method.endsWith(".proxy.optimize")
      ? {
          group: params.group,
          selected: "Tokyo",
          delay: 26,
          tested: 2,
          candidates: [
            { name: "Tokyo", delay: 26 },
            { name: "Singapore", delay: 58 },
          ],
          changes_system: false,
        }
      : original(method, params),
  );
  await view.get('[data-page="proxy"]').trigger("click");
  await flushPromises();
  await view.get("[data-optimize]").trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.optimize", {
    group: "Auto",
  });
  expect(view.text()).toContain("已自动选择 Tokyo");
  expect(view.text()).toContain("26 ms");
});
it("keeps the current line when no measured node is reachable", async () => {
  const { view, rpc } = await setup();
  const original = rpc.getMockImplementation();
  rpc.mockImplementation(async (method, params) =>
    method.endsWith(".proxy.optimize")
      ? {
          group: params.group,
          selected: null,
          tested: 2,
          candidates: [
            { name: "Tokyo", error: "超时" },
            { name: "Singapore", error: "超时" },
          ],
          changes_system: false,
        }
      : original(method, params),
  );
  await view.get('[data-page="proxy"]').trigger("click");
  await flushPromises();
  await view.get("[data-optimize]").trigger("click");
  await flushPromises();
  expect(view.text()).toContain("没有可用线路，已保留当前选择");
  expect(
    rpc.mock.calls.filter(([method]) => method.endsWith(".proxy.select")),
  ).toHaveLength(0);
});
it("starts a download with the chosen parallel count and speed limit", async () => {
  // user:“旁边就是配置项，比如并行数量、下载限速”+(开始下载时一并提交，不需要二次设置)。
  const { view, rpc } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view
    .get('input[name="url"]')
    .setValue("https://example.com/file.zip");
  await view.get('select[aria-label="并行数量"]').setValue("4");
  await view.get('select[aria-label="下载限速"]').setValue("5242880");
  await view.get(".nx-download-composer").trigger("submit");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith(
    "network-exploration.transfer.add",
    expect.objectContaining({
      url: "https://example.com/file.zip",
      connections: 4,
      bytes_per_second: 5242880,
    }),
  );
});
it("accepts a link dropped into the download box", async () => {
  // user:“通过一个链接或者拖拽放进来之后，点‘开始下载’”+(拖入链接直接填入，不要求先点新建)。
  const { view } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view.get("[data-download-drop]").trigger("drop", {
    dataTransfer: {
      getData: (type) =>
        type === "text/plain" ? "https://example.com/dropped.zip" : "",
    },
  });
  await flushPromises();
  expect(view.get('input[name="url"]').element.value).toBe(
    "https://example.com/dropped.zip",
  );
});
it("pauses a download directly from its row", async () => {
  const { view, rpc } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view.get('[data-task-action="pause"]').trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.transfer.action", {
    gid: "abc",
    action: "pause",
  });
  expect(view.text()).toContain("project.zip");
});
it("turns a web address into a readable diagnostic result", async () => {
  const { view, rpc } = await setup();
  await view.get('[data-page="overview"]').trigger("click");
  await flushPromises();
  await view
    .get('input[aria-label="要检查的网站"]')
    .setValue("https://github.com/");
  await view.get(".nx-site-check form").trigger("submit");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith(
    "network-exploration.diagnose",
    expect.objectContaining({ target: "github.com" }),
  );
  expect(view.text()).toContain("检查通过");
  expect(view.find("pre").exists()).toBe(false);
});
it("only enables the proxy switch after a subscription is saved", async () => {
  // user:“代理的功能挺简单的”+(没有订阅时不给一个点了必然失败的开关)。
  const { view } = await setup({
    proxy: { running: false, config_saved: false },
  });
  await view.get('[data-page="proxy"]').trigger("click");
  await flushPromises();
  expect(view.get("[data-proxy-switch]").attributes("disabled")).toBeDefined();
});
it("toggles the proxy directly from the home block", async () => {
  // user:“三个块分别是加速代理下载的快捷操作”+(代理块直接开关连接，不要求先跳到代理页)。
  const { view, rpc } = await setup();
  await view.get("[data-home-proxy]").trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.stop", {});
  expect(view.get('[data-page="home"]').attributes("aria-current")).toBe("page");
});
it("sends a home proxy block without a subscription to the proxy page", async () => {
  const { view, rpc } = await setup({
    proxy: { running: false, config_saved: false },
  });
  await view.get("[data-home-proxy]").trigger("click");
  await flushPromises();
  expect(view.get('[data-page="proxy"]').attributes("aria-current")).toBe(
    "page",
  );
  expect(rpc.mock.calls.map(([method]) => method)).not.toContain(
    "network-exploration.proxy.start",
  );
});
it("starts a download from the home block with a filename derived from the link", async () => {
  // user:“三个块分别是加速代理下载的快捷操作”+(下载块粘贴链接即可开始，不要求先打开下载页)。
  const { view, rpc } = await setup();
  await view
    .get('[data-home-download] input')
    .setValue("https://example.com/files/My%20Mod.zip?download=1");
  await view.get("[data-home-download]").trigger("submit");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith(
    "network-exploration.transfer.add",
    expect.objectContaining({
      url: "https://example.com/files/My%20Mod.zip?download=1",
      filename: "My Mod.zip",
      connections: 8,
    }),
  );
  expect(view.get('[data-home-download] input').element.value).toBe("");
});
it("starts local acceleration from the home page without a subscription", async () => {
  // user:“就像是用 watt toolkit 一样，点一下‘一键加速’”“本机加速的意思就是本机加速选线路的事儿，去代理里面”+(首页一键加速只启动本机加速器，不要求订阅，也不跳走)。
  const { view, rpc } = await setup({
    proxy: { running: false, config_saved: false },
  });
  await view.get("[data-acceleration]").trigger("click");
  await flushPromises();
  expect(view.get('[data-page="home"]').attributes("aria-current")).toBe("page");
  expect(rpc).toHaveBeenCalledWith(
    "network-exploration.accelerator.start",
    {},
  );
  expect(rpc).toHaveBeenCalledWith("network-exploration.system.apply", {
    kind: "proxy",
    server: "127.0.0.1:49152",
  });
  expect(rpc.mock.calls.map(([method]) => method)).not.toContain(
    "network-exploration.proxy.start",
  );
});
it("prepares the line fallback when acceleration starts with a subscription", async () => {
  // user:“加速和代理要不要改成智能进行”+(有订阅时自动拉起线路内核做兜底，但不改系统代理)。
  const { view, rpc } = await setup({
    proxy: { running: false, config_saved: true },
  });
  await view.get("[data-acceleration]").trigger("click");
  await flushPromises();
  const methods = rpc.mock.calls.map(([method]) => method);
  expect(methods).toContain("network-exploration.proxy.start");
  expect(methods.indexOf("network-exploration.proxy.start")).toBeLessThan(
    methods.indexOf("network-exploration.accelerator.start"),
  );
  expect(rpc).toHaveBeenCalledWith("network-exploration.system.apply", {
    kind: "proxy",
    server: "127.0.0.1:49152",
  });
});
it("runs local acceleration from the acceleration page without a subscription", async () => {
  // user:“本机加速层 你学习一下呗…它该抄就抄”+(加速页只做本机加速，不需要订阅，也没有线路模式切换)。
  const { view, rpc } = await setup({
    proxy: { running: false, config_saved: false },
  });
  await view.get('[data-page="overview"]').trigger("click");
  await flushPromises();
  expect(view.find("[data-acceleration-mode]").exists()).toBe(false);
  expect(view.find("[data-line-select]").exists()).toBe(false);
  await view.get("[data-acceleration]").trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith(
    "network-exploration.accelerator.start",
    {},
  );
  expect(rpc).toHaveBeenCalledWith("network-exploration.system.apply", {
    kind: "proxy",
    server: "127.0.0.1:49152",
  });
});
it("keeps line switching on the proxy page instead of the acceleration page", async () => {
  // user:“加速页里头不用分什么线路加速，本机加速的意思就是本机加速选线路的事儿，去代理里面”+(加速页不再选线路，线路选择只在代理页)。
  const { view, rpc } = await setup();
  expect(view.get('[data-page="home"]').attributes("aria-current")).toBe("page");
  expect(view.text()).toContain("一键加速");
  await view.get("[data-acceleration]").trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.system.apply", {
    kind: "proxy",
    server: "127.0.0.1:49152",
  });
  await view.get('[data-page="overview"]').trigger("click");
  await flushPromises();
  expect(view.text()).toContain("去代理页管理");
  expect(view.find("[data-node]").exists()).toBe(false);
  expect(view.find("[data-line-select]").exists()).toBe(false);
  await view.get('[data-page="proxy"]').trigger("click");
  await flushPromises();
  await view.get('[data-node="Singapore"]').trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.select", {
    group: "Auto",
    name: "Singapore",
  });
});
it("derives a safe filename for quick downloads", () => {
  // user:“三个块分别是加速代理下载的快捷操作”+(下载块只让用户粘贴链接，文件名从链接里推导并清理非法字符)。
  expect(
    filenameFromUrl("https://example.com/files/My%20Mod.zip?download=1"),
  ).toBe("My Mod.zip");
  expect(filenameFromUrl("https://example.com/")).toBe("download.bin");
  expect(filenameFromUrl("https://example.com/a%3Ab%3F.zip")).toBe(
    "a_b_.zip",
  );
  expect(filenameFromUrl("not a url")).toBe("");
});
it("formats the real proxy uptime for the home page", () => {
  // user:“样式示例：不必照抄，只是方向”+(连接时长来自控制器启动时刻，不是伪造的计时)。
  const now = Date.parse("2026-10-25T12:00:00Z");
  expect(uptime("2026-10-25T10:58:59Z", now)).toBe("01:01:01");
  expect(uptime("", now)).toBe("");
  expect(uptime("not-a-date", now)).toBe("");
});
it("keeps an unfinished download link when background statistics refresh", async () => {
  const { view, rpc } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view
    .get('input[name="url"]')
    .setValue("https://example.com/my-file.zip");
  rpc.mockImplementationOnce(async () => ({
    ...state(),
    traffic: { download: 4096, upload: 0 },
  }));
  await networkStore.refresh();
  await flushPromises();
  expect(view.get('input[name="url"]').element.value).toBe(
    "https://example.com/my-file.zip",
  );
});
it("does not claim acceleration is on when the user cancels the system change", async () => {
  const { view, rpc } = await setup();
  const original = rpc.getMockImplementation();
  rpc.mockImplementation(async (method, params) =>
    method.endsWith(".system.apply")
      ? { cancelled: true }
      : original(method, params),
  );
  await view.get("[data-acceleration]").trigger("click");
  await flushPromises();
  expect(view.get("[data-acceleration]").attributes("aria-pressed")).toBe(
    "false",
  );
  expect(view.text()).toContain("已取消操作");
});
it("opens the page requested by a quick pill", async () => {
  // user:“右侧栏…三行 3 个胶囊…易交互”+(侧栏胶囊可以直接落到下载页，不用先开首页再点导航)。
  sessionStorage.setItem("network-exploration:page", "transfer");
  const { view } = await setup();
  expect(view.get('[data-page="transfer"]').attributes("aria-current")).toBe(
    "page",
  );
  expect(sessionStorage.getItem("network-exploration:page")).toBeNull();
});
it("renders three quick pills with direct actions", async () => {
  const rpc = vi.fn(async (method) => {
    if (method.endsWith(".status")) return state();
    if (method.endsWith(".system.inspect")) return { enabled: 0, server: "" };
    if (method.endsWith(".proxy.inspect"))
      return {
        mode: "rule",
        proxies: {
          Auto: {
            type: "Selector",
            now: "Tokyo",
            all: ["Tokyo", "Singapore"],
          },
          Tokyo: { type: "Shadowsocks", history: [{ delay: 26 }] },
          Singapore: { type: "Shadowsocks", history: [{ delay: 58 }] },
        },
      };
    if (method.endsWith(".accelerator.start"))
      return { running: true, port: 49152 };
    return {};
  });
  const view = mount(QuickPanel, {
    props: {
      context: {
        rpc,
        visible: true,
        signal: new AbortController().signal,
        onVisibilityChange: () => () => {},
      },
    },
  });
  mounted.push(view);
  await flushPromises();
  expect(
    view.findAll("[data-quick]").map((pill) => pill.attributes("data-quick")),
  ).toEqual(["acceleration", "proxy", "download"]);
  await view.get('[data-quick-action="acceleration"]').trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.system.apply", {
    kind: "proxy",
    server: "127.0.0.1:49152",
  });
  await view.get('[data-quick="proxy"] select').setValue("Singapore");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.select", {
    group: "Auto",
    name: "Singapore",
  });
  await view.get('[data-quick-action="proxy"]').trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("network-exploration.proxy.stop", {});
  await view
    .get('[data-quick="download"] input')
    .setValue("https://example.com/file.zip");
  await view.get('[data-quick="download"] form').trigger("submit");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith(
    "network-exploration.transfer.add",
    expect.objectContaining({
      url: "https://example.com/file.zip",
      filename: "file.zip",
      connections: 8,
    }),
  );
});
it("opens the proxy page when the quick proxy has no subscription", async () => {
  const rpc = vi.fn(async (method) => {
    if (method.endsWith(".status"))
      return { ...state(), proxy: { running: false, config_saved: false } };
    if (method.endsWith(".system.inspect")) return { enabled: 0, server: "" };
    return {};
  });
  const view = mount(QuickPanel, {
    props: {
      context: {
        rpc,
        visible: true,
        signal: new AbortController().signal,
        onVisibilityChange: () => () => {},
      },
    },
  });
  mounted.push(view);
  await flushPromises();
  const opened = vi.fn();
  window.addEventListener("sunday:open-plugin-page", opened);
  await view.get('[data-quick-action="proxy"]').trigger("click");
  expect(opened).toHaveBeenCalled();
  expect(sessionStorage.getItem("network-exploration:page")).toBe("proxy");
  window.removeEventListener("sunday:open-plugin-page", opened);
});
it("stops quick-panel polling when the window becomes hidden", async () => {
  vi.useFakeTimers();
  let visible = true;
  const listeners = new Set();
  const rpc = vi.fn(async (method) =>
    method.endsWith(".status") ? state() : {},
  );
  const context = {
    rpc,
    get visible() {
      return visible;
    },
    signal: new AbortController().signal,
    onVisibilityChange(callback) {
      listeners.add(callback);
      return () => listeners.delete(callback);
    },
  };
  const view = mount(QuickPanel, { props: { context } });
  mounted.push(view);
  await flushPromises();
  const before = rpc.mock.calls.filter(([method]) =>
    method.endsWith(".status"),
  ).length;
  visible = false;
  for (const listener of listeners) listener(false);
  await vi.advanceTimersByTimeAsync(15000);
  expect(
    rpc.mock.calls.filter(([method]) => method.endsWith(".status")).length,
  ).toBe(before);
});
