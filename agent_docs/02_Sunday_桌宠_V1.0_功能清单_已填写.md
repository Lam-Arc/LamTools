# Sunday 桌宠 V1.0｜功能清单（逐项填写）

> 对应 `02_Sunday_桌宠_V1.0_功能清单.md`。本文件只记录**真实状态**：能自动化验证的都写测试名，需要在真机点一遍的标为待验证，做不到的写清缺口。
>
> 状态图例：
> - `[x]` 已验证：有自动化测试或可在代码中直接核对的硬事实。
> - `[~]` 已实现、未真机验证：代码完成且通过类型检查/构建，但**没有**在运行中的桌面点过一遍。
> - `[-]` 部分实现：写清缺什么。
> - `[ ]` 未实现。
>
> **本轮结论：P0 未全部通过（不能声明 V1.0 P0 完成）。** 主要缺口：全部需要真实桌面的交互项尚未验收；GLB/骨骼格式、ZIP 导入闭环、逐像素遮挡、Hitbox 可视化编辑未完成；P2 全部延期。
> 本轮按用户要求**没有做重启后的真机测试**（`core/desktop` 的 dev 应用属于同一个 `Sunday.exe` 进程族，重启会打断会话）。

## 一、项目基础与产品边界（P0）

- `[~]` **BASE-01** 插件/模块接入现有工程，保留原功能：桌宠是独立文档 `pet.html` + 独立覆盖层窗口 + `core/ui/src/pet/**`，主界面组件零修改。未真机验证。
- `[x]` **BASE-02** 不调用新 LLM、脱离 Agent 可运行：引擎与行为在 `pet-engine.test.ts` 里完全脱离 Agent 跑通（25 条），`core/ui/src/pet/**` 中没有任何模型调用。
- `[x]` **BASE-03** 三模块边界：`engine/`（桌宠自身）、`agent/`（真实交互）、表演层未实现（`config.enabled`/界面不依赖任何表演接口）。
- `[-]` **BASE-04** 启动/退出/隐藏/恢复：`pet_autostart`、`pet_overlay_close`、`shutdown()`、托盘开关都已实现；异常重启后的完整路径未真机验证。
- `[x]` **BASE-05** 配置版本与迁移：`migrateConfig` / `parseConfigText`，`pet-config-import.test.ts` 覆盖空配置、v0 迁移、坏 JSON 回落、逐项自定义。
- `[x]` **BASE-06** 多只宠物独立活跃：`pet-engine.test.ts`「两只宠物独立活动，共享地形缓存」验证独立物理与共享地形。

## 二、角色资源、适配与动作注册（P0）

- `[x]` **ASSET-01** 单张 PNG 即可成角色：测试「只有一张 PNG 也能成为可用角色」+「只给一张静态图也能建立可运行实例」。
- `[x]` **ASSET-02** PNG 序列帧按 fps/循环播放：测试「序列帧按数字顺序归组」「序列帧按 fps 循环，非循环停在最后一帧」。
- `[x]` **ASSET-03** Spritesheet 切片：测试「图集切片按行列取帧，不出现帧错位」（含跨行列断言）。
- `[~]` **ASSET-04** GLB/glTF/VRM 加载播放：**已实现**。Three.js `GLTFLoader` 解析（VRM 挂 `@pixiv/three-vrm` 的 `VRMLoaderPlugin`，VRM 0.x 自动修正朝向），骨骼/蒙皮/动画片段可播，每宠物独立 mixer 与骨架克隆，动作名精确/别名/退第一段三档匹配并写诊断；`PetPreview` 里同一套渲染层可预览。测试：`pet-render.test.ts` 渲染选择/模型框/动画映射 15 条；`pet-config-import.test.ts` GLB 混合资源包。**真机加载未验证**（未运行覆盖层）。
- `[x]` **ASSET-05** 适配器独立于物理/Action/UI：`engine/sprite.ts` 只描述"怎么取一帧"，`physics/nav/actions` 不 import 渲染。
- `[x]` **ASSET-06** 同一角色不同 Action 引用不同来源/格式：测试「pet.json 描述的动作各自引用不同资源」。
- `[x]` **ASSET-07** 动作名自动建议 + 人工修正 + 持久化：`suggestActionId`（测试覆盖外部命名）；预览器展示映射；`config.pets[].actions` 落盘。
- `[x]` **ASSET-08** `jump` 与 `jump_happy` 是两套完整动作：测试「jump 与 jump_happy 是两套独立完整动作」。
- `[x]` **ASSET-09** 动画缺失仍保留物理：测试「缺动画时动作仍可执行，并且有回退说明」+「只给一张静态图…能移动」。
- `[x]` **ASSET-10** 缺失依赖/不支持格式有清晰信息、单资源失败不致命：测试「GLB/骨骼文件明确列为不支持，而不是假装兼容」「没有任何图片时报错，但不会抛异常」。
- `[-]` **ASSET-11** 文件夹导入 + 版本化 `pet.json`：Rust `pet_scan_import` + 导入器都实现并有测试；真机前的路径读取未验证。
- `[~]` **ASSET-12** `.sundaypet` ZIP：**已闭环**。`assets/zip.ts`（fflate 内存解包、剥公共顶层目录、过滤 `__MACOSX`、路径/类型/体积校验）+ Rust `pet_read_zip` / `pet_write_pack_bundle`（二进制整包写入，同一套白名单与上限）；导入后直接进预览器。测试：`pet-zip.test.ts` 9 条（穿越拦截、脚本拦截、体积上限、文件数上限、坏容器）。**真机安装未验证**。
- `[x]` **ASSET-13** 路径安全/类型/数量/体积校验、不执行脚本：Rust 单测「rejects_path_traversal」「asset_whitelist_blocks_scripts」「pack_id_sanitizes_dangerous_names」。
- `[~]` **ASSET-14** 基础配置（名字/预览/缩放/朝向/资源/映射/物理）：`PetRecordConfig` 全字段 + 预览器可改缩放与尺寸；朝向与预览图未在界面暴露。
- `[x]` **ASSET-15** 动画与物理阶段联动：`BodyState.phase`（rising/apex/falling/landed）由物理给出，取帧按 phase 与动作开始时间；跳跃落地由物理判定（测试「跳跃在既有速度上叠加冲量」）。

## 三、导入预览器与默认测试场景（P0）

