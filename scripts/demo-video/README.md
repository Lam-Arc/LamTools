# Sunday 演示视频流水线

用脚本驱动真实的 Sunday 窗口，把一次真实的模型调用录下来，之后按可控节奏
稳定重演，最后用代码动画与镜头语言成片。

不碰产品代码、不碰你正在用的会话与配置：演示实例有独立的标识、端口、数据库、
配置副本与工程目录。

## 三段式

```
录制  真实跑一遍            →  takes/<take>/cassette/   （请求、响应字节、时序）
回放  照原样重演（节奏可控）  →  takes/<take>/frames/     （逐帧画面 + 时间戳）
成片  代码动画 + 镜头语言     →  takes/<take>/clip.mp4   →  主片
```

### 1. 录制：真实跑，全部留痕

模型接口指向本机代理，代理把**原始字节**和**分块到达时序**存进 cassettes。

```powershell
# 起代理（录制模式）
powershell -NoProfile -File scripts/demo-video/env/proxy.ps1 -Mode record -Take calendar
# 驱动窗口演一遍
node scripts/demo-video/driver/run.mjs --take calendar --beat calendar
```

录制模式从 0 开始编号，**绝不覆盖**已存在的记录：take 目录里还有 cassette 时再起录制代理会直接报错退出（发生过一次覆盖事故）。一趟一个 take 目录；录制中断想续录就换新目录。

### 2. 回放：稳定重演，节奏可控

同一个地址（演示配置里的 provider 指向本机代理），换代理的运行模式即可：

```powershell
powershell -NoProfile -File scripts/demo-video/env/proxy.ps1 -Mode replay -Take calendar `
  -ChartPace 12 -TtfbMs 500
