# EasyNet 产品审查（PRD V1.0 · 阶段 A）

<!-- user:“现有 EasyNet 审查”“每个问题记录严重程度、代码证据、用户影响、预期结果和验收方式”+(先建立带代码证据的功能现状表，不把历史缺陷直接当成当前缺陷)。 -->

审查对象：`core/src/lamtools_core/plugins/bundled/network-exploration`（版本 0.2.4），宿主侧 `core/ui/src/design-system/Network*Preview.vue`、`core/desktop/src-tauri/src/browser/download.rs`、`core/p2p/src/transfer.rs`。
方法：读源码 + 读既有测试 + 与 PRD 逐条比对；未在本机改动任何系统网络配置。历史结论只作为线索，全部重新按当前代码核对。

---

## 0. 结论摘要

1. **核心链路是真的**：加速、代理（Mihomo）、订阅、选线路、下载（aria2）、诊断、系统代理/DNS/防火墙/QoS 与恢复，都有真实 Rust 后端与真实端到端测试（`core/tests/test_network_exploration.py:76` 用真 aria2 跑完暂停→重启→续传→哈希一致）。
2. **最严重的问题是「有界面、点不到」**：`NetworkSettings`（DNS/规则）、`ConnectionsView`（连接列表）、`SecurityView`（应用联网/限速/恢复）三个页面在 `NetworkApp.vue:70/77/84` 定义了，但 `navItems`（`:99-101`）把它们过滤掉，全仓也没有任何 `emit('navigate', 'network'|'traffic'|'security')`。等于 **DNS 修改、规则预览、应用出站管控、连接排查这些已实现的能力对用户完全不可用**。
3. **下载是「能下但不闭环」**：续传、并发、限速、校验、重启恢复都有；缺失败原因翻译、完成通知、打开文件、全局并发/重试设置、服务端不支持续传时的提示。
4. **PRD 3.5「设备互联」的底座已经存在，不要在 EasyNet 里重做**：`core/p2p/src/transfer.rs`（分块互传、进度、取消、仅信任设备）+ `RemoteConnectionPanel.vue`(1411 行)/`SendToDeviceMenu.vue`/`TransferPanel.vue` 已经覆盖配对、设备清单、发送与接收。
5. **PRD 3.6「虚拟局域网」是从零新增**，仓库里没有任何 VPN 内核、路由或 TUN 相关实现。
6. **两处需要你拍板**：界面信息架构（PRD 四视图 vs 你之前定的「左栏少入口、其余从卡片进」），以及系统修改是否恢复逐次授权（PRD 要求授权，现状是 `auto_allow`，来自你之前「不希望这个东西再出现」的决定）。

---

## 1. 架构现状（作为后续判断的基线）

| 层 | 事实 | 证据 |
| --- | --- | --- |
| 宿主桥接 | Python 只管生命周期、审批桥、目录 ACL、Job 回收、看门狗自愈，不持有业务 | `backend.py:97-173`、`process_job.py` |
| 业务 | 全部在一个 Rust 控制器里，33 个操作 | `controller/src/state.rs:108-156`、`operations.json` |
| 界面 | 插件自绘，构建成单文件 `ui/page.mjs`（943 KB） | `ui/page.mjs`、`ui/src/*.vue` |
| 内核 | aria2 1.37.0、Mihomo 1.19.33 随包，固定版本 + SHA-256 校验 | `resources/engines/`、`engine_install.py` |
| 凭据 | DPAPI（当前 Windows 账户）+ 数据目录 ACL | `credentials.rs`、`backend.py:109-117` |

---

## 2. 功能现状表

分类口径按 PRD：保留 / 优化 / 补齐 / 合并 / 删除。

### 2.1 保留（可用，不改造）