- `[~]` **PREV-01** 先预览再部署：`PetPreview.vue` 是唯一创建实例的入口，`confirmImport()` 才落盘。未真机验证。
- `[~]` **PREV-02** 自动推断尺寸/映射/碰撞体：导入时读图片实际尺寸并估算半径，动作名建议自动填入。未真机验证。
- `[~]` **PREV-03** 缩放/旋转/Action 切换即时生效：预览器有尺寸、缩放、Action 下拉与执行；旋转未做（2D 角色无此概念）。
- `[x]` **PREV-04** 预览复用正式运行时：`PetPreview.vue` 直接 `new PetWorld` + `buildTestArena` + `PetInstance`，与桌面同一套类。
- `[x]` **PREV-05** 自由运行测试：单测「只给一张静态图也能建立可运行实例」即自由运行 + 落地。
- `[~]` **PREV-06** 指定 Action 测试：`playAction()` 返回失败/回退原因，预览器显示；未真机点过。
- `[x]` **PREV-07** 点击设目标并显示路径：单测「生成有界离散图并给可达目标规划出路径」；预览器调用同一 `setDestination`。
- `[x]` **PREV-08** 回形/内左竖边接地/内右半圆/外上缘断口：单测「回形半圆测试图：外框、内左竖边接地、内右半圆、外框顶部断口」。
- `[-]` **PREV-09** 测试图随碰撞尺寸自适应：`buildTestArena(width,height,petSize)` 的边距/内框随尺寸缩放；半径变化后的可达性未逐尺寸回归。
- `[~]` **PREV-10** 调试叠层独立开关：地形线/碰撞体/路径/速度四开关都在预览器与运行时菜单里。
- `[~]` **PREV-11** 暂停/单帧/重置：预览器有三个按钮，重置重建世界但不动配置。
- `[x]` **PREV-12** 默认预览不调用 Agent：预览器只与 `PetWorld` 交互，没有任何 `agents` 调用。
- `[~]` **PREV-13** 确认才创建、取消无残留：`cancelImport()` 只清临时状态；未真机验证桌面无实例残留。

## 四、状态、Action 与自主行为（P0）

- `[x]` **ACT-01** 基础状态与情绪标签共存、接触状态来自物理：`BodyState` 的 grounded/hung/climbing 由物理写，Action 只读。
- `[x]` **ACT-02** Action 具备 ID/许可/优先级/动画/物理意图/结束与回退：`ActionDefinition` + `buildDefaultActions()`。
- `[x]` **ACT-03** 同一时刻只跑一个完整 Action：`ActionExecutor.update` 单指针；测试隐含验证。
- `[x]` **ACT-04** 基础 Action 兜底齐备：idle/walk/jump/jump_happy/climb/hang/fall/land/dance/interact/rest 全部注册，均可在无动画时运行。
- `[x]` **ACT-05** 优先级处理冲突、同优先级不抖动：测试「同优先级不抖动」「高优先级可以抢占，低优先级不能」。
- `[x]` **ACT-06** 新增 Action 不改物理/寻路：`registry.register` + `PetInstance.registerAction`，引擎模块无反向依赖。
- `[x]` **ACT-07** 用户抓取优先：测试「用户抓取可以打断自主行为」；`startDrag` 清空目标与路径。
- `[x]` **ACT-08** 自主选目标/探索/休息、无模型调用：`BehaviorController` + 测试「目标一旦选中会保持」。
- `[x]` **ACT-09** 鼠标附近只是软偏好：目标打分里用 `mouseBias`，寻路成本不含鼠标（见 NAV-05 测试）。
- `[x]` **ACT-10** 已选目标保持：测试「目标一旦选中会保持，不会每帧改选」。
- `[~]` **ACT-11** 活跃度/范围/休息倾向可调并保存：`BehaviorConfig` 全字段 + 落盘；设置面板暂未暴露这三个滑杆。

## 五、三级地图与地形拟合（P0）

- `[~]` **MAP-01** L1 屏幕边界 + 跨屏坐标：`TerrainField.setScreenBounds` 用虚拟桌面矩形；跨屏转换未真机验证。
- `[~]` **MAP-02** L2 窗口边框/手绘并随移动更新：`pet_desktop_windows`（EnumWindows）+ `applyWindows` + `moveWindowSource`；单测覆盖跟随与大幅错位，真机未验证。
- `[x]` **MAP-03** L3 视觉边缘可关闭/降精度：**已扩到多方向**。`fitEdges` 按精度档扫描 0°/90°（低）、加 ±45°（均衡）、再加 ±27°（高），再做位置+角度+长度去重；开关与档位在设置里。测试：「多方向识别：水平、垂直、斜边都能被找出来并归成三类几何」「去重：同一位置的重复线段只留一条」。
- `[x]` **MAP-04** 几何只有平台/斜坡/垂直边：`classifySegment` 测试。
- `[x]` **MAP-05** 平台上可站、下方可挂：`resolvePlatform` 双向接触 + `findCeiling` + 悬挂单测（松手保留切向速度）。
- `[x]` **MAP-06** 文字密集区不产生海量几何：测试「线段拟合不会因为文字噪音爆炸」（<80 段）+ 共线合并测试。
- `[x]` **MAP-07** 精度档与自适应段数：`QUALITY_PRESETS` + 拟合按误差产出，不写死段数。
- `[~]` **MAP-08** 半圆拟合后可站/爬/转角：`fitPolyline` 折线拟合 + `fitEdges` 斜边识别都能产出斜坡段，测试断言三类几何齐全；真实站在弧段上的物理表现未逐段验证。
- `[~]` **MAP-09** 稳定附着 L2 时跟随窗口：单测「窗口小幅移动时站在上面的宠物跟着走」；L3 明确不跟随（代码中 L3 段无 `sourceId`）。
- `[x]` **MAP-10** 窗口消失/突变不瞬移：单测「大幅错位不瞬移」（位移>160px 不跟随，交给重力）。
- `[-]` **MAP-11** 抖动容差与短时宽限：有 `supportTolerance` 与跟随阈值；没有独立的"短时宽限计时"。
- `[~]` **MAP-12** 手绘/编辑/清除/保存 + 分层启停：`addUserSegments`/`clearUserSegments` + `config.useL3`；手绘交互界面未实现。
- `[x]` **MAP-13** 局部处理/缓存/可观测耗时：`stats()`（段数/节点/建图耗时）+ `l3Stats()`，诊断面板显示。

## 六、物理、运动和寻路（P0）

> 实现已按用户指令整体"泰拉瑞亚瓦片化"：地图 = 16px 瓦片网格（与泰拉瑞亚 16×16 像素瓦片同粒度；实心/单向板/绳梯），物理 = AABB 对瓦片的分轴扫掠，寻路 = 瓦片 A*。旧几何段寻路图（nav.ts、simulateTrajectory）已删除。**提示**：设计文档是唯一权威源；本清单里标注"实现自定"的细节不是设计文档内容。

