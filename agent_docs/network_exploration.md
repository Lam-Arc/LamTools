# 网络拓展插件开发记录

<!-- user:“实现这个插件，也正好实验我们的新插件架构”+(保留架构试验结果和可重现验收命令)。 -->

插件源目录：`core/src/lamtools_core/plugins/bundled/network-exploration`。功能、接口、构建和明确的未完成范围以该目录的 `README.md` 为准。

本轮新架构验证补齐了四项宿主能力：

1. 插件操作的后台审批。声明 `permission: ask_user` / `hard_block` 后，后台先检查宿主权限再加载执行处理器；一次性确认绑定服务器捕获的参数、插件版本与账本状态。
2. `ui.pages[].navigation: true`。同一页面可以进入左竖栏主界面与分屏，无需为每个插件增加宿主专用分支。
3. 自绘配置面板获得 `rpc`、`signal`，并可返回清理函数或异步清理函数；多面板等待同一脚本加载。
4. 卸载前停止插件后台。清理失败不继续删除源目录。

Rust 控制器通过宿主插件后端的私有标准输入/输出通道服务请求，没有公开新的无认证网络管理端口。Python 只负责宿主衔接、资源准备和 Windows Job 生命周期。三个页面入口不拥有下载或代理进程。

本次只运行新增相关测试：

```powershell
$env:PYTHONPATH='E:\LamTools\core\src'
python -m pytest core/tests/test_plugin_operation_consent.py core/tests/test_network_exploration.py core/tests/test_network_live_rpc.py -q
cargo test --locked --manifest-path core/src/lamtools_core/plugins/bundled/network-exploration/controller/Cargo.toml --target-dir E:/LamTools/.build/network-controller
```

在 `core/ui`：

```text
npx vitest run tests/plugin-operation-consent.test.ts tests/plugin-config-lifecycle.test.ts tests/network-plugin-surfaces.test.ts tests/network-plugin-ui.test.mjs
npx vue-tsc --noEmit
```

没有使用 Computer Use，没有修改开发机全局网络配置，没有重启用户正在使用的 Sunday。已经启动隔离测试宿主，通过其真实 WebSocket、资源接口和插件装配检查运行行为。用户当前应用需要完整重启才能装配新的声明和处理器。

## 0.2.1 首页与自动选线（2026-10-25）

<!-- user:“样式示例：不必照抄，只是方向”“常用功能放在首页 切梯子/网络加速”+(首页按参考方向重排，并提供基于真实延迟的自动选线)。 -->

- 首页改为卡片工作台：实时网速、系统代理开关、出站模式、当前线路、流量统计环、本机网络、网站检查与最近活动。线路卡片显示真实节点名称、最近延迟和控制器记录的连接时长。
- 新增 `network-exploration.proxy.optimize`。它只读取一个 Selector 分组，过滤 `DIRECT`、`REJECT` 等内置目标，并发 12 路测量真实节点延迟，按最低延迟切换；全部失败时保留当前线路并返回 `selected:null`，不修改系统代理。
- “最快”只表示本次延迟最低，不是带宽测速。控制器的 `started_at` 是首页连接时长的唯一来源。

本轮相关测试：

```text
core/ui: npx vitest run tests/network-redesign.test.mjs tests/network-plugin-ui.test.mjs tests/network-plugin-surfaces.test.ts
controller: cargo test --locked --manifest-path core/src/lamtools_core/plugins/bundled/network-exploration/controller/Cargo.toml --target-dir E:/LamTools/.build/network-controller
```

## 0.2.2 一键加速与极简入口（2026-10-25）

<!-- user:“点一下‘一键加速’，然后就把 GitHub等常用的那些网站全部都加速了”“标准就是脑残来都会用”+(收敛入口、内置常用站点规则、订阅保存后自动重连)。 -->

