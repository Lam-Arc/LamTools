# Sunday 桌宠 V1.0｜实现说明、验收与限制

> 对应需求：`01_Sunday_桌宠_V1.0_设计方案.md`、`02_Sunday_桌宠_V1.0_功能清单.md`
> 实现日期：2026-10-30。本文说明**实际做成了什么、怎么跑、哪里还没做到**，不谈设想。

## 1. 集成方式（最小侵入）

桌宠不是插件市场里的独立应用，也不是重写主界面：

| 层 | 改动 |
|---|---|
| 新增文档 | `core/desktop/pet.html` + `core/desktop/src/pet.ts`（覆盖层独立页面，已加入 Vite 多入口） |
| 新增窗口 | Rust 运行时创建 `pet-overlay` 窗口，横跨虚拟桌面，透明、无边框、不进任务栏、不抢焦点 |
| 新增模块 | `core/ui/src/pet/**`（引擎 + 渲染 + Agent 桥 + 覆盖层界面），主界面组件一行未改 |
| Rust 命令 | `core/desktop/src-tauri/src/pet/{mod,platform}.rs`，24 个 `pet_*` 命令 |
| 启动入口 | 托盘菜单「打开桌宠」；`pet_autostart` 在启动时按配置恢复上次状态 |
| 复用 | `MessageView.vue`、`CoreAppServerClient`、`createCoreAppServerRuntimeController`、`submitCoreComposerTask`、`selectVisiblePendingDecisions`、`/sessions/{id}/attachments` 上传、主题玻璃变量 |

主界面保持原样：桌宠关掉、禁用、崩溃都不影响主窗口；反过来主窗口藏到托盘后桌宠照常工作。

## 2. 代码地图

```
core/desktop/pet.html                     覆盖层页面（透明底）
core/desktop/src/pet.ts                   入口，挂载 PetSurface
core/desktop/src-tauri/src/pet/mod.rs     窗口、命中区、截图、快捷键、角色包、配置、自启
core/desktop/src-tauri/src/pet/platform.rs Windows 原生：多屏/DPI/光标/GDI 截图/EnumWindows/热键轮询
core/ui/src/pet/bridge.ts                 Tauri 命令的薄封装 + 资源 blob 缓存
core/ui/src/pet/config.ts                 配置 v1 + 迁移
core/ui/src/pet/engine/{math,terrain,physics,actions,nav,behavior,sprite,pet,world}.ts
core/ui/src/pet/render/{types,threeLayer}.ts  渲染适配层：2D 取帧规则 + Three.js GLB/glTF/VRM
core/ui/src/pet/render/{blocky,blockyRig,blockySkin}.ts  内置方块人：皮肤 UV、盒式骨架、姿态
core/ui/src/pet/render/occlusion.ts        局部遮挡：按真实窗口矩形生成裁剪切图
core/ui/scripts/make-stickman.mjs          生成带骨骼与四段动画的 GLB 测试角色
core/ui/src/pet/assets/importer.ts        pet.json 校验、格式识别、动作名建议
core/ui/src/pet/assets/zip.ts             .sundaypet 解包与白名单校验
core/ui/src/pet/agent/{client,host}.ts    项目/会话发现、会话通道、两套绑定路由
core/ui/src/pet/ui/*.vue                  覆盖层界面（舞台/环/标记动画/标注/卡片/气泡/预览器/设置/菜单）
core/ui/src/pet/ui/pingModel.ts           轮盘分层与扇区命中（纯函数，可单测）
core/ui/tests/pet-engine.test.ts          引擎回归 29 条
core/ui/tests/pet-render.test.ts          渲染选择/动画映射/轮盘逻辑 15 条
core/ui/tests/pet-zip.test.ts             .sundaypet 校验 9 条
core/ui/tests/pet-config-import.test.ts   配置迁移与角色包校验 13 条
core/ui/tests/pet-isolated-e2e.test.ts    隔离真实后端 E2E 9 条
```

## 3. 关键实现决定

### 3.1 坐标系只有一个：物理像素

覆盖层横跨所有显示器，窗口内的 CSS 像素会被单一 DPI 缩放。为避免"多屏 + 混合 DPI 下角色位置漂移"，**引擎、物理、地形、命中矩形全部用物理像素屏幕坐标**，画布按物理尺寸绘制，UI 再除以窗口缩放换算成 CSS。Rust 报上来的光标、命中矩形因此可以直接和引擎数字比较。

### 3.2 点击穿透：命中矩形 + 8ms 轮询