| # | 能力 | 证据 | 说明 |
| --- | --- | --- | --- |
| K1 | 系统代理应用/恢复 + 事务快照 + 外部修改保留现场 | `system.rs:262-420`、`system.rs:528` 测试 | 只允许指向 `127.0.0.1:<port>`（`system.rs:40-56`），不会把系统代理改成任意地址 |
| K2 | Mihomo 配置净化：强制 `tun=false`、`allow-lan=false`、控制面归一为回环、注入随机 secret | `engines.rs:992`、`engines.rs:1456` 测试 | 导入订阅不会顺手打开 TUN 或暴露局域网监听 |
| K3 | 订阅导入（优先走系统代理、分档超时、DPAPI 存储） | `engines.rs:376-436` | 真实订阅主机实测过的路径 |
| K4 | 节点/分组/provider 合并、单点测速、一键最快（失败保留当前） | `engines.rs:511-633` | 「最快」只代表本次延迟最低，界面文案已如此声明 |
| K5 | 本机 CONNECT 加速（DoH 选 A 记录、命中域名直连、非命中回退 Mihomo） | `accelerator.rs`（661 行）+ 6 个单测 | 不改 hosts、不装证书 |
| K6 | 下载断点续传与重启恢复 | `engines.rs:655-700`（`--continue=true`）、`engines.rs:1185-1230`、`test_network_exploration.py:76` | 重启后恢复为暂停态，续传复用 `.aria2` |
| K7 | 下载参数统一（文件名推导、Windows 保留名、1000 条上限、同名拒绝） | `transfer.rs:3-100`、`engines.rs:1086-1185` | 三个入口共用同一份校验 |
| K8 | 诊断分阶段（DNS→TCP→TLS/HTTP，可加 Ping/Traceroute），不宣称未测量的结论 | `observe.rs:148-215` | 明确写「不能仅凭 5 秒未解析判定 DNS 污染」 |
| K9 | 接口/DNS/路由/连接/邻居查询 | `observe.rs:52-147` | 邻居表是缓存快照，不是主动扫描 |
| K10 | 进程 Job + 看门狗：宿主崩溃不留内核子进程，控制器挂了自愈 | `backend.py:122-173` | |

### 2.2 优化（能用，但不达 PRD 的可靠性/体验线）

| # | 问题 | 严重度 | 代码证据 | 用户影响 | 预期结果 | 验收方式 |
| --- | --- | --- | --- | --- | --- | --- |
| O1 | 状态轮询是全量快照：每 5 秒拉一次含 `history`(120)、`reports`(≤50，含 traceroute 原文)、`events`(200) 的 payload | 高 | `ui/store.mjs:16`、`state.rs:165-172` | 面板开着就持续消耗，诊断做多了 payload 变大 | 概览只取轻量字段，历史/报告按需拉 | 面板静置 10 分钟采样：单次 status 响应 < 32 KB；无任务时 CPU < 0.5% |
| O2 | 下载进度每次变化都整份重写 `state.json`（含全部报告/事件） | 中 | `engines.rs:1230-1256` | 大文件下载时磁盘写放大 | 只写下载区或增量落盘 | 下载 1 GB 期间 `state.json` 写入次数与字节数下降一个量级 |
| O3 | aria2 错误被压成一句话，`errorCode` 不翻译 | 高 | `engines.rs:642-655` | 失败只说「请检查任务状态、文件权限或链接有效期」 | 按 aria2 错误码给出可执行原因（404/403/磁盘满/证书/超时） | 构造 404、403、磁盘不足三种失败，界面文案各不相同 |
| O4 | 同一能力多处重复入口：加速 3 处、代理 3 处、下载 3 处、订阅 4 处 | 中 | `HomeView.vue:158/206/253`、`DashboardView.vue:47`、`QuickPanel.vue:88/111/120`、`ProxyView.vue:22/49`、`NodePicker.vue:182/194` | 用户不知道哪个是「正确入口」 | 每能力保留 1 主入口 + 快捷面板 | 界面清点表，同能力入口 ≤ 2 |
| O5 | 忙碌期点击被静默丢弃（无提示） | 中 | `session.mjs:127` | 连点没反应，以为卡死 | 返回「正在处理上一步」 | 连点 3 次只执行 1 次且有提示 |
| O6 | 先报成功再等轮询：`run()` 收到 RPC 返回即写「已开始下载」 | 中 | `session.mjs:133`、`HomeView.vue:97` | 后台随后失败时用户已看到成功 | 以任务真的出现在快照里为准 | mock 让 `transfer.add` 成功但列表无任务 → 界面不得显示「已开始下载」 |
| O7 | 「累计流量」是系统接口自开机累计，界面未说明口径 | 中 | `state.rs:250-251`、`HomeView.vue:28-32` | 用户会以为这是 EasyNet 自己传的量 | 标注口径，或改为本插件自上次启动累计 | 文案与数据源一致，可被 `traffic_source` 验证 |
| O8 | 面向普通用户的界面仍在用 DoH / hosts / 线路兜底 / 并行数量 / SHA-256 | 中 | `DashboardView.vue:37/74/77`、`HomeView.vue:146`、`TransferView.vue:208/236` | 认知成本高，与「脑残来都会用」冲突 | 术语换人话或加一句解释 | 首屏与下载页无未解释缩写 |
| O9 | 零检查项时可能显示「检查通过」 | 低 | `DiagnoseView.vue:113`（`undefined > 0 === false`） | 极端情况下给出假阳性结论 | `checks` 为空时显示「未取得测量结果」 | 构造空 checks 报告 → 不显示通过 |