- 插件页面把 `style.css?inline` 打进自己的 `page.mjs`，挂载时注入实际文档，不再依赖宿主在某个特定文档里注入样式；实测页面已恢复深色卡片布局。
- 插件接管主区时给 `.workspace-main` 加 `nx-plugin-full`，隐藏宿主整版标题条、插件工具栏和内边距；退出时移除。
- 删除多余的 `appRail` 无入口区域声明。它就是标题栏里 “network-exploration” 覆盖 “Sunday” 的来源；左侧插件入口由 `ui.pages[].navigation` 提供，不需要空区域。
- 左侧导航只保留“加速 / 代理 / 下载”。代理页收敛为订阅、节点分组、测速、选节点；下载页改为链接/拖拽 + 开始下载 + 并行数/限速 + 进度。
- 首页“网络加速”改为一个“一键加速/停止加速”按钮。没有订阅时按钮直接打开订阅面板；保存订阅时自动断开旧连接，保存后自动重连并开启加速。
- 订阅下载优先使用 Windows 系统代理（跳过插件自己的 `127.0.0.1:17890`），系统代理 55 秒超时，失败再直连 75 秒。真实测试 `https://sub.serverpulse.me/clash.yaml`（17 KB）用旧逻辑 8 秒超时，新逻辑 5.5 秒保存成功；随后插件代理访问 GitHub 与 api.github.com 均返回 200。
- 修复 `proxy.select`、`proxy.delay`、`delay_probe` 的路径拼接：基址 `/proxies/` 再加路径段会变成 `/proxies//名字`，Mihomo 返回 404。改为无尾斜杠基址，并加回归测试；真实订阅上选择节点返回 `{"ok":true}`，节点测速返回 223–535 ms。
- 恢复系统代理前检查旧的本机代理端口；端口已关闭时不再把死端口写回，而是关闭系统代理。这样 FlClash 关闭后，插件恢复时不会再把 `127.0.0.1:7890` 留在系统设置里。
- 控制器在 `start_proxy` 前把 GitHub、Steam、Twitch、Spotify、Google、HuggingFace、网盘、游戏站点等内置规则插到订阅规则之前，目标选第一个可用 Selector 分组。`proxy_status` 新增 `config_saved`，首页据此决定先显示“添加订阅”还是“开启代理”。
- 自动选线、连接时长、删除 `.old` 控制器文件的构建处理保留。

本轮验收：

```text
core/ui: npx vitest run tests/network-redesign.test.mjs tests/network-plugin-ui.test.mjs tests/network-plugin-surfaces.test.ts
controller: cargo test --locked --manifest-path core/src/lamtools_core/plugins/bundled/network-exploration/controller/Cargo.toml --target-dir E:/LamTools/.build/network-controller
```

真实订阅导入与 GitHub 实际连通未在本机验证，因为没有提供可用订阅；规则注入和保存/重连流程由单元测试覆盖。

## 0.2.3 四页界面与本机加速（2026-10-25）

<!-- user:“这整个设计由你重设计”“本机加速层 你学习一下呗…它该抄就抄”+(四个入口重做，并按 FastGithub/Watt Toolkit 的思路实现本地 CONNECT + DoH 选路)。 -->

- 左侧固定为首页 / 加速 / 代理 / 下载；首页是总览台，加速页只开关本机加速，代理页是订阅→连接→分组→测速→选节点，下载页是链接/拖拽→开始→并行数/限速→进度。
- Watt Toolkit 的 GitHub 处理者继承自 `TcpReverseProxyHandler`，注释指向 FastGithub 2.1.4。它的系统代理模式是：本地 HTTP 代理接 CONNECT，命中域名用 DoH 解析 A 记录，直连候选 IP，TLS 原样透传；不需要证书。Hosts/DNSIntercept/PAC 是另外的透明模式。
- 新增 `controller/src/accelerator.rs`：域名精确/子域名匹配、CONNECT/IPv6 解析、多 DoH 并发、候选 IP 并发直连（4 秒）、非命中域名交给 Mihomo 17890 或系统解析。监听 `127.0.0.1` 临时端口，`accelerator.start/stop` 暴露端口，`status` 带 accelerator 状态。
- `system.apply` 现在接受任意 `127.0.0.1:<port>`，所以本机加速可以把系统代理指向临时端口；本机加速不需要订阅。停止时恢复原系统代理，旧端口已死则关闭系统代理。
- 真实测试：通过本地加速器请求 GitHub 下载了 566 KB；`example.com` 非命中路径返回 200。UI 24 个测试、控制器 24 个测试、Python 4 个测试通过。
- 仍未实现：Hosts/DNS 拦截/PAC/透明模式、Git/SSH 独立端口、证书 MITM、外部 Watt Toolkit 进程接入；网络层直接阻断目标 IP/SNI 时本机加速仍会失败。