```

节奏参数（按需组合，互不冲突）：

| 参数 | 作用 |
|---|---|
| `--speed N` | 按录制时序整体加速 N 倍（默认 1） |
| `--chars-per-second N` | **按可读字速**匀速吐字（推荐；短回答不会一闪而过） |
| `--tokens-per-second N` | 按分块数匀速（分块≈token） |
| `--chunk-interval-ms N` | 固定分块间隔 |
| `--ttfb-ms N` | 固定首字延迟（默认 -1 = 沿用录制的，并用 `--max-ttfb-ms` 封顶） |

### 3. 校验：重演必须与录制一致

回放结束后比对两个数据库快照里最新会话的消息序列，逐字一致才算通过：

```powershell
py -3.14 scripts/demo-video/verify.py --record <record 快照> --replay <replay 快照> --verbose
```

不一致就是失败——宁可报错，也不让跑歪的画面进成片。

### 4. 成片

```powershell
py -3.14 scripts/demo-video/compose/frames-to-video.py --take <take> --fps 60
```

## 另一条路：真实前端渲染（stage/，现在的主用路径）

上面那三段（录制 → 回放 → 采集）是为了**拿到一次真实跑出来的内容**。
画面本身不必录屏：`stage/` 把真实的 `core/ui` 应用挂在无头浏览器里，用一张时间表
喂状态，逐帧截图。

```powershell
node scripts/demo-video/stage/capture.mjs --scene first-look              # 出片
node scripts/demo-video/stage/capture.mjs --scene first-look --at 4,12.5  # 只取静帧
```

为什么主用它：

- **不碰桌面、不碰你的实例**：没有窗口、不需要前台、不在意遮挡与缩放。
- **帧确定**：同一帧两次渲染逐字节相同（PPT 式动画靠 CSS 的地方全部关掉，时钟钉死）。
- **任意宽度是真的响应式**：产品被关在一个真实尺寸的盒子（iframe）里，改盒子 = 产品的
  真实重排，不是把画面缩小。
- **节奏随意**：想快想慢改时间表，不用重跑任务。

方法、写法、确定性的规则与陷阱都在
[`stage/README.md`](stage/README.md)。录屏那条路保留下来做**取内容**用：真实跑一遍，
把对话与产物拿回来，再喂进 stage 重演。

## 目录

| 路径 | 作用 |
|---|---|
| `env/start-app.ps1` | 起演示实例（独立标识/端口/数据库/配置副本） |
| `env/window.ps1` | 定位/调整/激活演示窗口（`-Info` 查看几何） |
| `env/reset-demo.ps1` | 复位演示工作区（`-Fresh` 连数据库一起清） |
| `env/proxy.ps1` | 起录制或回放代理 |
| `env/tauri.demo.conf.json` | 演示实例的 Tauri 覆盖配置（独立标识 + 调试端口） |
| `proxy/proxy.py` | 录制/回放代理本体 |
| `proxy/cassette.py` | 磁带格式与请求分类（主循环 / 标题等辅助调用各一条队列） |
| `proxy/test_proxy.py` | 代理自测（字节一致性、节奏缩放、跑超报错、严格模式） |
| `driver/sunday.mjs` | 连接窗口、动作记录、采集 |
| `driver/run.mjs` | 桥段运行器（布局、前台校验、采集、报告） |
| `driver/probe.mjs` / `tune.mjs` | 几何与帧率探针（排查采集问题用） |
| `driver/look.mjs` | 看一眼当前窗口并落一张图（debug 用） |
| `beats/*.mjs` | 各桥段的驱动脚本 |
| `verify.py` | 回放等价性校验 |
| `compose/frames-to-video.py` | 帧序列 → 视频 |

## 这台机器上的既有约束（踩过的坑）

1. **窗口必须铺满屏幕并保持前台**。合成点击走系统输入通道：窗口被别的窗口盖住，
   或者点击落在屏幕可视区域之外，都会被静默吞掉——桥段会卡在"元素可见却点不动"。
   `driver/run.mjs` 每次运行都会调整窗口并校验 `document.hasFocus()`，不满足就报错。
2. **排版尺寸不要超过窗口的可视区域**。本机是 2K 屏（2560×1440），系统缩放下
   网页可视区只有约 1375×773 CSS 像素；把排版视口撑得比它大，超出部分虽然能渲染，
   却点不到（就是第 1 条的陷阱）。所以演示直接用窗口自身的全屏尺寸排版，
   不做设备指标模拟：输入、排版、采集三者天然一致。
   帧尺寸 = CSS 视口 × 真实像素比，全屏 2K 下约 2544×1431。
3. **屏幕与缩放要按真实值算**：显示设置里的"缩放"会让系统上报的屏幕尺寸变小
   （2560×1440 @125% 上报成 2048×1152），照着上报值设窗口大小就会"窗口化"。
3. **CDP 截屏只在画面重绘时出帧**。空闲窗口几乎不出帧，所以采集期间注入一个
   1px 的 rAF 心跳元素，保证稳定 98fps 的帧供给；`everyNthFrame` 参数会把帧生产
   卡死，不要用。
4. **应用有单实例保护**（按 bundle 标识），所以演示实例有自己的标识，
   否则一启动就自己退出。
5. **后端会校验浏览器来源**，演示开发端口要通过
   `LAMTOOLS_CORE_ALLOWED_ORIGINS` 加进白名单（`start-app.ps1` 已处理）。
6. **模型供应商配置在演示副本里**指向本机代理（`http://127.0.0.1:8790/provider/v1`），
   录制与回放共用同一个地址，靠代理的运行模式切换。
7. **会话带的模型有记忆**：新建会话通常已经继承了上次选的模型，
   桥段里先读触发条文字，已经是目标模型就不要再去点菜单。

## 现状

- 阶段 A（最小桥段「录制 → 回放 → 采集 → 成片」）已跑通并校验通过。
- 采集指标：排版 1440×900、帧 2032×1144、活动时 98fps、约 100KB/帧。
- 真实接口实测首字延迟约 38 秒（这就是必须回放的原因）。
