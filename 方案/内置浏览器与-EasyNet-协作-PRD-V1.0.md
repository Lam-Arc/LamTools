# 内置浏览器 × EasyNet 协作 PRD

> 来源：用户 2026-11-23 提问「检查目前内置浏览器的下载和网络功能等是否可以与 easynet 协作，若可以，给我 PRD」。
> 版本 V1.0 · 2026-11-23 · 优先级 P1 · 状态：阶段 A–E 已实施，单元与构建验收通过；真机手工验收待做（见 §9）。

## 1. 结论

**可以协作，接缝有三条，都有代码依据：**

| 接缝 | 方向 | 现状 | 能不能做 |
| --- | --- | --- | --- |
| S1 下载接管 | 浏览器 → EasyNet 队列 | 浏览器自己落盘、只有开始/完成/失败三态 | 能，`on_download` 已经拦到 URL，可改成投递 |
| S2 出口统一 | EasyNet → 浏览器代理 | 浏览器只在建环境时读一次系统代理并缓存 | 能，但要接受「改出口后要重建环境」 |
| S3 失败联动 | 浏览器错误 → EasyNet 诊断 | 浏览器只有一个错误条，没有网络诊断 | 能，EasyNet 已有分层结论，直接调 |

**两条不成立的方向，明确不做：**

- 浏览器不要自建第二套下载队列（aria2 已经有一份，重复维护必然对不上）。
- 不要指望插件给浏览器弹通知：插件的页面上下文只有 `rpc / visible / openPage / openFile / addStyle`（`core/ui/src/plugins/pages.ts:24-32`），没有通知通道。

## 2. 现状审查（代码证据）

| 对象 | 事实 | 证据 |
| --- | --- | --- |
| 浏览器下载入口 | 唯一通道是 `on_download`；`Requested` 阶段就把落盘路径定死 | `core/desktop/src-tauri/src/browser/webview.rs:168-196` |
| 浏览器下载状态 | 只有 `started / finished / failed`，明确不做进度与暂停 | `core/desktop/src-tauri/src/browser/download.rs:1-40` |
| 浏览器下载目录 | 固定 `系统下载目录/Sunday`，不按项目分 | `core/desktop/src-tauri/src/browser/mod.rs:378-383` |
| 浏览器下载操作 | 只有 `open / reveal`；危险后缀（exe/msi/脚本）打开前要审批 | `core/desktop/src-tauri/src/browser/mod.rs:1280-1310` |
| 浏览器出口 | 建 WebView2 环境时读 `HKCU\...\Internet Settings` 的 `ProxyServer`，拼成 `--proxy-server`，并禁用 QUIC | `core/desktop/src-tauri/src/browser/compositor.rs:328-345`、`383-393` |
| 环境缓存 | 环境按数据目录缓存，建一次就复用 | `core/desktop/src-tauri/src/browser/compositor.rs:229-262` |
| 浏览器「诊断」 | 是**越权自检**（检查 `__TAURI_INTERNALS__` 等是否泄漏），不是网络诊断 | `core/desktop/src-tauri/src/browser/platform_win.rs:908-1000` |
| 浏览器下载条 | 已有列表、打开、定位、审批提示，并跟随 `download` 事件刷新 | `core/ui/src/components/CoreSplitBrowser.vue:183-215`、`523-528` |
| EasyNet 下载 | aria2 队列：续传、1–16 并发、单任务与全局限速、SHA-256、重启恢复 | `controller/src/engines.rs:1120-1210` |
| EasyNet 诊断 | 五层探测 + 分层结论（本机/网关/DNS/外网/代理） | `controller/src/observe.rs` 的 `network_diagnose` |

**由此得到两个真实缺陷：**

1. 系统代理在浏览器环境建好之后被 EasyNet 改掉，**已打开的浏览器不会跟着变**——它还在用旧代理，直到环境被重建。用户会看到「EasyNet 显示代理已开，浏览器还是打不开」。
2. 页面打不开时，浏览器只能给一句错误，无法回答「是 DNS 挂了、代理挂了，还是这个站自己 500」。而这正是 EasyNet 已经能回答的问题。

## 3. 功能要求

### 3.1 S1 浏览器下载交给 EasyNet（P0）

**目标**：用户在网页上点下载，任务出现在 EasyNet 的下载页，能暂停、继续、限速、续传、校验，和 `network_download` 工具、下载页是同一份列表。