### 2.3 补齐（场景需要，当前缺失）

| # | 缺口 | 严重度 | 证据 | 预期结果 | 验收方式 |
| --- | --- | --- | --- | --- | --- |
| G1 | 三个已实现页面没有入口：DNS 修改、规则保存/测试、连接列表、应用出站防火墙/上传 QoS/恢复、局域网设备 | **阻断级** | `NetworkApp.vue:70/77/84` 定义、`:99-101` 过滤；全仓无 `navigate` 到这三页；`NetworkSettings.vue:134` 还指向进不去的「防护」 | 每个已实现能力都能从界面到达 | 点击路径走查：从首页 3 步内到达 DNS 修改与应用联网 |
| G2 | 首页没有诊断入口（PRD 3.1 要求） | 高 | `HomeView.vue` 三块 = 加速/代理/下载，无检测 | 概览有「检查网络」入口 | 首页可见可点，进入检测页 |
| G3 | 没有「检查网络」一键诊断：本机接口、网关、局域网、外网、代理冲突 | 高 | `observe.rs:148` 只针对单个 target；`interfaces`/`lan` 是独立查询，不进诊断结论 | 一次点击覆盖 5 层并给出人话结论 | 断网/断 DNS/代理挂掉三种场景，结论各不相同且正确 |
| G4 | 诊断结论只有通用建议，没有「网络正常但目标无响应」这类判断 | 高 | `observe.rs:211` recommendation 是固定句式 | 按失败所在层生成结论 | 4 个场景文案互不相同 |
| G5 | 下载完成通知 | 中 | 宿主 `PluginPageContext`（`core/ui/src/plugins/pages.ts:24-32`）只有 rpc/signal/openPage/openFile/addStyle，无通知通道 | 下载完成能提示 | 后台完成后用户被提示一次 |
| G6 | 打开文件/定位文件 | 低 | `pages.ts:30` 已有 `openFile`，`TransferView.vue` 未使用 | 完成行有「打开」 | 点击后系统打开该文件 |
| G7 | 全局并发数与重试策略不可设置 | 中 | `engines.rs:686-689` 硬编码 `--max-concurrent-downloads=3`、`--max-tries=5`、`--retry-wait=3` | 设置页可调 | 改并发后同时活跃任务数随之变化 |
| G8 | 服务端不支持续传时无提示 | 中 | `--continue=true` 但无「服务端未返回 Accept-Ranges」的判定 | 明确提示「该源不支持续传，将重新下载」 | 用不支持 Range 的源验证提示出现 |
| G9 | 代理循环/端口不可达/认证失败识别（PRD 3.4） | 中 | 现只有「Mihomo 控制接口不可用」等笼统错误 | 能区分三类失败 | 三种构造场景分别给出不同提示 |
| G10 | 设备互联统一入口（PRD 3.5） | 中 | EasyNet 内 0 设备能力；宿主已有 `core/p2p/src/transfer.rs` + 三个设备组件 | 一个入口看到设备与互传 | 与现有「设备连接」页不出现两套状态 |
| G11 | 虚拟局域网（PRD 3.6） | 低（P2） | 全仓无 TUN/路由/VPN 内核 | 可选私人网络 | 见阶段 D，需先做内核与许可评估 |

### 2.4 合并（与其它模块重复）