- `[x]` **PHYS-01** 物理是位置/速度/碰撞的最终来源：`stepBody` 唯一写 `position/velocity`。
- `[x]` **PHYS-02** 行走输出目标速度，碰撞真实影响：AABB 对实心瓦列做边界阻挡并归零水平速度（`pet-physics` 直接断言）；单向板/绳梯不挡横移。
- `[x]` **PHYS-03** 跳跃叠加冲量、空中连续：起跳在既有速度上叠加冲量；空中保留水平速度并受弱操控（`airControl`）。
- `[x]` **PHYS-04** 悬挂松手不归零：`release` 保留水平速度自由落体；檐下可滑行。
- `[x]` **PHYS-05** 静止松手竖落、落地不弹射：落地 `vy=0`；单向板/实心顶面着陆。
- `[x]` **PHYS-06** 碰撞尺寸/能力影响可达：判定框 60×120px（**实现自定**，取自角色屏幕尺寸）；跳跃高度由 `jumpImpulse²/(2g)` 换算成瓦片跳格数（16px 瓦片下约 16 格），A* 用同一高度校验跳跃边。
- `[x]` **PHYS-07** 固定步长跨帧率一致：1/120 固定步长 + 累加器子步，测试钉住不同帧时长结果一致。
- `[x]` **NAV-01** 有界离散空间 + A*：瓦片网格有界；A* 扩展上限 8000，超限返回不可达。
- `[x]` **NAV-02** 可达性由同一套物理语义决定：跳跃边用真实脚底高差 + 起跳/落点走廊检查；执行与判定共用同一瓦片网格，不存在"验证能过、实机不同"的两套物理。
- `[x]` **NAV-03** 不可达动作不规划、能力越适合代价越低：瓦片邻居按动作给代价（用户设计表：一瓦片=1，走=1、跳=x+y、爬=2、挂=3、落=(x+y)/2），不可走的邻居不生成；启发式取 0.5×曼哈顿距离保证不高估。
- `[~]` **NAV-04** 小幅随机补偿稳定且为正：瓦片 A* 当前无随机补偿（成本恒正）；选靶噪声在行为层 `behavior.ts`（不等于寻路成本抖动）。
- `[x]` **NAV-05** 鼠标偏好不进成本：瓦片 A* 成本只含地形动作代价；`mouseBias` 只在行为选靶打分里（`pet-behavior` 用例）。
- `[x]` **NAV-06** 目标可以是平台上任意安全位置：`goalCell` 归一化到站立瓦/板瓦，最后一段用瓦片路标精确接近。
- `[x]` **NAV-07** 转移考虑速度/附着，不折线瞬移：跳跃带水平速度离地、空中弱操控；攀爬沿绳梯连续位移；落地后重规划。
- `[x]` **NAV-08** 不可达/阻挡/地形消失能失败并恢复：寻路失败返回 `unreachable` 并清目标；卡住看门狗 >700ms 重规划（≥1s 防抖）。
- `[x]` **NAV-09** 局部重规划/缓存/上限可观测：`world.stats()`（瓦片数量/建图耗时/几何版本）、地形变化延迟重建、看门狗重规划在诊断里可查。

## 七、桌面输入、角色 Hitbox 与渲染（P0）

- `[~]` **INPUT-01** 左键单击直接执行 Action、不弹菜单：`clickAt` → `executor.force(hitbox.action)`，菜单只由右键打开。未真机验证。
- `[~]` **INPUT-02** 双击独立 Action、右键菜单：`doubleClickAt` + `PetContextMenu`（设置/绑定/临时会话/动作/显隐/移除/调试）。
- `[~]` **INPUT-03** 任意有效区域可抓：命中测试按精灵框 + Hitbox，`startDrag` 与位置无关。
- `[x]` **INPUT-04** 弹性牵引（滞后/摆动/阻尼）：测试「抓取是弹性牵引：位置滞后于鼠标，不是硬绑定」。
- `[~]` **INPUT-05** 释放保留速度、不失控：`drag.maxSpeed/maxAccel` 限制；真机手感未验证。
- `[x]` **INPUT-06** 点击/拖拽阈值：`moved > 6px` 才进入拖拽（`PetSurface.onPointerMove`）。
- `[x]` **HIT-01** Hitbox 与物理碰撞体分离：`collider`=物理圆 `physics.radius`，`hitboxes` 只参与点击；测试「Hitbox 按朝向镜像，物理碰撞不受影响」。
- `[~]` **HIT-02** 多 Hitbox 与区域绑定动作：**已完成**。预览器新增 Hitbox 编辑模式（拖动、右下角缩放、增删区域、按区域绑定单击/双击动作、启用开关），编辑结果随确认写进角色记录；命中优先级改为"后声明的区域优先"（头部压过身体）。测试：「多个 Hitbox 各自绑定动作，区域顺序决定优先级」「改 Hitbox 不影响物理碰撞半径」。**编辑器手感未真机验证**。
- `[x]` **HIT-03** 静态 Hitbox 随变换：`hitTest` 以精灵框归一化坐标计算，缩放/朝向自动生效；骨骼/逐帧绑定未做（高级模式）。
- `[~]` **HIT-04** Hitbox 外穿透：Rust 命中矩形只覆盖精灵框，逐 Hitbox 精细遮挡未做（整框接收点击）。偏好项，不影响底层操作。
- `[~]` **WIN-01** 透明层渲染 PNG 与动画角色、无粗边框：窗口 `transparent(true).decorations(false)`，`pet.html` 全透明。未真机验证。
- `[~]` **WIN-02** 真实窗口遮挡 + 可切换降级：实现三档 `top`（置顶）/ `clip`（置顶 + 按真实窗口矩形裁剪宠物画布，卡片气泡不受影响）/ `behind`（整层压到窗口之下）。`clip` 每 1.2 秒刷新窗口几何，遮罩用 SVG evenodd 挖洞。测试：`pet-render.test.ts` 遮挡遮罩 5 条（局部挖洞、越界裁剪、整层覆盖、非 clip 模式不裁剪）。**逐像素混合仍做不到**，窗口互相重叠处会恢复可见，已如实记录。真机遮挡效果未验证。
- `[~]` **WIN-03** 窗口移动/关闭/最大化最小化时更新：定期 `pet_desktop_windows` 刷新 + `applyWindows`；未真机验证。
- `[-]` **WIN-04** 多屏/DPI/屏幕边缘：虚拟桌面矩形 + `GetDpiForMonitor` 上报；引擎用物理像素。混合 DPI 下 CSS 文本缩放未验证，角色不会离开可视区（`clampToScreen`）。
- `[~]` **WIN-05** 全屏/游戏可隐藏暂停：`pet_overlay_close` + `shutdown`；没有"检测到全屏自动暂停"。

## 八、Ping 轮盘与屏幕上下文（P0）