**做法**

1. 浏览器在 `DownloadEvent::Requested` 阶段判定是否接管：
   - 接管开关由前端下发（`browser_download_takeover`），默认**关闭**；只有前端确认 EasyNet 已启用且后端就绪时才打开。
   - 接管时返回 `false` 取消原生下载，并发出 `lamtools://browser-download-request`，带 `{tab, url, cookie, userAgent, referer}`。
   - 不接管时保持现状，走原生下载。
2. 前端收到事件后调 `easynet.transfer.add`，并带 `source: "browser"` 与 `headers`（Cookie / User-Agent / Referer）。
3. EasyNet 侧 `transfer.add` 新增可选 `headers`：只允许 `Cookie`、`User-Agent`、`Referer` 三个键，值长度上限 8 KB，随请求一起进 DPAPI 加密记录，不进日志、不进 `transfer.list` 返回。
4. 任务记录新增 `source`（`browser` / `page` / `tool`），下载页据此显示来源标签。
5. 失败回退：`transfer.add` 失败时，前端提示原因并给「用浏览器直接下载」；点了就临时关闭接管、重新导航该 URL，让原生下载走一遍。

**取舍（写清楚，避免以后被当成 bug）**

- 不接管 `blob:`、`data:`、POST 表单提交、流媒体分片、需要 DRM 的下载——这些拿不到可重放的 URL。
- 接管后浏览器不再有自己的字节进度；进度来自 EasyNet 快照（同一条 gid）。
- 带 Cookie 的链接依赖 Cookie 传递；如果目标站点用一次性签名，接管会失败并走回退，这是预期行为。

**验收**

- 插件关闭时：点下载仍然成功落盘，浏览器列表照常显示三态，不弹任何 EasyNet 相关错误。
- 插件开启时：点直链 → EasyNet 下载页出现同一条任务（`source=browser`）→ 暂停/继续/限速可用 → 完成后文件哈希与原生下载一致。
- 本地测试服务要求 `Cookie: session=ok` 才返回文件：接管路径能下载成功（证明 Cookie 传递生效）。
- 接管失败（例如 404）：错误条给出具体原因，点「用浏览器直接下载」能走通。

### 3.2 S3 页面打不开时一键检查网络（P0）

**目标**：错误条从「一句话」升级为「一句话 + 原因 + 下一步」。

**做法**

1. `CoreSplitBrowser` 的错误条加「检查网络」按钮。
2. 点击后调 `easynet.diagnose`，参数 `{target: 当前域名, port: 443, kind: "basic"}`（不是整机五层，避免等太久；整机检查留在 EasyNet 诊断页）。
3. 结论回填到错误条：例如「能解析地址，但连不上对方的端口」「网络正常，但这个网站自己返回了错误」「系统 DNS 解析失败，网络本身是通的」。
4. 结论里给一个跳转：「打开 EasyNet 诊断」→ 调 `sunday:open-plugin-page` 打开插件页的 diagnose 分区。
5. EasyNet 不可用时，按钮不显示（不出现点了没反应的入口）。

**验收**

- 断网场景：错误条点检查 → 结论落在「本机/网关」层，不误导成「网站挂了」。
- 目标返回 500：结论是「网络正常，网站自己出错」。
- 域名不存在：结论是「找不到这个网站的地址」。

### 3.3 S2 浏览器出口与 EasyNet 一致（P1）

**目标**：EasyNet 开了加速/代理，浏览器立刻用上；EasyNet 显示「仅 Sunday 内生效」时，浏览器也属于 Sunday，不该被排除在外。

**做法**

1. 新增 `browser_network_state`：返回 `{mode: "accelerator"|"system"|"direct", endpoint, note}`。取值优先级：
   - EasyNet 加速器在跑 → `accelerator`，`endpoint = 127.0.0.1:<port>`；
   - 否则系统代理开启 → `system`，`endpoint = 系统代理`；
   - 否则 `direct`。
2. `build_environment_options` 改为读这份状态，而不是直接读注册表。
3. 状态变化时：新增 `browser_reload_network`，清掉 `host.envs` 缓存并重建当前可见标签；无法重建时（正在下载/有未保存表单）给「重新打开网页后生效」的提示，不静默假装已生效。
4. EasyNet 在 `system.apply / system.restore / accelerator.start / accelerator.stop` 之后派发 `sunday:easynet-network-changed`；宿主收到后刷新出口状态并提示。