## 0.2.4 加速页只做本机加速与真实站点复测（2026-10-26）

<!-- user:“加速页里头不用分什么线路加速，本机加速的意思就是本机加速选线路的事儿，去代理里面”+(加速页去掉线路/本机模式切换；订阅和选线路只在代理页) -->
<!-- user:“那你试了吗？能连上吗？比如 mod n 网”+(用真实模组站验证，不用单元测试代替连通性) -->

- 加速页与首页的一键加速都只调用 `accelerator.start` + `system.apply`，不再提供线路模式选择；线路、订阅和测速保留在代理页。取消系统代理授权时会同时停掉已启动的加速器，不留下空转进程。
- 实测当前网络拦截 Cloudflare/Google DoH；解析器改为阿里 223.5.5.5、DNSPod、Cloudflare、Google 并发查询，并过滤路由器伪造的 `127.0.0.1`、`0.0.0.0`、组播和链路本地地址。
- 新增 TLS 首包回退：被污染的域名常常 TCP 能连、TLS 首包被重置。加速器在 2 秒内收不到上游首包就改走已开启的 Mihomo 线路，避免“本机加速反而让线路失效”。常用域名加速失败也会继续走线路/系统解析，不再直接 502。
- 真实结果（本机 2026-10-26）：Modrinth 与本机加速均 200；`files.nexus-cdn.com` 经加速器 302；`mod.io` 直连失败、经线路回退后 200；GitHub 当前直连被阻断、经线路回退后 200；NexusMods（N 网）能建立连接，但 Cloudflare 风控间歇返回 403 人机验证，直连和换线路都一样，属于站点侧限制而不是连接失败。
- 本机加速不是 VPN，不能承诺绕过 IP/SNI 阻断或 Cloudflare 人机验证；这类站点需要在代理页选一条可用线路。
- `system.apply` 与 `system.restore` 在桌面端改为 `auto_allow`，用户不再逐次看到“修改或恢复所选网络配置”的审批。只放开这两项系统代理操作；DNS、防火墙、QoS 等其他系统修改仍按原逻辑审批。实际运行中用一个无效 kind 调用验证：请求进入执行层并返回“此系统操作尚不支持”，没有出现审批取消，也没有改动系统配置。

## 0.2.5 首页改为数值条与三个快捷块（2026-10-26）

<!-- user:“首页重做，放三个块和一个 bar，bar 写数值，三个块分别是加速代理下载的快捷操作，信息密度适宜，操作便捷直觉” -->

- 首页移除大 Hero、圆环、三行入口和最近活动，只保留一条数值 bar 与三个快捷块。
- bar 显示实时下载、实时上传、累计流量和当前线路延迟；代理未连接时延迟显示“—”。
- 加速块直接开关本机加速；代理块有订阅时直接开关连接、没有订阅时跳到代理页；下载块可直接粘贴链接开始下载，自动从 URL 推导并清理文件名，默认 8 连接。
- 新增 `filenameFromUrl()`，下载页与首页共用，避免两套文件名推导逻辑。
- 窄容器下三块改为单列，bar 改为 2×2；仍使用宿主 `--nx-*` 主题变量，不新增独立色板。
- 本轮测试：`core/ui: npx vitest run tests/network-redesign.test.mjs tests/network-plugin-ui.test.mjs tests/network-plugin-surfaces.test.ts`（24 + 3 + 2 通过）。