- `[~]` **PING-01** 按下显示、移动选择、松开执行、中心/Esc 取消：`pet://ping/hotkey` down/up + `sectorAt` 中心死区 + Esc。未真机验证。
- `[~]` **PING-02** 大直径细环、中心透明：SVG 只画 stroke，无填充；半径/环宽可配。未真机验证。
- `[x]` **PING-03** 扇区数量不硬编码：`config.ping.sectors` 任意长度，等分排布；半径/环宽/图标/颜色/快捷键可配。
- `[x]` **PING-04** 增删项/动作绑定/预设/子轮盘：增删项、颜色/图标/标签、子轮盘（`group` 归组、选父项展开下一层）与自定义项动作（设置/导入/显隐宠物/刷新 L3/地形线/关闭覆盖层）都已接通；密集扇区给出提示而不截断。测试：`pet-render.test.ts` 轮盘分层与扇区命中 4 条。
- `[x]` **PING-05** 桌宠隐藏也能 Ping：Ping 入口是全局快捷键 + 独立窗口，不依赖角色可见；`ring` 只看 `config.enabled`。
- `[x]` **PING-06** `?`/`!`/`记录` 独立可编辑模板并持久化：`DEFAULT_PING_PROMPTS` 三条独立 + 设置面板逐条编辑 + 测试「桌宠的名字与提示词模板可以逐项自定义」。
- `[~]` **PING-07** 标记动画 2–3 秒 + 带标记上下文提问：`PingMarkerFx` 在指向处播放脉冲+图标+标签，时长取 `config.ping.markerMs`（默认 2400ms）；标记同时合成进截图像素（圈+符号+坐标），动画不参与请求时序（先提交再动）。指向处截图与提问已接。**真机截图未验证**。
- `[~]` **PING-08** `!` 用独立模板：`executeSector` 按 `sector.prompt` 分派，互不串用。
- `[x]` **PING-09** `记录` 只整理、不偷偷写本地文件：发送提示词模板，未调用任何写文件命令。
- `[~]` **PING-10** 默认截鼠标所在整屏：`pet_capture_monitor_under_cursor`（`MonitorFromPoint` + 该显示器矩形）。未真机验证。
- `[~]` **PING-11** 标记坐标准确传回：坐标同时写入图像与文本（屏幕坐标 + 显示器矩形 + 缩放）。跨 DPI 精度未验证。
- `[x]` **PING-12** 不把轮盘/卡片拍进原图：截图瞬间隐藏覆盖层再恢复（`capture_with_overlay_hidden`），Ping 真机项同批核验；早期记录的 `WDA_EXCLUDEFROMCAPTURE` 方案已弃用（它会把远程桌面/录屏整屏变黑，见 platform.rs 注释）。
- `[~]` **PING-13** 框选任意区域并保留坐标：`PingAnnotator` 拖选区域 → 裁剪 → 记录选区坐标。
- `[~]` **PING-14** 胶囊输入 + `?`/`!`/箭头/文字/画笔：六件套齐备（文字用 `prompt()` 输入）。
- `[~]` **PING-15** 撤销/重做/清除/取消、标注进图：`undo/redo/clearAll/cancel` 与合成导出。
- `[~]` **PING-16** 「对话」打开卡片并按配置附截图且不自动发送：`openPingConversation` 上传后放入 `pending.attach`，卡片可删除附件、需手动点发送。
- `[~]` **PING-17** 轮盘内「切换会话」立即影响后续 Ping：`SessionPicker` → `host.setPingTarget` → 写回 `config.ping.target`。
- `[x]` **PING-18** 截图失败不伪造：`decodeCapturedFrame` 对 magic/长度/像素数校验，失败抛错并显示 `capture.lastError`。

## 九、会话绑定、Agent 双向消息（P0）

- `[x]` **SESS-01** 每只桌宠可配默认项目+会话并跨启动有效：`PetBindingsState.pets` 落到 `config.bindings`。
- `[x]` **SESS-02** 右键临时切换立即生效、重启恢复默认：`temporarySessionId` 只在内存，`save()` 只写 `projectId/sessionId`。
- `[x]` **SESS-03** 首次在 My Project 只建一个会话：**已在真实后端验证**。`pet-isolated-e2e.test.ts`「首次未绑定 → 在 My Project 建且只建一个会话」：第二次路由拿到同一 sessionId，项目数不膨胀。
- `[x]` **SESS-04** Ping 与桌宠绑定完全独立：`bindings.pets[petId]` 与 `bindings.ping` 两处存储。隔离 E2E「Ping 绑定与桌宠绑定互不改写」双向验证（改 Ping 不动桌宠，改桌宠不动 Ping）。
- `[x]` **SESS-05** Ping 首次借用桌宠默认会话、之后独立：`pingTarget(borrowFromPetId)` 分支 + `pingBorrowedFrom`；隔离 E2E 验证借用后仍可被独立改写。
- `[x]` **SESS-06** 消息带 project_id/session_id/request_id、错误路由防护：`SessionChannel` 绑定单会话；审批带显式 `thread_id`；卡片按 `sessionId` 键。
- `[x]` **SESS-07** 同会话多条 Ping 只追加：`ensureCard` 按 `sessionId` 去重；隔离 E2E「同一会话永远拿到同一个通道」用真实 host 断言对象同一性。
- `[~]` **SESS-08** 流式中再次 Ping 不中断：`submitCoreComposerTask` + `turnStatus==running` → `queueInput`/`steer`。未真机验证。
- `[x]` **AGINT-01** 提问送达气泡并可直接回答：`pollAgentEvents` 从决策池取 `isQuestion` → 气泡输入框 → `respondApproval(..., 'other_guidance', text)`。**2026-11-01 上游 mock 验证**：往真实会话的事件流注入 `approval_request` + 决策池记录，桌宠（主 Agent 与子代理 Researcher）都弹出带选项/输入框的气泡；修掉了"绑定了会话却从不打开通道"的断点。
- `[x]` **AGINT-02** 真实审批到气泡、回原请求：气泡「允许/拒绝」→ `channel.respondApproval(requestId, ...)`。隔离 E2E「审批只能回到真实存在的请求」用真实后端断言：伪造 `request_id` 被拒绝，不存在本地伪造成功的路径。**2026-11-01 上游 mock 验证**：主 Agent 与子代理 Reviewer 的审批都转发成气泡并带来源标签；点击回答仍需真实运行时挂起的请求，mock 记录会被后端拒绝（符合"只回真实请求"）。
- `[~]` **AGINT-03** 完成通知轻量提示 + 可查看结果：气泡 `notification` 级别 + 卡片查看会话；完成事件目前靠决策池/回复触发，没有专听 `turn/completed`。**本轮 mock 结论：没有 producer，回复/完成类通知气泡无法从上游造出来；这是未实现项，不用显示接口伪造。**
- `[~]` **AGINT-04** 气泡直接对话可继续：无 `requestId` 时走 `channel.send`。
- `[x]` **AGINT-05** 关闭/折叠不拒绝不取消、待处理数准确：`dismissBubble` 只改 UI；`pendingBubbleCount` 只统计未关闭的 actionable。
- `[x]` **AGINT-06** 过期/重复/中断有可解释状态：重复提交由 `approval.respond` 的 `duplicate` 语义与本地 `handling` 拦；错误写进 `bubble.error`；隔离 E2E 确认后端拒绝语义真实生效。

## 十、桌宠气泡与 Ping 会话卡片（P0）

- `[~]` **BUB-01** 三级气泡复用消息/审批渲染：轻量通知/可操作/展开；审批按钮来自决策池，`SessionCard` 内是真实 `MessageView`。
- `[~]` **BUB-02** 提问审批默认弹出，其余轻量：`config.bubbles` 策略位已接（popup/badge/silent）。
- `[x]` **BUB-03** 默认只展开一个、可多开并避让：`maxExpanded` 在 push 时也生效（新审批到达收起旧的展开气泡）+ 同一宠物气泡按真实高度整栈排布。
- `[x]` **BUB-04** 跟随宠物、边界反向布局：`layout` 每次按宠物当前位置重算；先算整栈总高再决定头顶/脚下，翻到下方时不再互相压住。
- `[x]` **BUB-05** 内部滚动、可折叠、不可拖动：展开 230px / 折叠 40px 固定高度（与堆叠计算一致），内容超出在 body 内滚动；气泡没有拖动实现。
- `[~]` **CARD-01** 真实流式卡片：`SessionCard` 用 `MessageView` + `SessionChannel` 的实时快照。
- `[~]` **CARD-02** 出现在鼠标所在显示器、右侧优先、不出屏：`ensureCard` 按光标所在 monitor 计算并把位置夹回可视区。
- `[x]` **CARD-03** 一会话一视图：卡片 `Map<sessionId, CardState>`，`ensureCard` 幂等；隔离 E2E 断言同会话两次取通道是同一对象。
- `[~]` **CARD-04** 未钉住共享一个容器、每会话一个标签：`PetCards.vue` 的标签栏 + `activeCardSession`。
- `[~]` **CARD-05** 钉住独立、后续 Ping 不替换、取消回归：`pinCard/unpinCard`，`pinned` 与 `unpinned` 两组渲染。
- `[~]` **CARD-06** 已钉卡片允许重叠、可拖动整理：绝对定位，不做自动排列。
- `[~]` **CARD-07** 低透玻璃样式：`--pet-glass` + `backdrop-filter: blur(18px)`。
- `[~]` **CARD-08** 只标题栏拖动：`startDrag` 绑在 header，消息区/输入框/标签不触发。
- `[~]` **CARD-09** 保留用户拖动位置并夹回可视区：`moveCard` 只做边界夹取，无自动归位。
- `[~]` **CARD-10** `X` 只关视图不取消任务：`closeCard` 只删本地卡片，不断开会话。
- `[~]` **CARD-11** 每标签独立消息/草稿/流式：每个 `sessionId` 一个 `SessionChannel` + `card.draft`。
- `[x]` **CARD-12** 同一会话不会同时出现钉住卡片与重复标签：同一 `CardState.pinned` 决定归组。