整窗覆盖全屏，但默认 `set_ignore_cursor_events(true)`。前端把"角色、气泡、卡片、轮盘"的矩形按物理像素报给 Rust，轮询线程只在**状态翻转**时切换窗口是否吃鼠标。所以角色以外的区域（PDF、浏览器、桌面图标）照常点击。

拖拽期间强制 `input_mode=capture`：鼠标甩出角色矩形也不会中断抓取。

### 3.3 截图不含桌宠自己

覆盖层开启 `WDA_EXCLUDEFROMCAPTURE`（Windows 10 2004+），GDI 截图永远拍不到桌宠、轮盘与卡片。**这是降级的边界**：更旧的 Windows 上该 API 无效，截图可能带进覆盖层，代码只打日志、不假装成功；设置面板里有截图失败原因。

### 3.4 遮挡：三档，如实声明

- `top`：置顶，总在窗口之上（默认）。
- `clip`：**置顶 + 按窗口几何裁剪**（推荐）。每 1.2 秒枚举一次真实窗口矩形，转成 SVG 遮罩挖掉宠物画布对应的那片。桌宠走到窗口后面就被窗口"挡住"，而卡片、气泡、Ping 轮盘仍然在窗口之上（遮罩只作用在画布容器上）。
- `behind`：`SetWindowPos(HWND_BOTTOM)`，整层压到普通窗口之下，一次被挡全部。

`clip` 的边界：窗口重叠处按 evenodd 会"恢复可见"，属于多窗口叠加的边缘情况；一个窗口无法做到真正的逐像素 Z 序混合，这是单窗口方案的系统上限。三档都在设置里可切换，不宣称"完全真实遮挡"。

### 3.5 内置方块人预设与换肤

首次打开桌宠时自动安装一个可直接用的角色，不需要用户先准备素材：

- **模型**：不依赖外部文件，渲染层按 32 个模型单位现场搭盒式骨架（头 8³、body 8×12×4、四肢 4×12×4，Alex 用 3 宽手臂）。
- **皮肤**：严格按 Minecraft 64×64 标准网格做盒面 UV，正面/侧面/顶底各自对位；默认皮肤是**画出来**的（不打包第三方皮肤）。
- **动作**：待机、行走、跳跃、开心跳、下落、攀爬、悬挂、休息、跳舞、互动全部程序化姿态；走路按固定节奏播放（不按移动速度倍速）。
- **换肤**：设置里「导入皮肤…」选一张 PNG/JPG/WEBP，写入角色包 `skins/` 并立刻重建渲染实例；模型、动作、碰撞体、行为配置一律不动。「恢复默认皮肤」随时回来。
- 角色包落在 `{lam_home}/pet/packs/sunday-blocky/`，含 `skins/default.png` 与 `pet.json`；配置里的 `presetInstalled` 保证用户删掉后不会被自动加回。

### 3.5 物理主导、Action 只提交意图

- 固定步长 1/120，渲染帧率不参与物理。
- 跳跃 = 在既有速度上叠加冲量；悬挂松手保留切向速度（单测断言 `velocity.x` 不变、形成抛物线）。
- 抓取是弹簧-阻尼：位置滞后于鼠标，释放继承真实速度，上限由 `maxSpeed/maxAccel` 兜住，不是突然归零。
- 动画按物理阶段（上升/顶点/下降/落地）取帧，不用动画时长决定落地。

### 3.6 寻路：先验证可达，再算代价

节点/边 = 瓦片网格上的走、爬、挂、跳、落。**跳跃边用同一套物理常量校验真实高差与水平射程**，落点必须真的落在目标站瓦上才生成。代价按设计表：一瓦片=1，走=1、跳=|dx|+|dy|、爬=2、挂=3、落=(|dx|+|dy|)/2；鼠标附近偏好只参与目标挑选，不进 A*。

搜索有节点上限、展开上限和 14ms 时间预算，超了返回 `budget` 而不是卡死主线程。

### 3.7 会话：一个会话一个通道

每个会话一张卡片对应一个 `SessionChannel`：独立 fork 的传输 + 独立 `CoreAppServerClient` + 独立运行时控制器。因此

- 同一会话的多条 Ping 进同一张卡（卡片按 `sessionId` 去重）；
- 不同会话各自保留流式状态与草稿；
- 审批通过 `approval/respond` 带显式 `thread_id` 回到原请求，不在本地模拟。