| # | 重复项 | 证据 | 建议 |
| --- | --- | --- | --- |
| M1 | 浏览器下载是另一套实现：三态、无进度/暂停/续传，落 `~/Downloads/Sunday` | `core/desktop/src-tauri/src/browser/download.rs:1-40`、`core/ui/src/split/native.ts:271` | 浏览器下载改为投递到 EasyNet 的 `transfer.add`，保留危险后缀审批；不新增第二套队列 |
| M2 | 设备配对/互传/传输列表已在宿主实现 | `core/p2p/src/transfer.rs`、`RemoteConnectionPanel.vue`、`SendToDeviceMenu.vue`、`TransferPanel.vue` | EasyNet 只做入口与状态展示，不实现第二套配对或消息队列 |
| M3 | 加速页复制了一份「检查网站」表单 | `DashboardView.vue:103-110` vs `DiagnoseView.vue:66` | 加速页改为跳转，表单只留检测页 |
| M4 | 同一页 4 个「添加/更新订阅」入口 | `ProxyView.vue:22/49`、`NodePicker.vue:182/194` | 保留 1 个 |
| M5 | 设计系统展厅的 5 个 Network 预览 | `core/ui/src/design-system/NetworkHomePreview.vue:3-4` 直接 import 插件真组件 | 不是重复实现，是薄壳；**保留** |

### 2.5 删除

| # | 对象 | 证据 | 处理 |
| --- | --- | --- | --- |
| D1 | `ui/src/TrafficDonut.vue` | 全仓无 import | 删除，或替换首页「累计流量」纯文字 |
| D2 | `ui/src/ConnectionModes.vue` | 全仓无 import；`proxy.mode` 因此无任何 UI 入口 | 先补模式入口再删，避免连模式切换一起丢 |

---

## 3. PRD 章节差距

| PRD | 要求 | 现状 | 结论 |
| --- | --- | --- | --- |
| 3.1 概览 | 网络类型/连接状态、速率、累计流量、可达性与最近异常、下载任务、已连设备、诊断入口 | 速率✓ 累计流量✓(口径未说明) 下载✓ 网络类型与最近异常✗(在「网络」「更多」里且进不去) 设备✗ 诊断入口✗ | 补齐 G1/G2 + 优化 O7 |
| 3.2 下载 | 多任务/暂停恢复、续传与不支持时提示、并发/限速/重试可设、失败原因、完成通知、校验、打开、Browser/Easy File/Agent 同一列表、重启保留 | 多任务✓ 续传✓ 不支持提示✗ 并发(单任务✓/全局✗) 限速✓ 重试✗ 失败原因✗ 通知✗ 校验✓ 打开✗ Browser 同一列表✗ Agent✓ 重启✓ | 优化 O3 + 补齐 G5-G8 + 合并 M1 |
| 3.3 诊断 | 一键检查 5 层 + 人话结论 + 修复需告知并可恢复 | 只有单目标 DNS/TCP/TLS/HTTP；无本机/网关/代理冲突；结论固定句式 | 补齐 G3/G4 |
| 3.4 代理 | 系统代理与内部代理状态、HTTP/SOCKS5、导入/测试/启停、区分「仅 Sunday」与「改系统代理」、循环/端口/认证识别、可恢复 | 状态✓ 导入测试启停✓ 区分✓ 可恢复✓ 协议：系统代理仅 HTTP 回环（`system.rs:40-56`）、内核侧支持多协议；三类错误识别✗ | 补齐 G9；协议限制需在文案里说清 |
| 3.5 设备互联 | 「我的设备」统一入口、配对/解绑、发文件、手机访问电脑文件、远程操作、诊断 | EasyNet 无；宿主已有配对+互传+设备页 | 合并 M2 + 补齐 G10（需你定入口归属） |
| 3.6 虚拟局域网 | 一键建网、自动地址、直连优先中继兜底、Ping/延迟、子网访问、EasyTier 复用 | 无 | 补齐 G11（阶段 D） |
| 4 界面 | 概览/下载/互联/诊断 四视图；代理与高级设置进设置页 | 左栏 首页/加速/代理/下载；检测/网络/连接/防护/更多 中 3 个进不去 | **需要决策**（见 §5） |
| 5 非功能 | 默认不提权、无任务不高频轮询、断网安全暂停、单任务不拖崩 Core、凭据分存、日志不泄露、兼容其它 VPN/防火墙 | 不提权✓ 轮询 5s 常驻⚠ 断网暂停✓(aria2 重试) 崩溃隔离✓(Job+看门狗) 凭据 DPAPI✓ 日志✓ 不擅自关防护✓ | 优化 O1/O2 |
| 6 验收 | 「系统设置修改需授权」 | 现状 `system.apply/restore` = `auto_allow`（`operations.json:117-141`），来自你此前明确要求 | **需要决策**（见 §5） |

