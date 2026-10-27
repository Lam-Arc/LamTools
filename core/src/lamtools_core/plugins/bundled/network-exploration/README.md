# Network Exploration · 网络拓展

<!-- user:“实现这个插件，也正好实验我们的新插件架构”+(记录实际实现、验收与尚未交付的范围，不把方案目录当作已完成功能)。 -->

Sunday 的 Windows 桌面内置网络插件。完整界面由插件自己绘制，左竖栏、右侧快捷面板、插件配置与分屏使用同一个 Rust 后台。

<!-- user:“常用功能放在首页 切梯子/网络加速”+(新版首页优先提供网络加速开关、真实线路列表和网站检查，不要求进入参数配置页)。 -->

0.2.3 界面采用与 Sunday 主题接壤的浅色/深色自适应工作台。插件直接继承宿主的 `--theme-main-*`、`--theme-main-border`、`--green` 和字体变量，不再自带一套独立的深色色板。左侧固定四个入口：首页、加速、代理、下载；首页是一条实时数值 bar 加加速/代理/下载三个快捷操作块，数值 bar 显示下载、上传、累计流量和线路延迟，三个块内可直接开关加速、开关代理或粘贴链接开始下载。

## 已实现

- 系统接口上传/下载采样、近期速度曲线、接口/DNS/默认路由查询。
- TCP/UDP 连接、进程、端口查询与筛选；已知局域网邻居查询。
- 系统 DNS、Cloudflare / Google DoH 查询与耗时；DNS → TCP 候选地址 → TLS/HTTP 检查，可附加 Ping 或路由跟踪。
- Mihomo 配置导入、HTTPS 订阅更新、节点/分组/规则查看、节点选择、延迟测试和一键选择最快可达线路、直连/规则/全局模式。自动选线只做延迟测量，不宣称带宽测速结果。
- aria2 HTTP/HTTPS 下载、并发分段、队列、暂停/继续/取消、优先级、任务限速、代理出口、SHA-256 校验。
- 下载状态持久化，插件重启后恢复为暂停状态，继续使用原文件及 `.aria2` 记录。
- 本机加速：本地 HTTP CONNECT 代理，命中 GitHub、Steam、Twitch、Spotify 等常用域名时用 DoH 选 A 记录并直连；不改 hosts、不装证书、不需要订阅。
- 经宿主审批后的当前用户系统代理、指定接口 DNS、应用出站防火墙规则、应用上传 QoS。
- 修改前加密快照、实际配置核对、失败恢复、重启恢复；发现外部修改时保留现场。
- 定时只读诊断、试运行、事件记录与报告导出。
- Agent Skill 和 `core network-exploration call` 命令；没有新增 Agent 工具或第二个 Agent Loop。

## 使用

左竖栏的网络入口打开完整界面；右键可选择分屏。右侧快捷面板是三行胶囊：加速开关、代理开关、下载入口；整行可点，状态显示在右侧，点下载会直接落到下载页。配置页也使用相同界面。

<!-- user:“左侧入口就保留3个就行 加速 代理 下载”“把操作傻瓜化”+(左侧只保留三个常用入口，其余页面从卡片内部进入)。 -->

插件自己的左侧导航固定为“首页 / 加速 / 代理 / 下载”四项。检测、网络、连接、防护和定时检查不再占用左侧入口，仍可从首页或加速页进入。添加订阅不需要先手动关闭代理：保存时会自动断开当前连接，保存后自动重连并刷新节点。

首页和加速页的“一键加速”只启动本机加速：

- **本机加速**：启动本地 HTTP CONNECT 代理，命中 GitHub、Steam、Twitch、Spotify、mod.io 等常用域名时用 DoH 解析 A 记录并直接连候选 IP，TLS 原样透传；不需要订阅，不改 hosts、不装证书。有订阅时自动准备线路内核做兜底，但不会改系统代理；TLS 首包失败时回退线路并记住该域名 30 分钟，后续优先走线路。
- **线路、订阅和选节点**都在代理页；加速页不再提供“线路加速/本机加速”模式切换。

### 下载工具

插件向 agent 提供一个 `network_download` 工具，复用现有 aria2 队列：

- `url`：HTTP/HTTPS 链接，必填。
- `directory`：绝对保存目录；不传则使用插件私有下载目录。
- `foreground`：`false`（默认）立即返回任务号；`true` 等待完成、失败或达到 `wait_seconds`。
- `wait_seconds`：前台等待上限，默认 300 秒，最多 900 秒；超时后下载继续在后台运行。
- `filename`、`connections`（1–16）、`proxy`：可选。

工具声明为 `ask_user`，因为会写入用户指定目录。

<!-- user:“本机加速层 你学习一下呗…它该抄就抄”+(按 FastGithub/Watt Toolkit 的思路实现本地 CONNECT + DoH 选路，不复制其源码)。 -->

本机加速的域名匹配、CONNECT 隧道和 DoH 选路思路来自 FastGithub（MIT）和 Watt Toolkit（GPL-3.0）的公开实现；这里的 Rust 代码是重新实现的，没有复制它们的源码。它只对使用系统代理的应用生效，也不能绕过网络层对目标 IP/SNI 的直接阻断或 Cloudflare 人机验证；这类目标需要在代理页选一条可用线路，界面不会把直连标成成功。

代理页的“当前线路”卡片可以切换节点或点“选择最快”。自动选择只测量该分组内真实节点的延迟，按最低延迟切换；`DIRECT`、`REJECT` 等内置目标不参与，全部失败时保留当前线路，也不会修改系统代理设置。这里的“最快”指本次延迟测量最低，不代表带宽或稳定性最好。