发送走 `submitCoreComposerTask`：会话忙时按 Sunday 现有机制排队或引导，不中断上一条。

### 3.8 判定框、点击域与穿透同源

- **物理判定框**：60×120 的 AABB（脚底锚定），只负责地形碰撞；相对精灵框约 75% 高，与泰拉瑞亚"碰撞体小于绘制体型"的约定一致。
- **脚底锚定渲染**：3D 正交相机世界可见 `[0, 1.05]`，世界 y=0 正好落在精灵框底边——角色脚底、物理 AABB 底边、平台表面三者重合，不再悬空约 8px。
- **点击域 = 画出来的 Hitbox = 穿透矩形**：交互 Hitbox 以精灵框归一化（`hitboxWorldRect` 统一处理朝向镜像），`world.hitTest`、`clickAt`、调试框、上报给 Rust 的命中矩形全部用同一份世界矩形；透明边距不再吃鼠标。
- **拖拽保留抓取偏移**：在角色哪个位置按下就抓着那个位置走，不会把脚底吸到光标上导致整体上跳。

## 4. 默认参数（可改，不改变交互语义）

| 项 | 默认值 | 位置 |
|---|---|---|
| Ping 快捷键 | `Ctrl+Alt+Space` | `config.ping.hotkey` |
| 轮盘半径 / 环宽 | 132px / 14px（细环） | `config.ping.radius/ringWidth` |
| 默认扇区 | 提问 ?、注意 !、记录、框选、对话、切换会话 | `config.ping.sectors` |
| `?`/`!`/`记录` 提示词 | 三条独立固定模板，可在设置里逐条改 | `DEFAULT_PING_PROMPTS` |
| 标记时长 | 2400ms（只用于标记文案，不阻塞请求） | `config.ping.markerMs` |
| 「对话」自动附截图 | 开 | `config.ping.autoAttachScreenshot` |
| 气泡策略 | 提问/审批=弹出，普通回复/完成=标记 | `config.bubbles` |
| 同时展开气泡 | 1 | `config.bubbles.maxExpanded` |
| 渲染上限 | 60 FPS | `config.perf.maxFps` |
| L3 刷新 | 30s | `config.perf.l3RefreshMs` |
| 重力 / 跳跃冲量 / 走速 | 2400 / 1120 / 260（物理像素/秒） | `engine/physics.ts` |
| 碰撞半径 | `min(宽,高) × 0.38` | 导入时自动估算 |
| 地形精度 | low / balanced / high（最短边 96/64/40，容差 6/3/2） | `QUALITY_PRESETS` |

配置带 `version: 1`，读旧配置时补默认值并回写；坏 JSON 回落后端默认并提示，不覆盖用户其他字段。

## 5. 角色包

### 5.1 目录与 `pet.json`

```json
{
  "schema_version": 1,
  "name": "Mixed",
  "preview": "preview.png",
  "scale": 1,
  "actions": {
    "idle": { "source": "idle.png", "type": "static" },
    "walk": { "source": "anim/walk.png", "type": "spritesheet",
              "frame_width": 64, "frame_height": 64, "frame_count": 6, "fps": 10 },
    "jump_happy": { "frames": ["j/h1.png", "j/h2.png"], "type": "frames", "fps": 12 }
  },
  "physics": { "radius": 28 },
  "hitboxes": [{ "id": "head", "name": "头", "x": 0.3, "y": 0.0, "width": 0.4, "height": 0.3,
                 "action": "interact_head", "enabled": true }]
}
```

- 每个动作可以引用**不同格式**：静态图、序列帧、图集。
- 没写 `pet.json` 也能导入：识别序列帧（`walk_0.png`…）与单图。
- 缺某个动作的动画时，Action 执行器按 `fallback` 回退，物理照常（`ASSET-09`）。

### 5.2 安全

- 路径：拒绝绝对路径、盘符、`..`、冒号段；读取时再 `canonicalize` 并校验仍在包根内。
- 类型白名单：`png/jpg/jpeg/webp/gif/bmp/svg/glb/gltf/bin/atlas/txt/md/ogg/mp3/wav/vrm/vrma/inp/plist/skel/json`；`js/py/exe` 一律拒绝。
- 规模：≤ 800 文件、≤ 160MB 总量、单文件 ≤ 64MB；不跟随符号链接。
- 角色包**不含任何可执行逻辑**，只有资源与 JSON 描述。

### 5.3 实际支持的格式