**取舍**

- WebView2 的代理只能在建环境时给定，所以「切换出口」必然有一次环境重建；不承诺无感切换。
- 不做每标签页代理、不做 PAC、不改系统 DNS。

**验收**

- EasyNet 开启加速（不改系统代理）→ 新开标签页走加速端口（本地加速器日志能看到命中域名）。
- 关闭加速 → 新开标签页回到直连/系统代理。
- 切换时正在下载的任务不受影响（下载走 EasyNet 队列，不依赖浏览器环境）。

### 3.4 浏览器「更多」里的网络一行（P2）

在「更多」菜单加一行只读状态：`当前出口：本机加速 127.0.0.1:49231` / `系统代理 127.0.0.1:7890` / `直连`，加一个「打开 EasyNet」链接。不做浏览器内独立代理设置。

## 4. 明确不做

- 不把内置浏览器改成「全部流量走 EasyNet」的强制代理；EasyNet 是可选插件。
- 不在浏览器里重建第二套下载列表、第二套进度、第二套暂停/继续。
- 不接管 POST / blob / data / DRM / HLS 分片。
- 不因为协作给浏览器加管理员权限，不改 hosts，不装证书。
- 不把 Cookie、Referer、带签名的下载 URL 写进日志或诊断报告。

## 5. 接口与数据改动

| 位置 | 改动 |
| --- | --- |
| `easynet.transfer.add` | 新增 `headers`（Cookie/User-Agent/Referer，白名单 + 8 KB 上限）、`source` |
| `easynet.status` / `transfer.list` | 任务行新增 `source`；`headers` 永不回传 |
| 宿主命令 | 新增 `browser_download_takeover`、`browser_download_retry`、`browser_network_state`、`browser_reload_network` |
| 宿主事件 | 新增 `lamtools://browser-download-request`；监听 `sunday:easynet-network-changed` |
| EasyNet 事件 | 系统代理/加速启停后派发 `sunday:easynet-network-changed` |

## 6. 非功能与安全

- **插件可选性**：EasyNet 关闭、崩溃或后端未就绪时，浏览器必须完全退回现状，不阻塞、不报错、不出现灰色死按钮。
- **Cookie 最小化**：只在接管瞬间从 WebView2 Cookie 管理器读当前 URL 的 Cookie，只用于本次请求；随请求进 EasyNet 的 DPAPI 加密记录（已有机制），不写日志、不进错误信息、不返回给前端之外的任何地方。
- **危险后缀**：接管后仍沿用现有规则——exe/msi/脚本下载完成后不自动打开，打开前要确认。
- **不重复维护状态**：浏览器下载条显示的是 EasyNet 的任务快照（按 gid 关联），不是自己攒的第二份。
- **失败可见**：任何一步失败都要给出可执行下一步（重试 / 用浏览器直接下载 / 打开诊断），不静默。

## 7. 执行顺序

| 阶段 | 内容 | 交付物 |
| --- | --- | --- |
| A | EasyNet 侧 `headers` + `source`，含白名单与上限校验 | 单测：非法 header 被拒、来源字段进快照 |
| B | 宿主 `on_download` 接管 + 事件 + 开关 + 原生回退 | 单测：开关关闭时返回 true、开启时返回 false 且事件带 URL |
| C | 浏览器下载条改为消费 EasyNet 快照 | 界面测试：同一条 gid 在两边状态一致 |
| D | 错误条「检查网络」+ 结论回填 | 界面测试：三类失败对应三种结论 |
| E | 出口统一 + 环境重建 + 变化通知 | 手工验收：加速开/关后新标签出口正确 |

每个阶段都能单独交付，不等待后续阶段。

## 8. 验收标准

| 项目 | 验收目标 |
| --- | --- |
| 功能真实性 | 每个新按钮都有真实后端；插件不可用时相关入口不出现 |
| 下载一致性 | 同一次下载在浏览器与 EasyNet 显示同一条任务、同一状态、同一文件路径 |
| 下载可靠性 | 接管路径支持续传与校验；失败能退回原生下载 |
| 出口一致性 | EasyNet 显示「已加速」时，新开标签页确实走加速端口 |
| 诊断有效性 | 页面失败时能区分 DNS / 端口 / 服务端 5xx / 本机断网 |
| 权限安全 | Cookie 不进日志；危险后缀仍需确认；不新增管理员权限 |
| 模块复用 | 不新增第二套下载队列、第二套诊断、第二套设备状态 |
| 资源管理 | 接管关闭时不额外轮询；出口状态只在变化时刷新 |