---

## 4. 测试覆盖（摘要）

现有：Python 12 个用例（含真 aria2、真 Mihomo、真宿主 WebSocket）、Rust 38 个单测、UI 约 60 个 vitest。

| 验收目标 | 覆盖 | 缺口 |
| --- | --- | --- |
| 功能真实性 | 部分 | 只有 status/connections/interfaces/diagnose/代理/下载走真实链路；其余靠 mock rpc |
| 下载可靠性 | 仅单元 | 只测「暂停→重启→续传」，没测「传输中断线自动重连」 |
| 重启恢复 | 有 | 未覆盖任务消失/文件被删后转「明确失败」的分支 |
| 诊断有效性 | 仅单元 | 分阶段判定本身零测试，只测了输入校验 |
| 数据准确性 | 仅单元 | 只断言来源标注，没有采样→速率的换算校验 |
| 权限安全 | 仅单元 | 无「未授权被拒」用例；auto_allow 下等于无授权环节 |
| 资源管理 | 无 | 空闲 CPU/句柄/线程泄漏无测试 |
| 模块复用 | 无 | 无 Relay/Browser 共用 transfer 的断言 |

假通过风险：`test_network_download_tool.py:73` 的「绝对路径」错误由它自己的 mock 抛出；`:114` 直接测 aria2 绕过插件选线逻辑；`credentials.rs:90` 整块被 `cfg(all(test, windows))` 门控。

---

## 5. 需要你决定的三件事

1. **界面信息架构**：PRD 要「概览/下载/互联/诊断 + 设置页收口」；你之前定的是「左栏只留常用 3-4 个，其余从卡片内部进」。当前实现是左栏 4 个 + 3 个页面彻底没有入口。两者可以合成一套（左栏 4 个 = 概览/下载/互联/诊断，代理与高级进设置页），但那会把你熟悉的位置全换一遍。
2. **系统修改是否恢复逐次授权**：PRD 验收要求「系统设置修改需授权」，而你之前明确说过不希望再看到那个审批。现状是桌面端直接放行，只有快照与恢复。
3. **设备互联的归属**：宿主已有「设备连接」页（配对、互传、发送到设备）。EasyNet 里再加「我的设备」会出现两个入口维护同一份状态；是做成 EasyNet 里的一页（复用宿主接口）、还是只放一个跳转链接。

## 6. 建议的执行顺序（阶段 B 起）

不依赖上面三个决定的，可以先做：

1. B1 接通三个无入口页面（G1）——纯界面改动，任何 IA 下都需要。
2. B2 下载失败原因翻译 + 续传不支持提示 + 打开文件 + 全局并发/重试设置（O3、G6-G8）。
3. B3 状态轮询减重与 `state.json` 写放大（O1、O2）。
4. B4 「检查网络」一键诊断与结论生成（G3、G4），先写场景测试再实现。
5. B5 浏览器下载并入统一队列（M1）。
6. C 设备互联入口（G10，待决定 3）。
7. D 虚拟局域网（G11，待 EasyTier 许可与内核分发评估）。

---

## 7. 阶段 B 实施记录（2026-11-23）

### 已决策

| 问题 | 决定 |
| --- | --- |
| 界面信息架构 | 按 PRD 重排：左栏 概览 / 下载 / 互联 / 诊断 + 独立设置入口 |
| 系统修改授权 | 保持现状（`auto_allow` + 快照 + 可恢复），不恢复逐次确认 |
| 设备互联归属 | 只放跳转链接到宿主「设备连接」页，不在插件里重做 |

### 已改