| 格式 | 状态 |
|---|---|
| 静态 PNG/JPG/WEBP/GIF/BMP | 可用（单图即最小角色，已单测） |
| PNG 序列帧 | 可用（按文件名数字排序、fps/循环可配） |
| Spritesheet / 图集 | 可用（帧宽高、帧数、列数、帧范围） |
| glTF / GLB | **可用**：Three.js `GLTFLoader` 解析，骨骼/蒙皮/动画片段可播；动作名按"精确 → 别名 → 退第一段"匹配，回退会写进诊断；每只宠物独立 mixer 与克隆骨架 |
| `.sundaypet`（ZIP） | **可用**：fflate 内存解包、剥公共顶层目录、过滤 `__MACOSX` 噪音、路径/类型/体积三重校验后二进制整包写入 |
| VRM | **可用**：`@pixiv/three-vrm` 的 `VRMLoaderPlugin` 挂在同一套 `GLTFLoader` 上；VRM 0.x 自动 `rotateVRM0` 修正朝向；骨骼/表情由 three-vrm 驱动，mixer 逻辑与 GLB 共用 |
| FBX / VRMA / Inochi2D / DragonBones / Live2D / Spine / Rive / Lottie | **未实现**，导入时逐条列出，不静默丢弃 |

渲染分工：`static/frames/spritesheet` 走 Canvas 2D；`model` 走 Three.js 层（一块独立透明 WebGL 画布，逐宠物用视口+裁剪绘制，位置来自引擎 `renderState`）。两者都可以同时存在于一只角色上（不同 Action 用不同格式），互不干扰。

Three.js 是**动态 import**：没有 3D 角色时不加载（构建产物里 `three.module`/`three.core`/`GLTFLoader` 是独立懒加载块）。

## 6. 启动与手工验收

```powershell
# 1) 启动（完全退出旧实例后再来）
cd core/desktop
npm run tauri dev
# 2) 托盘菜单 → 打开桌宠
# 3) 覆盖层里右键角色 → 桌宠设置 → 导入角色文件夹
#    选 core/ui/pet-assets/arc-ball（里面有多张 PNG）
```

手工验收步骤与期望结果（对应清单条目）：

1. **导入**：设置 → 导入角色文件夹 → 预览器出现回形半圆测试场 → 角色在跑；点「点击设目标」在地图上点一下，出现路径并走过去。
2. **穿透**：把 PDF 或浏览器拖到角色旁边，点击角色以外的位置，底层窗口正常响应；点角色本体只触发互动动作，不打开菜单。
3. **抓取**：按住角色甩出去松手，角色带横向速度飞出并自然下落，有滞后和回弹感。
4. **Ping**：鼠标放到浏览器里，按 `Ctrl+Alt+Space` → 环出现（中心透明，能看见光标下的字）→ 移动到 `?` → 松手。观察：只截鼠标所在那块屏；卡片出现在同屏右侧；消息里带标记图与坐标。
5. **同会话两条 Ping**：第一条还在流式输出时再 Ping 一次 → 仍是同一张卡；第二条状态显示"已排队"。
6. **审批**：在某个绑定会话里让 Agent 触发审批 → 桌宠头顶弹出可操作气泡 → 直接点「允许」→ 主界面该请求变为已处理（不是本地假装）。
7. **关闭卡片**：点卡片 `X` → 卡片消失但 Agent 继续跑；再 Ping 同一会话 → 卡片回来还是同一会话的历史。

## 7. 已知缺口与风险（不粉饰）