---

## 9. 实施记录（2026-11-23）

### 各阶段状态

| 阶段 | 内容 | 状态 | 证据 |
| --- | --- | --- | --- |
| A | EasyNet 接受 `headers`/`source` | 完成 | `controller/src/transfer.rs`（白名单 + 8 KB 上限 + 换行拒绝）、`controller/src/engines.rs`（`header` 进 aria2 选项、`source` 进任务记录） |
| B | 浏览器下载接管 + 请求头回传 + 回退 | 完成 | `browser/download.rs`（开关 / 一次性放行 / 可接管判定）、`browser/webview.rs`（Requested 分支）、`browser/mod.rs`（三个命令 + 两个事件）、`browser/platform_win.rs`（Cookie + UA 读取） |
| C | 浏览器下载条显示交接记录 | 完成（不做进度镜像） | `core/ui/src/components/CoreSplitBrowser.vue` 的「已交给 EasyNet」行 + 「查看」跳转 |
| D | 错误条「检查网络」 | 完成 | 同上组件 + `core/ui/src/app/LamToolsApp.vue` 的 `sunday:easynet-diagnose-request` 桥 |
| E | 出口统一 | 完成（新建网页生效） | `browser/compositor.rs` 的网络出口覆盖 + `browser_network_state` 命令；插件在系统代理/加速变化后派发 `sunday:easynet-network-changed` |

### 实际取舍（与 §3 的差异，不算偏离需求）

1. **进度镜像（2026-11-23 修正）**：最初只写「已交给 EasyNet」，用户指出「下载进度不镜像本身就是反直觉且不原生」。现改为：宿主在有接管任务时按 1.5 秒读一次 `easynet.status`，把同一批 gid 的进度、速度、状态推给浏览器下载条；全部结束即停止轮询。浏览器下载条显示进度条、百分比、速度、已下载/总量，并提供暂停、继续、取消、打开——与原生下载的操作一致，数据仍只来自 EasyNet 快照，不另存一份。
2. **出口切换只对之后创建的网页生效**：WebView2 的代理只能在建环境时给定，所以没有做「无感热切换」，也没有强制重建正在使用的网页。切换后会清掉环境缓存，新开网页即生效。
3. **接管默认仍为关闭**：只有宿主确认 EasyNet `enabled && available && backend.state === ready` 时才打开；插件不可用、或 `transfer.add` 失败时，自动放行一次原生下载并在提示里说明原因。
4. **请求头只带 Cookie 与 User-Agent**：Referer 在白名单里，但宿主目前不采集（拿不到可靠值），不假装带上。

### 验证

| 范围 | 命令 | 结果 |
| --- | --- | --- |
| EasyNet 控制器 | `cargo test`（插件 controller） | 40 通过（请求头白名单/上限/注入、下载默认目录校验） |
| 浏览器宿主 | `cargo test --bin Sunday browser::download` | 11 通过（新增接管默认关闭、一次性放行、只接管 HTTP(S) 直链） |
| 宿主类型检查 | `npx vue-tsc --noEmit` | 本次改动的文件无报错（仓库其余 192 条为既有问题） |
| 插件面板 | `npx vitest run tests/network-*.test.mjs` | 46 通过（新增订阅保存后自动加载节点、默认下载目录可见可改、订阅切换、双击打开） |
| 插件构建 | `npx vite build --config vite.config.network-plugin.ts` | 成功 |

### 待真机验收（本机没做，因为要动用户正在用的浏览器）

1. 插件关闭：网页点下载 → 原生下载成功，接管开关保持关闭。
2. 插件开启：同一直链 → EasyNet 下载页出现 `source=browser` 任务；暂停/继续/限速可用；最终哈希与原生下载一致。
3. 需要登录的链接（本地服务校验 `Cookie`）：接管路径能下载成功。
4. EasyNet 开加速（不改系统代理）→ 新开网页走加速端口；关掉后新开网页回到系统代理。
5. 页面打不开 → 错误条「检查网络」→ 显示分层结论。