1. **接通三个断头页面**（G1）：新增 `ui/src/SettingsView.vue`，六个分区（加速 / 代理与线路 / 网络与 DNS / 连接 / 防护 / 高级与记录）全部可达；`NetworkApp.vue` 重排为四视图 + 设置入口。
2. **概览补齐**（G2、O7 部分）：`HomeView.vue` 新增网络状态带（连接方式、本机地址、网关、最近检查、最近事件）与「检查网络」「我的设备」入口；累计流量仍来自系统接口，标签未改口径（见未改）。
3. **互联页**（G10、M2）：新增 `ui/src/InterconnectView.vue`，只做设备入口、文件互传说明、本机局域网地址与邻居数量；私人网络标注「尚未提供」。跳转用 `sunday:open-app-page` 事件，宿主 `LamToolsApp.vue` 加白名单监听后调用既有 `openFullArea`。
4. **一键检查网络**（G3、G4）：`controller/src/observe.rs` 新增 `network_diagnose`，`diagnose` 支持 `kind:"network"`；五层真实探测（本机网卡、网关 TCP、系统 DNS + DoH 交叉验证、两个公网 IP 的 TCP、系统代理端口监听），按失败所在层生成结论与建议。站点检查也改为分层结论（DNS 失败 / 端口不通 / 5xx / 证书）。
5. **下载失败原因与续传提示**（O3、G8）：`engines.rs` 新增 `aria_error_text`，`transfer.list` / `status` 的失败任务带 `errorText`；`errorCode=8` 标 `canResume:false`；`TransferView.vue` 直接显示原因。
6. **打开文件**（G6）：`session.mjs` 暴露宿主 `openFile`，完成的任务行可「打开文件」。
7. **全局下载设置**（G7）：`settings.update` 支持 `download:{concurrency,max_tries,bytes_per_second}` 并校验；内核启动读取该设置，运行中通过 `changeGlobalOption` 就地更新并发与全局限速；下载页新增「下载设置」面板。
8. **去重**（O4、M3、M4）：加速页的网站检查表单改为跳转诊断页；代理页与节点列表的重复订阅入口合并为一个（空状态保留上下文入口）。
9. **测试与实现对齐**：`core/ui/tests/network-redesign.test.mjs` 的 rpc 前缀从已废弃的 `network-exploration.` 改回 `easynet.`（此前 18 条用例因前缀漂移一直失败）；`core/tests/test_network_*.py` 的插件名与操作前缀同步为 `easynet`；manifest 用例改为断言「只声明自己那一份工具」。

### 验证

| 范围 | 结果 |
| --- | --- |
| Rust 控制器 | `cargo test` 39 通过（新增错误码翻译、失败任务可读原因、下载设置校验、代理地址解析） |
| 插件界面 | `npx vitest run tests/network-redesign.test.mjs tests/network-plugin-ui.test.mjs tests/network-ia-settings.test.mjs` 43 通过（新增 9 条：四视图、设置分区可达、互联跳转、下载失败原因、全局设置、一键检查网络、概览状态带） |
| 宿主装配（Python） | 7 通过 / 3 未通过：`test_host_controls_one_rust_service_and_persistent_state`、`test_real_aria2_*`、`test_integrated_mihomo_*` 在离线环境里报 `operation ... is not registered`。原因是 `PluginHost.available()` 对声明了 backend 的插件要求存在 backend manager，临时宿主没有；与本次改动无关，属于测试环境耦合 |
| 构建 | `npx vite build --config vite.config.network-plugin.ts` 成功（page.mjs 960 KB） |

### 未改（仍待做）

- G5 下载完成通知：宿主 `PluginPageContext` 没有通知通道，需要宿主侧先加能力，本次未伪造。
- M1 浏览器下载并入统一队列：`browser/download.rs` 仍是独立三态实现。
- O1/O2 轮询与写放大：`status` 仍返回 `history`+`reports`+`events` 全量，下载进度变化仍整份写 `state.json`。
- O8 术语：DoH / hosts / 线路兜底 / 并行数量 / SHA-256 仍未解释。
- O9 零检查项时可能显示「检查通过」：未加守卫。
- G11 虚拟局域网：未开始，需要 EasyTier 许可与内核分发评估。