| 项 | 现状 | 影响 |
|---|---|---|
| 应用"未响应"死锁（用户报告的故障 A 深层根因） | **已修复（2026-10-31，真机复现 + minidump 证据）**：页面 invoke 的同步命令跑在 WebView2 IPC 回调线程上，命令内再调 `is_visible()/hide()/show()` 等窗口 API 是同线程重入，必然死锁；桌宠就绪后立即执行的 L3 抓屏是稳定触发点。`pet_capture_monitor*`、`pet_autostart`、`pet_overlay_open/ready/close/status`、`pet_set_z_mode` 已全部改 async（见 §11） | 修复后同场景真机 50 秒以上不再挂死，覆盖层正常显示 |
| pet-dev 主窗口不可拖动（用户报告的故障 B） | **已修复（结构性）**：`tauri.pet-dev.conf.json` 不再用 `app.windows` 覆盖基础配置，窗口定义与正式版完全一致（`core/desktop/tests/pet-dev-config.test.mjs` 验收） | 拖动手感待用户在 `npm run pet:dev` 里点验（自动化不抢用户鼠标） |
| WebDriver 自动化（pet-e2e） | **已跑通（2026-10-31）**：msedgedriver 拉起应用需正斜杠路径 + `webviewOptions.userDataFolder`；应用在检测到驱动注入的浏览器参数时自行合并 `--remote-debugging-port`（wry 固定参数会顶掉环境变量）；断言改标题前缀匹配 + pet 入口预热 + FPS>0 | `npm run pet:e2e` 10 项全绿；非确定性 UI 项（拖动手感、托盘菜单点击）仍需人点 |
| VRM / FBX / 2D 骨骼格式 | 未接入运行时 | 只能用 glTF/GLB 做 3D；导入时明确列出 |
| 3D 动画混合 | 只做单动作切换 + 140ms 交叉淡入；不做表情/上半身叠加 | 与"一个时刻一个完整 Action"的产品约束一致，但不是游戏级混合 |
| 逐像素真实遮挡 | 有 top / clip / behind 三档；`clip` 按窗口矩形整体挖洞，窗口互相重叠处会恢复可见 | 不能同时"挡在 A 前、藏在 B 后"，属于单窗口系统上限 |
| 混合 DPI 多屏 | 引擎用物理像素，位置正确；CSS 文本/卡片在不同缩放屏之间可能偏大或偏小 | 视觉细节，不影响交互命中 |
| L3 视觉边缘 | 已识别水平/垂直/±45°/±27° 四个方向族；圆弧仍由折线拟合近似 | 极窄的斜边可能漏检；圆弧靠多段近似 |
| 全局快捷键 | `GetAsyncKeyState` 轮询（8ms），不是键盘钩子 | 极短按键可能漏判；不会被其他程序"吃掉" |
| 3D 首帧成本 | 首次加载模型有解析耗时（几十毫秒到几百毫秒），期间显示占位 | 只影响第一次出现的模型 |
| P2 表演 | 未实现（仅保留接口位置） | 不影响 P0 |

## 8. 自动化测试

```powershell
# 全部桌宠测试（含隔离真实后端 E2E，约 10–20 秒）
cd core/desktop
npm run pet:verify

# Rust 侧（bin 名是 Sunday，包名是 sunday）
cd src-tauri
cargo test --bin Sunday pet::
```

当前结果：TypeScript 侧 **105 条通过**（引擎 30、渲染/轮盘/遮挡 20、方块人 16、骨骼 GLB 8、ZIP 9、配置与导入 13、隔离 E2E 9）；Rust 侧 **6 条通过**（含 `--pet` 参数别名与 WebDriver 浏览器参数合并）；`vue-tsc --noEmit` 与 `vite build` 通过（`dist/pet.html` 产出）。另有：

- `node --test tests/pet-dev-config.test.mjs`（窗口定义不被 pet-dev 配置覆盖）
- `npm run pet:e2e`（WebDriverIO + tauri-driver 真机冒烟，10 项，含 FPS>0 渲染断言）

覆盖要点：自由下落落地、跳跃叠加冲量、悬挂松手保留切向速度、固定步长一致性、弹性牵引滞后、几何三分类、回形半圆测试图、多方向边识别（水平/垂直/45°）、噪音上限、共线合并与去重、Action 独立与优先级不抖动、缺动画回退、有界寻路出路径、鼠标偏好不进成本、不可达明确失败、行为目标保持、多实例独立共享地形、窗口跟随与大幅错位不瞬移、序列帧/图集取帧、多 Hitbox 优先级与物理分离、单图角色可运行、配置迁移与提示词补全、路径安全、动作名建议、混合资源包（静态图 + GLB）、不支持格式显式报告、ZIP 去公共目录/穿越拦截/脚本拦截/体积上限、渲染器选择、模型框归一、动画名映射、轮盘子层与扇区命中、方块人皮肤网格与盒面 UV、方块人动作姿态、遮挡遮罩路径、骨骼 GLB 的容器/骨架/权重/动画通道校验。

## 9. 快速体验入口

```powershell
cd core/desktop
npm run pet:dev
```

它用 `tauri.pet-dev.conf.json` 覆盖应用标识（`com.lamtools.lamcore.petdev`），因此**能和正在运行的正式 Sunday 同时存在**：不触发单实例保护、不共享 `.lam` 数据目录、不占用同一端口。启动后托盘右键 →「打开桌宠」，首次会自动装好方块人预设；设置里可导入皮肤、导入角色、切遮挡模式、改 Ping 提示词。