## 十一、多桌宠、性能、稳定性与安全（P0）

- `[x]` **MULTI-01** 两只以上独立活动：测试「两只宠物独立活动，共享地形缓存」（独立 body、独立目标）。
- `[x]` **MULTI-02** 各自独立绑定、Ping 全局不被覆盖：`bindings.pets` 按 petId 存，Ping 单独。
- `[x]` **MULTI-03** 共享地形/可达图缓存：地形与 `NavGraph` 在 `PetWorld` 唯一实例。
- `[x]` **MULTI-04** 隐藏/移除一只不影响其他：`removePet`/`togglePetVisible` 只动目标实例。
- `[x]` **PERF-01** 各环节非阻塞：物理/寻路同步但受预算约束；L3 识别异步（`refreshL3`）；消息走已有运行时。
- `[-]` **PERF-02** 性能/质量档位：`quality`、`maxFps`、`l3RefreshMs` 可调；空闲降频只体现在 L3 周期，动画不断流。
- `[x]` **PERF-03** 可测诊断：`PetStage` HUD（FPS/tick/draw/地形数/节点/路径/动作/路由）+ `WorldStats`。
- `[-]` **PERF-04** 真实多屏/频繁拖窗/多卡片回归：只做了单测级（窗口跟随）；真机回归未做。
- `[~]` **SAFE-01** 截屏只由用户 Ping/对话触发、可关：只有 `submitPing*`/`openPingConversation` 调截图；`config.useL3` 是唯一的周期性截图（L3），默认 30s 可关。
- `[~]` **SAFE-02** 发送前识别目标显示器与失败原因：`pet_capture_monitor_under_cursor` + 失败信息；受保护窗口黑屏检测靠像素长度校验，未做全黑判定。
- `[x]` **SAFE-03** 审批用原权限与请求令牌：`approval.respond` 只带 `request_id + thread_id + decision`，不在本地伪造状态。
- `[x]` **SAFE-04** 模型/ZIP 输入有路径与资源限制：Rust 三重校验 + 单测。
- `[~]` **SAFE-05** 不跨项目串流、重启后一致：路由按绑定+会话隔离；重启后的恢复路径未真机验证。
- `[~]` **SAFE-06** 关闭后不留快捷键/遮挡/后台任务：`shutdown` 关窗口、清轮询、注销快捷键；未真机核对。

## 十二、Agent 表演能力（P2：保留设计，允许延期）

- `[ ]` **P2-01** 结构化 `pet` 工具：未实现。
- `[ ]` **P2-02** 本地执行器执行高层动作步骤：未实现。
- `[ ]` **P2-03** 生命周期事件映射为表现动作：未实现。
- `[x]` **P2-04** 关闭全部表演仍不影响 P0：P0 代码路径没有任何对表演层的依赖（`grep` 可核）。

## 十三、整链路回归脚本

| 编号 | 状态 | 说明 |
|---|---|---|
| E2E-01 纯 PNG → 预览 → 加桌面 | 未验证 | 逻辑与单测覆盖前置，桌面落地未点 |
| E2E-02 拖动甩出 | 未验证 | 物理单测覆盖，手感未验 |
| E2E-03 圆形/文字 PDF + 移动窗口 | 未验证 | L2 跟随单测通过，L3 只识别水平边 |
| E2E-04 第二屏 Ping | 未验证 | 代码按光标所在显示器截图 |
| E2E-05 同会话两次 Ping（第一次流式中） | 未验证 | 去重与排队逻辑已实现 |
| E2E-06 切会话再 Ping、钉旧卡片 | 未验证 | 分流/钉住实现，未点 |
| E2E-07 框选 PDF 公式并标注 | 未验证 | 标注器与合成路径已实现 |
| E2E-08 对话→附截图→删附件→发送 | 未验证 | 附件待发与删除已实现 |
| E2E-09 双绑定下审批进 A | 未验证 | 路由独立，未连真会话 |
| E2E-10 折叠未处理审批再恢复 | 未验证 | 只改 UI，不拒绝 |
| E2E-11 临时切 C 后重启回 A | 未验证 | 临时绑定不落盘 |
| E2E-12 未配置绑定首用建一次会话 | 未验证 | `ensureFallbackSession` 逻辑成立 |
| E2E-13 两只宠物 + 抓一只 + 隐藏另一只 | 部分 | 多实例单测通过，Ping 并发未验 |
| E2E-14 关卡片后重开看到结果 | 未验证 | 关视图不断会话 |
| E2E-15 禁用表演后 P0 仍可用 | 已满足 | 无表演依赖 |

## 十四、最终开发交付门槛

- `[ ]` **GATE-01** 所有 P0 通过：**未通过**，见上文 `[~]`/`[-]`/`[ ]`。**V1.0 P0 未完成。**
- `[x]` **GATE-02** 构建/启动/模块边界/依赖说明：`agent_docs/sunday_pet_v1.md`。
- `[ ]` **GATE-03** E2E-01～15 全部验证：未做（无真机测试）。
- `[x]` **GATE-04** 实际支持格式/版本/许可/不兼容项：`sunday_pet_v1.md` §5.3。
- `[-]` **GATE-05** Windows 遮挡/穿透原型结果与降级：两档 Z 序与命中穿透已实现并写明上限，缺真机证据与复现录像。
- `[x]` **GATE-06** 自动化可重复：`pet-engine.test.ts`（25）+ `pet-config-import.test.ts`（11）+ `cargo test pet::`（4）。
- `[x]` **GATE-07** P2 标注未实现（延期），不计入 P0 缺陷。
- `[-]` **GATE-08** 最终验收报告：本文件即报告，已完成/未完成/部分/受阻逐条列出。

## 十四点四、第三轮新增/修改（2026-10-30 续二）

