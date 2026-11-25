// user:“概览/下载/互联/诊断四个视图 + 设置页收口”+(验收原本点不到的页面现在可达，互联只跳转宿主设备页，下载失败给出具体原因)。
import { afterEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import NetworkApp from "../../src/lamtools_core/plugins/bundled/network-exploration/ui/src/NetworkApp.vue";
const mounted = [];
afterEach(() => {
  for (const view of mounted.splice(0)) view.unmount();
  document.body.replaceChildren();
  sessionStorage.clear();
});
const state = () => ({
  revision: 7,
  settings: { mode: "local", sample_seconds: 5, download: { concurrency: 3, max_tries: 5, bytes_per_second: 0, directory: "" } },
  download_default: "C:\\Users\\me\\Downloads\\Sunday",
  subscriptions: [],
  proxy: { running: false, config_saved: false },
  traffic: { download: 0, upload: 0, received: 0, sent: 0 },
  history: [],
  reports: [],
  events: [{ time: "2026-11-23T01:00:00Z", kind: "transfer", message: "新增下载任务" }],
  downloads: [
    { gid: "bad", filename: "broken.zip", status: "error", errorCode: "3", errorText: "来源服务器返回 404（文件不存在）", totalLength: "0", completedLength: "0" },
  ],
  rules: [],
  transactions: [],
  automations: [],
});
async function setup(overrides = {}, contextExtras = {}) {
  const snapshot = { ...state(), ...overrides };
  const rpc = vi.fn(async (method) => {
    if (method.endsWith(".status")) return snapshot;
    if (method.endsWith(".interfaces"))
      return {
        interfaces: [
          { index: 4, name: "WLAN", ipv4: ["192.168.1.5"], gateway: ["192.168.1.1"], dns: ["1.1.1.1"] },
        ],
      };
    if (method.endsWith(".lan")) return { devices: [{ IPAddress: "192.168.1.9" }] };
    if (method.endsWith(".connections")) return { connections: [], total: 0 };
    if (method.endsWith(".diagnose"))
      return {
        report: {
          id: "n1",
          kind: "network",
          time: "2026-11-23T02:00:00Z",
          target: "network",
          failures: 1,
          checks: [
            { stage: "本机网络", ok: true, evidence: "WLAN 192.168.1.5" },
            { stage: "网关", ok: true, evidence: "192.168.1.1 可达" },
            { stage: "DNS", ok: false, evidence: "系统解析失败" },
            { stage: "外网连接", ok: true, evidence: "1.1.1.1:443 可达" },
            { stage: "代理", ok: true, evidence: "系统代理未启用" },
          ],
          conclusion: { code: "dns_failed", text: "域名解析失败，其它网络看起来正常", suggestion: "可尝试切换 DNS 服务器" },
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
        ...contextExtras,
      },
    },
  });
  mounted.push(view);
  await flushPromises();
  return { view, rpc };
}
async function openSettings(view, section) {
  await view.get("[data-settings]").trigger("click");
  await flushPromises();
  if (section) {
    await view.get(`[data-settings-section="${section}"]`).trigger("click");
    await flushPromises();
  }
}
it("makes every settings section reachable from the gear entry", async () => {
  // user:“代理和高级网络设置置于设置页，不新增大量平级入口”+(六个分区都能打开，不再有写了却点不到的页面)。
  const { view } = await setup();
  await openSettings(view);
  expect(
    view
      .findAll("[data-settings-section]")
      .map((tab) => tab.attributes("data-settings-section")),
  ).toEqual([
    "acceleration",
    "proxy",
    "network",
    "connections",
    "security",
    "advanced",
  ]);
});
it("opens the DNS editor that previously had no entry", async () => {
  // user:“DNS 修改、规则预览、应用联网与连接列表都要能点到”+(原先进不去的网络页现在从设置分区进入)。
  const { view } = await setup();
  await openSettings(view, "network");
  expect(view.text()).toContain("调整 DNS");
  expect(view.text()).toContain("查询网站地址");
});
it("opens application outbound control and the connection list", async () => {
  const { view } = await setup();
  await openSettings(view, "security");
  expect(view.text()).toContain("应用联网");
  await view.get('[data-settings-section="connections"]').trigger("click");
  await flushPromises();
  expect(view.find('input[aria-label="搜索连接"]').exists()).toBe(true);
});
it("asks the host to open the device page instead of duplicating pairing", async () => {
  // user:“「我的设备」只放跳转链接到现有设备连接页”+(插件派发事件，配对与互传仍由宿主设备页负责)。
  const { view } = await setup();
  await view.get('[data-page="devices"]').trigger("click");
  await flushPromises();
  const events = [];
  const listener = (event) => events.push(event.detail);
  window.addEventListener("sunday:open-app-page", listener);
  await view.get("[data-open-device-page]").trigger("click");
  window.removeEventListener("sunday:open-app-page", listener);
  expect(events).toEqual([{ view: "account" }]);
  expect(view.text()).toContain("私人网络");
});
it("shows the concrete reason a download failed", async () => {
  // user:“失败任务显示具体原因及恢复操作”+(不再只说链接可能失效，而是把后台的错误原因显示出来)。
  const { view } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  expect(view.get("[data-task-error]").text()).toContain("404");
});
it("saves global download settings with the current revision", async () => {
  // user:“并发数量、限速、重试策略可设置”+(设置页一次保存全局并发、重试与限速)。
  const { view, rpc } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view.get("[data-download-settings] button").trigger("click");
  await flushPromises();
  const save = view
    .findAll("[data-download-settings] button")
    .find((button) => button.text().includes("保存设置"));
  await save.trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("easynet.settings.update", {
    revision: 7,
    settings: { download: { concurrency: 3, max_tries: 5, bytes_per_second: 0 } },
  });
});
it("checks the whole network from the diagnostics page", async () => {
  // user:“提供一个普通用户可以理解的「检查网络」按钮”+(一次点击覆盖本机、网关、DNS、外网和代理，并给出结论)。
  const { view, rpc } = await setup();
  await view.get('[data-page="diagnose"]').trigger("click");
  await flushPromises();
  await view.get("[data-network-check]").trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("easynet.diagnose", { kind: "network" });
  const result = view.get("[data-network-result]").text();
  expect(result).toContain("域名解析失败");
  expect(result).toContain("切换 DNS");
});
it("leads from the overview to diagnostics and to devices", async () => {
  const { view } = await setup();
  await view.get("[data-home-diagnose]").trigger("click");
  await flushPromises();
  expect(view.get('[data-page="diagnose"]').attributes("aria-current")).toBe("page");
  await view.get('[data-page="overview"]').trigger("click");
  await flushPromises();
  await view.get('[data-home-open="devices"]').trigger("click");
  await flushPromises();
  expect(view.get('[data-page="devices"]').attributes("aria-current")).toBe("page");
});
it("summarises the live connection on the overview", async () => {
  // user:“当前网络类型和实际连接状态”+(概览直接给出连接方式、本机地址与最近事件)。
  const { view } = await setup();
  const strip = view.get("[data-network-strip]").text();
  expect(strip).toContain("WLAN");
  expect(strip).toContain("192.168.1.5");
  expect(view.text()).toContain("已连接");
  // 最近事件不再堆在概览首屏，检查结果只给一句结论。
  expect(view.text()).toContain("还没检查过");
});

it("starts the proxy right after a subscription is saved", async () => {
  // user:“导入订阅之后会不会直接显示节点”+(保存后直接拉起代理，节点列表立刻出现)。
  const { view, rpc } = await setup({ proxy: { running: false, config_saved: false } });
  await openSettings(view, "proxy");
  await view
    .findAll("button")
    .find((button) => button.text().includes("添加订阅"))
    .trigger("click");
  await flushPromises();
  await view.get('input[aria-label="订阅链接"]').setValue("https://sub.example.com/clash.yaml");
  await view.get("[data-profile-import] form").trigger("submit");
  await flushPromises();
  const methods = rpc.mock.calls.map(([method]) => method);
  expect(methods).toContain("easynet.proxy.config");
  expect(methods).toContain("easynet.proxy.start");
  expect(methods.indexOf("easynet.proxy.start")).toBeGreaterThan(methods.indexOf("easynet.proxy.config"));
});

it("shows the default download folder and saves a new one", async () => {
  // user:“会不会不知道下载的文件默认在哪里”“知不知道怎么修改下载默认位置”+(默认路径直接写出来，可改)。
  const { view, rpc } = await setup();
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  // user:“目录这种属于是必要信息吧 为什么要藏起来”+(默认目录直接显示，点「更改」才出现输入框)。
  const hint = view.get("[data-download-default]").text();
  expect(hint).toContain("Sunday");
  await view.get("[data-change-directory]").trigger("click");
  await flushPromises();
  await view.get("[data-download-directory]").setValue("D:\\Downloads\\EasyNet");
  const save = view
    .findAll(".nx2-dir-editor button")
    .find((button) => button.text().includes("保存"));
  await save.trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("easynet.settings.update", {
    revision: 7,
    settings: { download: { directory: "D:\\Downloads\\EasyNet" } },
  });
});

it("switches between saved subscriptions", async () => {
  // user:“怎么切换订阅”+(列表里直接切，切换会重新拉取并重连)。
  const { view, rpc } = await setup({
    proxy: { running: true, config_saved: true },
    subscriptions: [
      { id: "aaa", host: "sub.example.com", saved_at: "2026-11-20T10:00:00Z", active: true },
      { id: "bbb", host: "backup.example.com", saved_at: "2026-11-21T11:00:00Z", active: false },
    ],
  });
  await openSettings(view, "proxy");
  expect(view.get("[data-active-subscription]").text()).toContain("sub.example.com");
  await view.get("[data-toggle-subscriptions]").trigger("click");
  await flushPromises();
  const row = view.get('[data-subscription="bbb"]');
  await row
    .findAll("button")
    .find((button) => button.text().includes("切换"))
    .trigger("click");
  await flushPromises();
  expect(rpc).toHaveBeenCalledWith("easynet.proxy.subscriptions", { action: "activate", id: "bbb" });
});

it("opens a finished download on double click", async () => {
  // user:“能不能直接双击打开已下载文件路径”+(完成的任务行双击即打开，不必先展开再点按钮)。
  const openFile = vi.fn();
  const { view } = await setup(
    {
      downloads: [
        {
          gid: "done", filename: "movie.mkv", status: "complete", directory: "D:\\Downloads",
          totalLength: "100", completedLength: "100",
        },
      ],
    },
    { openFile },
  );
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view
    .findAll(".nx-filter-tabs button")
    .find((button) => button.text().includes("已完成"))
    .trigger("click");
  await flushPromises();
  await view.get('[data-task="done"]').trigger("dblclick");
  await flushPromises();
  expect(openFile).toHaveBeenCalledWith("D:\\Downloads\\movie.mkv");
});

it("picks the download folder with the system dialog", async () => {
  // user:“下载路径连个浏览都没有吗？”+(点「浏览…」走系统目录选择器，选完直接填进输入框)。
  const pickDirectory = vi.fn(async () => "E:\Downloads\Picked");
  const { view } = await setup({}, { pickDirectory });
  await view.get('[data-page="transfer"]').trigger("click");
  await flushPromises();
  await view.get("[data-change-directory]").trigger("click");
  await flushPromises();
  await view.get("[data-browse-directory]").trigger("click");
  await flushPromises();
  expect(pickDirectory).toHaveBeenCalledTimes(1);
  expect(view.get("[data-download-directory]").element.value).toBe("E:\Downloads\Picked");
});