## 10. 隔离测试（不碰正在运行的 Sunday）

`tests/pet-isolated-e2e.test.ts` 会：

1. 在系统临时目录建 `sunday-pet-e2e-xxxx/`，把 `LAMTOOLS_HOME`、`LAMTOOLS_CORE_DATA_DIR`、`LAMTOOLS_PROJECTS_ROOT` 全部指进去；
2. 随机挑一个空闲端口，`python -m lamtools_core.cli serve --port <port>` 启动**真实** Core 后端；
3. 用 `createPetAgentClient` / `PetAgentHost` 走真实 HTTP + App Server RPC，验证：首次兜底只建一个会话、同一会话拿到同一个通道、Ping 与桌宠绑定互不改写、临时切换不落盘、线程快照可读、提交消息要么真的开始要么给出可读失败、不存在的审批 `request_id` 被后端拒绝、未知会话不会写到别人的会话；
4. 结束后 `taskkill /T /F` 收掉**自己启动的**那个 pid 的进程树并删除临时目录。

它不会连接正式实例、不会读写用户的 `.lam`、不会占用正式端口，也不需要人为点界面。后端起不来时用例**直接失败**（不允许静默跳过）。

## 11. 2026-10-31 修复轮：未响应死锁与自动化链路

**根因（用户报告"点击打开桌宠后未响应""一直未响应"的真正来源）**：Tauri 的同步命令在 WebView2 的 IPC 回调线程（即主线程）上执行；命令体内再调用 `is_visible()` / `hide()` / `show()` / `set_ignore_cursor_events()` 这类要进入 WebView2 宿主的窗口 API，就是同线程同步重入——事件循环被命令自己堵住，API 永远等不到回复，整个应用死锁。桌宠就绪后立即执行的 L3 抓屏（`useL3` 默认开启，`refreshL3` → `pet_capture_monitor_under_cursor` → `capture_with_overlay_hidden` → `is_visible()`）是每次启动必踩的触发点；`pet_autostart`、`pet_overlay_open`（页面 boot 时 `bridge.openOverlay`）也在同一条雷区上。表现：主窗口与覆盖层全部"未响应"，覆盖层页面心跳发不出去，15 秒后被看门狗隐藏（`overlay page silent` 日志）。

诊断方式：真机复现后用 `MiniDumpWriteDump` 抓全量 minidump，按模块解析线程栈——UI 线程卡在 `user32` 调用里（从 Sunday.exe 进入），多条 tokio 工作线程停在同一等待点；与上述代码路径完全吻合。

**修复**：所有会被页面 invoke 且要碰窗口 API 的命令改为 `async`（Tauri 把异步命令调度到异步运行时线程，窗口 API 等主线程事件循环是安全的）：`pet_capture_monitor_under_cursor`、`pet_capture_monitor`、`pet_autostart`、`pet_overlay_open`、`pet_overlay_ready`、`pet_overlay_close`、`pet_set_z_mode`。`pet_overlay_open` 拆出同步内部函数 `open_overlay_and_poll` 供托盘线程 / `--pet` 启动路径（不在 WebView2 回调里）继续使用。纯锁操作的 `pet_overlay_heartbeat`、`pet_set_interactive_rects`、`pet_set_input_mode` 保持同步。

**配套修复（同轮）**：

- `usePetRuntime` boot 里 `apiBase()` 改为 `waitForApiBase` 重试等待（60 秒）：pet-overlay 由 Rust 在启动恢复/托盘/CLI 触发时懒创建，页面 boot 仍可能早于后端冷启动，此前一次 `backend not yet started` 失败就让页面永久卡死。
- `tauri.pet-dev.conf.json` 删除 `app.windows` 覆盖（故障 B 的结构性修复），窗口定义完全走基础配置；`tests/pet-dev-config.test.mjs` 验收。
- `--pet` 作为 `--open-pet` 的别名（`pet::open_requested_from`，含 Rust 单测），环境变量 `SUNDAY_PET_OPEN=1` 通道保留。

**验证记录（修复后）**：全新数据目录真机启动 50 秒以上 `IsHungAppWindow=False`，覆盖层可见（首启自动装预设并显示）；`npm run pet:e2e` 10 项全绿（FPS 40–53）；`pet:verify` 105 条、`cargo test --bin Sunday pet::` 6 条、`vue-tsc` 全部通过。拖动手感、托盘菜单点击的手工点验留给用户（自动化不抢用户正在使用的鼠标）。