新增：
- `core/ui/src/pet/render/blocky.ts`（Minecraft 皮肤网格、盒面 UV、动作姿态）
- `core/ui/src/pet/render/blockyRig.ts`（盒式骨架构建，肩/髋为旋转轴）
- `core/ui/src/pet/render/blockySkin.ts`（内置皮肤生成 + 外部 PNG 解码）
- `core/ui/src/pet/render/occlusion.ts`（按真实窗口矩形生成 SVG 裁剪切图）
- `core/ui/scripts/make-stickman.mjs`（生成带骨架与四段动画的 GLB）
- `core/examples/sunday-pet/stickman/{stickman.glb,pet.json}`
- `core/desktop/tauri.pet-dev.conf.json`（独立标识的体验实例）
- `core/ui/tests/pet-blocky.test.ts`（16）、`core/ui/tests/pet-glb.test.ts`（8）

修改：
- `engine/sprite.ts`（`BlockyClip`、`clipPrimarySource`）
- `engine/pet.ts`（renderState）
- `render/types.ts`（方块人走 Three 层）
- `render/threeLayer.ts`（方块人骨架槽位、皮肤缓存、换肤重建、blocky 诊断）
- `ui/usePetRuntime.ts`（方块人预设自动安装、换肤、遮挡模式窗口刷新）
- `ui/PetStage.vue`（宠物画布遮罩层）、`ui/PetSettingsPanel.vue`（遮挡档位、换肤入口、重建预设）
- `bridge.ts` / Rust（`pet_read_image`、zMode 支持 clip）
- `core/desktop/package.json`（`pet:dev`、`pet:verify`）

对应清单条目的变化：
- **ASSET-01**：内置方块人让"零素材也能用"从单图提升到带动画的预设角色，皮肤可换。
- **ASSET-14**：方块人预设保留名字、皮肤、缩放、物理参数，换肤不动其他配置。
- **WIN-02**：从两档变三档，新增可用的局部裁剪。
- **PERF-03**：3D 诊断增加 blocky 槽位与皮肤缓存计数。

## 十四点五、第二轮新增/修改（2026-10-30 续）

新增：
- `core/ui/src/pet/render/types.ts`（渲染契约、动画名映射、视口换算）
- `core/ui/src/pet/render/threeLayer.ts`（Three.js GLB/glTF 加载、mixer、逐视口绘制）
- `core/ui/src/pet/assets/zip.ts`（`.sundaypet` 解包与校验）
- `core/ui/src/pet/ui/pingModel.ts`（轮盘分层与扇区命中）
- `core/ui/src/pet/ui/PingMarkerFx.vue`（标记脉冲动画）
- `core/ui/tests/pet-render.test.ts`（15）、`core/ui/tests/pet-zip.test.ts`（9）、`core/ui/tests/pet-isolated-e2e.test.ts`（9）
- Rust：`pet_read_zip`、`pet_write_pack_bundle`（二进制整包写入）

修改：
- `engine/sprite.ts`（`ModelClip` + `FrameRef.type` + 命中改为后声明优先）
- `engine/terrain.ts`（`fitEdges` 多方向扫描、`dedupeSegments`、精度档带方向集）
- `engine/pet.ts`（`renderState` 带 `elapsedMs` 与 `clip`）
- `assets/importer.ts`（GLB 识别、混合资源、VRM/FBX 明确不支持）
- `ui/usePetRuntime.ts`（3D 层装配、ZIP 链路、标记动画、子轮盘、自定义动作、`ui` 面板状态）
- `ui/PetStage.vue`（WebGL 画布 + 3D 诊断）、`ui/PetPreview.vue`（3D 预览 + Hitbox 编辑器）
- `ui/PetSurface.vue` / `ui/PingRing.vue`（标记动画、子轮盘提示、面板状态统一）
- `core/ui/package.json`（新增 `three@0.180` 与 `@types/three`）
- `bridge.ts`（ZIP 内存源、整包写入、导入代次）

## 十四点六、2026-10-31 修复轮（用户反馈"一直未响应"）

**故障定位（真机复现 + minidump 证据）**：应用整体"未响应"的根因不是托盘菜单本身，而是**同步命令在 WebView2 IPC 回调线程（主线程）里调用窗口 API 的同线程重入死锁**。桌宠就绪后立即执行的 L3 抓屏（`useL3` 默认开）是每次启动必踩的触发点；`pet_autostart`、页面 boot 的 `openOverlay` 走同一条雷区。表现为主窗口与覆盖层全部无响应、页面心跳停发、15 秒后覆盖层被看门狗隐藏。

修复（架构级，非补丁）：
- 窗口类命令全部改 async（异步命令在异步运行时线程执行，窗口 API 等主线程是安全的）：`pet_capture_monitor_under_cursor`、`pet_capture_monitor`、`pet_autostart`、`pet_overlay_open`、`pet_overlay_ready`、`pet_overlay_close`、`pet_set_z_mode`；纯锁命令（heartbeat/interactive_rects/input_mode）保持同步。
- `usePetRuntime` boot 改为 `waitForApiBase`（最长等 60 秒）：配置窗口过早 boot 不再因一次 `backend not yet started` 永久卡死。
- `tauri.pet-dev.conf.json` 删除 `app.windows` 覆盖，窗口定义与正式版一致（**故障 B 结构性修复**），新增验收测试 `core/desktop/tests/pet-dev-config.test.mjs`。
- `--pet` 作为 `--open-pet` 别名（`pet::open_requested_from` + Rust 单测）；`SUNDAY_PET_OPEN=1` 环境变量通道保留。

自动化链路（`npm run pet:e2e`，此前从未跑绿，本轮跑通）：
- msedgedriver 拉起应用需正斜杠路径（反斜杠被吃掉）+ `webviewOptions.userDataFolder`；
- 应用检测到驱动注入的浏览器参数时自行合并 `--remote-debugging-port`（wry 固定参数会顶掉环境变量，`pet::webdriver_browser_args` + 单测）；
- e2e 断言修正：窗口标题按 `Sunday Pet` 前缀匹配（页面标题是阶段值）、pet 入口预热（vite 冷启动会撞 15 秒沉默看门狗）、新增 FPS>0 渲染断言、失败时转储应用日志。

对应清单条目的状态变化：
- **BASE-04**：启动/自动恢复路径已真机验证——全新数据目录启动后方块人自动出现、应用不挂（50 秒观察）；托盘点击后应用保持响应（点击已发生，菜单 UIA 抓取不稳）。
- **PREV-01 / ASSET-14**：首启"先装预设再显示"真机可见（e2e + 全新目录各验一次）。
- **E2E 整链路**：新增自动化 10 项全绿（主窗口加载、覆盖层出现、PetSurface 挂载、配置落盘、预设安装、非错误页、FPS>0、截图存档）；原 E2E-01～15 的人工点验项仍未做。
- **GATE-06**：测试计数更新——Rust 6 条 + TS 105 条 + pet-dev-config 2 条 + pet-e2e 10 项。

仍未验证（如实保留）：主窗口拖动手感（自动化不抢用户正在使用的鼠标，留待用户点验）、Ping 全链路真机、审批气泡真实闭环、多屏/混合 DPI。

### 十四点六·续（用户首日真机反馈的四个问题，2026-10-31）