## 0.2.6 下载工具与智能线路兜底（2026-10-27）

<!-- user:“把 download 给做成一个工具，传参下载链接，可指定为前台和后台，以及路径” -->
<!-- user:“加速和代理要不要改成智能进行，先想清楚加速和翻墙的原理” -->

- 新增 agent 工具 `network_download`，薄封装现有 aria2 队列。参数 `url`、`directory`、`filename`、`foreground`、`wait_seconds`、`connections`、`proxy`；后台立即返回 gid，前台轮询到完成/失败/超时。超时只返回 `downloading`，任务继续运行。工具权限为 `ask_user`，因为会写用户指定目录。
- `transfer.add` 现在返回 `gid`、`filename`、`directory`，前台工具据此直接给出本地路径，不用再猜默认目录。
- 加速开启时若已保存订阅，会自动启动 Mihomo 内核作为线路兜底，但**不会改系统代理**；用户手动操作代理后，停止加速不再替用户关闭线路。
- 加速器新增 30 分钟域名记忆：常用域名直连 TCP/TLS 失败并成功回退线路后，下次优先走线路；线路也失败时忘掉记忆并重新尝试直连。记忆只存在当前控制器进程内。
- 首页加速块和加速页文案同步说明“线路兜底”，不再暗示非命中域名一定有线路可用。
- 验收：`core/tests/test_network_download_tool.py` 3 个测试（声明、前后台、相对路径拒绝）；控制器 25 个测试；网络 UI 30 个测试。

## 0.2.7 右侧栏改为三行胶囊（2026-10-27）

<!-- user:“这个玩意儿的右侧栏样式 你重做一下三行 3 个胶囊，简单明了 易交互” -->

- 右侧快捷面板从“标题 + 大开关 + 网速行 + 打开首页链接”改为三行胶囊：加速、代理、下载。整行可点，状态和任务数显示在右侧。
- 加速胶囊直接开关本机加速；代理胶囊有订阅时直接开关线路、没订阅时打开代理页；下载胶囊显示进行中任务与总速度，点击直接打开下载页。
- 主页面新增 `sessionStorage` 初始页与 `sunday:network-plugin-page` 事件，侧栏在页面已打开时也能直接切到代理/下载页。
- 新增右侧栏测试：三枚胶囊存在、加速与代理直接发操作、下载胶囊写入目标页并派发打开事件；主页面能读取并清理目标页。
- 网络 UI 测试 32 个通过；插件页面已重新构建。

## 0.2.8 右侧栏三胶囊与宿主毛玻璃对齐（2026-10-27）

<!-- user:“右侧栏是不是本身就提供了卡片…直接把该要的那 3 个胶囊镶上去”“一个开启键…一个点击更换节点…一个 URL 输入框”“能用图标表示的地方就不用写文字” -->
<!-- user:“这个卡片的深色是由卡片右侧栏本身提供的…查查它是怎么做的” -->

- 查到非插件右侧卡片由 `RightSidebarHost` 的 rail module 挂载，卡片本体是 Teleport 到 body 的 `.right-sidebar-card.optical-glass.optical-glass--low-trans`；插件 right 区域则渲染在抽屉已有的 `.plugin-region-card` 里，这个容器只有边框和内边距、没有背景。因此插件侧不再绘制任何卡片底色。
- 快捷面板改为透明容器 + 三颗半透明胶囊，文字使用 `--theme-backdrop-text`；胶囊只叠 `color-mix(text 4%, transparent)`，让宿主的 `backdrop-filter` 和深色玻璃直接透出来。
- 三颗胶囊保留基础能力：加速一颗电源键；代理一个节点下拉 + 一颗电源键；下载一个 URL 输入框 + 一个下载键。能用图标表达的入口全部使用图标，文字只保留节点名、状态值和 URL 占位。
- 代理节点下拉从第一个非 GLOBAL 的 Selector 分组读取真实成员，选择后调用 `proxy.select`；没有订阅时电源键落到代理页。
- 网络 UI 测试 33 个通过；插件页面已重新构建。