Mihomo 与 aria2 **随插件提供**，固定版本并校验 SHA-256，使用时自动准备运行副本。用户不用安装运行库、Python、Rust 或额外的网络工具 GUI。Rust/Python 仅为开发构建要求。

代理默认只监听 `127.0.0.1:17890`，不会自动设置系统代理或启用 TUN。导入 YAML 或订阅后点击启动；需要接管当前用户系统代理时再执行面板中的审批操作。导入配置中的局域网监听、外部管理界面、脚本和额外监听器会被移除；提供器限定 HTTPS 并改写为插件私有缓存路径。

系统修改需要 Windows 赋予相应权限，插件不自动永久提权。桌面端的一键加速与停止会直接应用/恢复系统代理，不再逐次弹出审批；只放开 `system.apply` 与 `system.restore`，其他系统修改仍按原权限处理。接口 DNS 会同时保存静态/自动获取模式；恢复时不会把旧 DHCP 地址固化成静态配置。Windows QoS 限速当前仅控制应用发送流量。

下载文件默认保存在插件运行数据的 `downloads`，也可指定绝对目录。目标文件已存在时拒绝新建同名任务；恢复已有任务使用“恢复已保存任务 / 继续”。取消任务保留已经下载的文件，不静默删除用户数据。

## 开发构建与分发

在仓库根目录运行：

```powershell
python scripts/prepare-network-plugin.py
```

脚本自动下载并验证固定版本的内核、保存许可证，使用锁定依赖构建 release 控制器。正式 Windows 后端打包已在 PyInstaller spec 中调用相同脚本。也可使用 `scripts/build-network-controller.ps1 -DebugBuild` 进行本地开发。

界面源码位于 `ui/src/`。仅修改界面时，在 `core/ui` 执行 `npx vite build --config vite.config.network-plugin.ts`，生成插件目录中的 `ui/page.mjs` 与 `ui/style.css`。生产构建和控制器开发构建也会执行这一步。`ui/store.mjs` 保持独立模块，主页面和右侧快捷面板共用同一状态订阅。

生成的可执行文件不进入 Git；`controller/Cargo.lock`、内核来源、许可证及校验记录进入 Git。正式分发必须通过上述构建，不可只复制源目录后宣称运行资源齐全。

| 组件 | 固定版本 | 许可证 | 来源 |
| --- | --- | --- | --- |
| aria2 | 1.37.0 Windows x64 | GPL-2.0-or-later | https://github.com/aria2/aria2/tree/release-1.37.0 |
| Mihomo | 1.19.33 Windows amd64 compatible | GPL-3.0 | https://github.com/MetaCubeX/mihomo/tree/v1.19.33 |

原始压缩包的 SHA-256 固定在 `engine_install.py`。aria2 校验来源为微软 winget 清单；Mihomo 为对应官方 GitHub Release 的 asset digest。每次执行前还检查运行副本的二进制哈希。

## 接口与数据

UI / CLI 调用 `network-exploration.<method>`。入口清单见 `operations.json`。除 `system.apply`、`system.restore` 必须通过宿主审批外，其余接口不修改系统全局网络配置。

`status` 返回统一快照及配置版本；`settings.update`、`rules.save`、`automation.save` 必须带 `revision`。过期版本被拒绝，避免不同面板互相覆盖。`rules.save/test` 当前为独立匹配预览；实际代理路由由导入的 Mihomo 规则执行，二者不会假装自动同步。

```text
core network-exploration call status
core network-exploration call diagnose --arguments-file E:\temp\diagnose.json
```

诊断参数示例：`{"target":"github.com","port":443,"kind":"basic"}`。命令连接运行中的 Sunday，不新建网络服务。使用 `--base-url` / `--ws-path` 或现有 Sunday 环境变量选择桌面后台。

数据位于宿主 `data_dir/plugins/network-exploration/data`（若宿主提供 `app_data_dir`，优先使用它）。内置源目录保持只读，运行数据不会经插件资源接口对外提供。目录 ACL 限定当前 Windows 用户与 SYSTEM。订阅配置、下载地址和配置快照使用当前账户 DPAPI 加密；换 Windows 账户后不能直接解密。

控制器使用独占锁；全部受控进程加入 Windows Job，宿主崩溃后不遗留内核子进程。正常退出先恢复插件配置、暂停并正常关闭 aria2。异常退出留下的事务会在下次启动检查；无法确认所有权时保留快照并要求核对。无法恢复的事务会阻止直接卸载。

## 验证与当前边界

新增验收覆盖真实宿主 WebSocket / 插件资源接口、共享控制器、审批、防重放、并发设置、页面清理、DPAPI、Mihomo 本地转发，以及 aria2 下载暂停、重启续传和最终文件哈希。系统配置变更的安全逻辑使用代码测试，未在开发机实际修改 DNS、防火墙或 QoS。

这次交付是可运行的基础版本，**没有完成原方案 P0–P6 的全部功能**。以下尚未实现，界面也不会伪造成功：浏览器下载接管扩展、上传与跨设备同步、需要证书的透明反向代理（本机 CONNECT 加速已实现）、DoT、DNS 缓存/Hosts 管理、TUN/路由/WFP、系统应用下载限速、应用级字节统计、长期日周月流量归档、多源一致性下载、基于吞吐量的出口优化、网络变更触发和自动修复闭环。

邻居表不是主动局域网扫描，未知进程不等于恶意进程，ICMP 不响应不等于连接不可用，Mihomo 流量不等于系统全局流量。诊断仅输出真实测量和明确标注的建议。