1. **看不见方块人**（诊断按钮在、角色不在）：3D 画布的绘制缓冲从未被设置尺寸，`layer.resize` 把画布自身默认的 300×150 又传回去当目标尺寸（自指），角色按全屏物理坐标算出的视口全被裁掉。修复：`syncThreeCanvasSize()` 每帧按覆盖层物理像素同步缓冲；e2e 新增"3D 画布缓冲为全屏尺寸"回归断言。
4. **只出现上半身**（用户实见）：正交相机 `top=1/bottom=0` 是相对视线高度 0.55 的偏移，实际可见区间 [0.55,1.55]，一单位高的角色下半身全被裁掉。修复：中心对准 0.5、上下 ±0.55，可见区间 [-0.05,1.05] 全身入画。e2e 截图（CDP 合成器）实证全身。
2. **托盘「打开桌宠」点了没反应**：显隐/关闭后，复用路径既不 show 窗口也不恢复角色（旧的一次性 reload 标记启动时就用掉了）。修复：页面存活时打开= place_overlay + 按需 show + 广播 `pet://overlay/opened` 让页面恢复隐藏的角色；页面死超宽限期则整窗重建（旧的 reload_done 机制删除）。
3. **主界面"未响应"、Ping 卡片残缺**：后端的消息来源白名单只有 5172/5173/5180，pet-dev 前端在 5299，WebSocket/HTTP 全被当跨站 403 拒绝——开发实例的后端链路从未通过。修复：pet-dev 启动器设置 `LAMTOOLS_CORE_ALLOWED_ORIGINS=http://127.0.0.1:5299,http://localhost:5299`（后端预留的扩展口，仅作用于开发实例）。
4. **慢启动被看门狗误杀**：npm install 后 vite 全量重优化依赖，首次页面加载超过 15 秒被收走、且轮询线程不恢复。修复：页面从未报过心跳时宽限期放宽到 60 秒（`page_alive`），`pet_overlay_ready` 显示窗口时同步重启轮询。

配套：e2e 与 pet-dev 实例不能同时运行（应用标识构建期固化，同跑会秒退，已注明）；皮肤可直接放入 `packs/<id>/skins/` 并把 `actions[*].skin` 指过去（用户粉色皮肤已按此上到 petdev 实例）。

### 十四点六·续2（截图实证轮：方块人渲染三连修，2026-10-31 深夜）

用 `SUNDAY_PET_DIAG=1` 诊断模式（覆盖层变普通小窗口+HUD 自动展开）+ HUD 读数逐层定位，用户"看不见方块人"共有**三个叠加根因**，全部修复：

1. **方块人从未进入 3D 渲染列表**：`draw()` 收集 renderables 时只认 GLB 的 `type:'model'`，方块人的 `type:'blocky'` 被漏掉 → 3D 层永远不启动（HUD 实证：`3D: 未启用 · 模型 0 · 实例 0`，而物理/行为/寻路全在跑）。修复后 HUD 显示 `3D: 已启用 · 实例 1`。
2. **包内资源读取全部误判"越界"**：Windows `canonicalize()` 返回 `\?\E:\...` 长前缀，`canonical.starts_with(root)` 的 root 未做同样规范化，皮肤/贴图一个都读不出来。修复 `canonical_contains`（两边同形态再比），新增 Rust 测试 `bounded_asset_reads_inside_root_and_rejects_traversal`。
3. **3D 画布缓冲 300×150**：`layer.resize` 把画布自身旧尺寸传回去当目标尺寸（自指）。修复 `syncThreeCanvasSize()` 每帧按覆盖层物理像素同步。

**截图实证**：e2e（CDP 合成器截图）拍到方块人站在屏幕底部——`.lam/artifacts/pet-e2e/pet-overlay.png`；e2e 扩到 **12 项断言**（新增"3D 渲染层已启用""3D 画布缓冲为全屏尺寸"两条回归）全绿。注意：PrintWindow/桌面 BitBlt 抓不到 WebView2 的 WebGL 合成层，验证渲染必须走 CDP 截图或诊断 HUD。

**重要陷阱（记录）**：`tauri dev --config X` 会把 X 的配置**编译进** `target/debug/Sunday.exe`（devUrl、应用标识全部固化）。跑过 pet:dev 之后，直接运行该 exe 或 pet:e2e 都会带上 petdev 身份（连 5299、撞 petdev 单实例锁）——e2e 前必须先 `cargo build --bin Sunday` 恢复基础配置。这也解释了此前"第二实例秒退"的现象。

诊断模式保留：`SUNDAY_PET_DIAG=1 npm run pet:dev` → 覆盖层变为 960×640 普通窗口（不置顶/不穿透/HUD 展开），供截图定位。

## 十四点七、分块核验与跨块落实轮（2026-10-31 下午）

按用户"分块核验"方法论：块 B/C/D/E 由子代理按"设计 ↔ 代码对照阅读"逐项核验（不以测试通过为证明），跨块问题由主会话统一落实。逐项证据见 `agent_docs/桌宠_分块验收.md`。

对应清单条目状态变化：
- **NAV-02 / NAV-07**：从"名义符合"变为真实兑现——`simulateTrajectory` 改为复用 stepBody（同一套积分与碰撞，垂直墙/屏幕边界参与弹道验证）；跳跃起跳帧不再提交 vx，规划 launch 弹道真正生效。
- **NAV-08**：目标生命周期修复——规划失败清行为目标并通知行为层（原：goal 永久挂起、decide 永不再被调用、20s 超时死代码）；起点即终点按已到达收尾；路径最后一段瞄准真实终点（原被中间路标覆盖，多边路径永远差一跳）。
- **ACT-08/10/11**：决策层修复——候选只选可站立节点且排除脚下 24px、到点进随机停留窗、activity 语义落地（越高越走远）。ACT-11 仍缺设置面板滑杆（维持 `[~]`）。
- **PHYS-02**：补撞墙直接断言（原 `[~]` → 已有测试）。
- **MAP-02**：L2 枚举剔除系统壳窗（`Windows.UI.Core.CoreWindow` 类名）与 cloaked（DWM 披隐）窗口——用户屏幕中部"莫名黄线"根因。
- 新增回归：pet-physics 18 条、pet-behavior 31 条（含"多边路径到达真实终点""不可达失败后恢复"两条集成）、nav 平地 walk/桥 4 条（旧代码全红）、Rust block_b 7 条（含真机探针窗口）。
- 测试基线：TS 149 条 + Rust 14 条全绿；vue-tsc 无 pet 相关错误。真机目视项与设计含糊项见 `桌宠_分块验收.md` 阻塞清单。

## 十四点八、用户设计决定落实轮（2026-10-31 下午，第二辑）

用户三条设计决定 + 两个真机新反馈，全部落实（详见 `桌宠_分块验收.md`）：

- **L1 可以爬墙**：L1 左右屏边生成贴墙节点与 climb 边（节点在墙内侧）；物理修复攀爬接管链路——此前 `body.climbing` 没有任何置真路径、贴墙接触不标记，攀爬整条链路从未生效；攀爬动作贴墙起动。连带修正：屏幕顶边的"站立节点"在屏幕外（物理钳制永远站不上），不再生成——否则可爬墙后弹道模拟会从屏幕外节点产生退化跳跃边。
- **L2 = 泰拉瑞亚平台**：窗口的上边缘与下边缘都是单向板（`oneWay`：可站、从下往上跳可穿过、提交下落意图可穿下、檐下可挂）；竖边是绳梯（可穿透、可爬）。窗口下沿之前漏建，属于实现漏项，已按设计补齐。
- **L2 只建看得见的**：按 z 序对顶边做可见性裁剪，被上层窗口盖住的区间不建、完全被遮的窗口不建任何地形。
- **"走到角落显示目标不可达还一直往左走"**：行为选靶加 `reachableFrom` 有向可达过滤——不可达目标不再被选中（此前选中必然规划失败、原地反复"选靶→失败→重选"）；"脚下"判定按碰撞半径放宽——修掉贴墙时对着墙原地走的循环。
- **朝向规则**：行走/攀爬侧脸朝行进方向，站立/空闲/其他动作一律正脸朝观众（3D 层两处渲染分支）。
- 对应状态变化：MAP-02（可见性地形）、MAP-05（单向板）、NAV-08（可达性选靶）、PHYS-02（撞墙/爬墙直接断言）均有新增引擎/物理用例钉住；测试基线 TS 157 条 + Rust 14 条全绿、vue-tsc 零错误。

## 十四点九、分块调试解耦轮（2026-10-31 下午，第三辑）

用户指令：桌宠按块拆开、不要一起调试；**Ping 环与桌宠是两个独立功能**（本设计方案把它们写在一起只是历史安排）；其余块派子代理核验落实。

- **Ping 解耦（块H）**：Ping 装配从 usePetRuntime 抽出为独立模块 `core/ui/src/pet/ping/usePingRuntime.ts`（依赖显式注入：config/bridge/agent 会话/可选"最近宠物借用来源"/自定义动作/通知）；Ping 模块零 import 桌宠引擎（源码契约测试钉住）；零宠物时轮盘/提交/卡片/目标路由完整可用；PING-01..18 逐条对照核验（9 符合 / 7 已接通待真机 / 0 不符）；PING-12 状态修正为 `[x]`（"先隐藏再截"兜底早已在 Rust 侧实现）。
- **桌宠动画/表现块（块F）**：逐条核验渲染契约、方块人、相机、遮挡——发现并修复三处：①走路动作按固定节奏（不按移动速度倍速；此前按速度加频率是实现自定，已移除）；②纯 2D 宠物的画布尺寸不每帧同步（非默认分辨率被裁）；③"全身入画"修复引入的 ~10% 横向拉伸（相机水平半宽未随视野调整）。
- **地图与寻路实验台**（上一辑）：`http://127.0.0.1:5299/pet-navlab.html`，无样式独立页面。
- **方块人动画实验台**：`http://127.0.0.1:5299/pet-animlab.html`——底部按移动/表演/互动分组切换 12 个动作，支持播放控制、朝向、Steve/Alex、自定义 64×64 皮肤（文件选择或拖入）。Ping 实验台待建。
- 屏顶隐身根因与悬挂锚定修正见 `桌宠_分块验收.md`（本轮跨块落实清单 10-15）。
- 测试基线：TS 168 条 + Rust 14 条全绿；vue-tsc 零错误。

## 十四点十、泰拉瑞亚瓦片化重写轮

用户指令："在设计方案中我们也说过体素化……不就是瓦片网格吗？所有的行为完全按照《泰拉瑞亚》去对齐，不用考虑既有实现，因为你之前的实现不一定是对的，可能偏离了我的原意。我现在说了，我的原意就是要让它跟泰拉瑞亚一样"；"包括寻路，边，判定框全部都与泰拉瑞亚一致，先一致，再适配"。

用户追加："通常泰拉瑞亚的瓦片力度有多细，这个就调成多细。之前的那个体素化可能不够细，那你就当它是随便写的吧" → 瓦片格宽从实现自定的 48 收到 16px（泰拉瑞亚同粒度）。

用户权威源规则："凡是我的设计文档里头没有写的，那都是他自己实现的，设计文档是唯一的权威源"。本节中判定框 60×120px、行为选靶噪声、可达性预筛等均为实现细节，不是设计文档内容。

按"先一致、再适配"整体重写，旧几何段模型（`nav.ts`、`simulateTrajectory`、`blockedByWall`、节点/边图）全部删除，不再维护两套：

- **地图**：`core/ui/src/pet/engine/tiles.ts`（新）——16px 瓦片网格（泰拉瑞亚 16×16 像素瓦片同粒度；用户指令："通常泰拉瑞亚的瓦片力度有多细，这个就调成多细"），`TileType.Solid/Platform/Ladder`；几何段体素化：横边→实心/单向板、竖边→绳梯/实心、斜边→沿线平台（楼梯）；窗口顶边=单向板行、竖边=绳梯列；完全被遮的窗口仍整窗无瓦。
- **判定框**：AABB 60×120px（**实现自定**：角色屏幕尺寸；设计文档只给碰撞半径），脚底锚定；`renderRect`/`hitTest`/调试框/物理共用。16px 瓦片下角色约占 3.75×7.5 格。
- **物理**：分轴瓦片扫掠 `moveX/moveY`——实心四面挡、单向板只挡下落（可穿板、dropThrough 下落）、绳梯无碰撞；固定步长 1/120 子步；重力 2400 / 起跳 1120（≈261px≈5.4 格）/ 走速 260 / 空控 0.45。
- **寻路**：瓦片 A*（走/跳/落/爬/挂）；跳跃边用**真实脚底高差**校验（修复"行差 5 = 240px 跳得上"把 288px 高台误判为可达）；绳梯可爬上窗口顶；墙天然隔断；檐下可挂。
- **执行**：`pet.followTiles` 沿瓦片路标走/跳/落/爬；贴墙时带水平速度起跳翻越；站墙顶边缘与下一路标对齐时朝落差方向走落；绳梯顶端继续爬到板顶再横移；路标循环推进避免"无动作请求"空档导致半空脱手。
- **行为**：候选点/可达集全部来自瓦片网格，不可达目标不选。
- **实验台**：`pet-navlab.html` 重画为瓦片世界（实心灰块/单向板橙条/绳梯蓝线/路径绿格/判定框蓝框）。
- **测试**：`pet-physics` 13 条、`pet-engine` 17 条、`pet-behavior` 22 条重写为瓦片语义；桌宠相关 10 个测试文件 145 条全绿（含爬墙压力回归 `pet-climb`）；`vue-tsc` 零错误；`node --test tests/pet-navlab-config.test.mjs` 2 条全绿。
- 已知量化特性：平台表面取所在瓦行上沿（16px 瓦片；窗口 y=400 → 400，y=401 → 400），站立高度误差 0~15px。平台宽度量化同理（左右各差 ≤15px）。

## 十五、本轮产生/修改的文件

新增（前端）：`core/ui/src/pet/**`（bridge/config/engine×9/assets/agent×2/ui×10）、`core/ui/tests/pet-engine.test.ts`、`core/ui/tests/pet-config-import.test.ts`、`core/desktop/pet.html`、`core/desktop/src/pet.ts`。
修改：`core/desktop/vite.config.ts`（多入口）、`core/desktop/src/main.ts`（启动恢复）、`core/desktop/src-tauri/src/main.rs`（模块/命令/托盘）、`core/desktop/src-tauri/src/pet/{mod,platform}.rs`（新增）。
文档与样例：`agent_docs/sunday_pet_v1.md`、本文件、`core/examples/sunday-pet/arc-ball/`（`pet.json` + 两张图）。
运行数据（dev 模式，供手工验收）：`core/.lam/pet/config.json`、`core/.lam/pet/packs/arc-ball/`。
