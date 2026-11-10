---
状态: 完成
摘要: AI 与用户共用的屏幕标注层：箭头、框选、高亮、涂鸦、文字直接画在真实桌面上，标记跟着窗口走，用户能圈选批注并回传给 Agent。
---

# Desktop Overlay 屏幕标注层

## 需求与边界

用户原话：“AI 直接在屏幕上标记、绘制、互动、发弹幕：箭头、框选、高亮、涂鸦、文字、悬浮控件、动态提示。标记可跟随窗口和对象，用户能直接点击、圈选、批注，与 Agent 实时互动。视觉轻量自由，不干扰正常使用。”

换成能验收的话：Agent 说“看这里”的时候，屏幕上真的有一个箭头指到那个按钮上，而不是发一张截图让用户自己找。窗口挪了，箭头跟着挪。用户想反驳，可以直接在屏幕上圈一块、写一句话，这句话回到正在跟他说这个事的那个会话里，Agent 下一轮就能读到。

这次做：

1. 一个常驻的透明标注层，置顶但不挡鼠标，只有标注本身和工具栏吃点击。
2. 五种标记：箭头、矩形框、圆形/椭圆高亮、自由涂鸦、文字标签。
3. 标记可以绑到某个窗口，窗口移动、缩放、切换前后台时标记跟着走；也可以绑屏幕绝对坐标。
4. Agent 通过工具一次性画一组标记，能按 id 清掉，也能清空；标记可以设自动消失时间。
5. 用户能进入批注模式，圈一块区域、写一句话，提交后回到发起标记的那个会话。
6. 托盘有“打开标注层/关闭标注层”，和桌宠同样的开合方式。

这次不做：

1. 发弹幕（滚动字幕、连发、投票）不做，等标注层的坐标系和交互稳定后再说。
2. 悬浮控件（按钮、滑块、输入框这类长期挂在屏幕上的迷你 UI）不做，第一版只有“看”和“圈选批注”。
3. 不重做截图标注。Ping 的截图编辑器继续独立存在，它画在静态截图上，这里画在真实桌面上。
4. 不做多人协作、不做标注历史回放。
5. 不改 Computer Use 的提示边框和 Agent 光标，两者并存，标注层不接管它的窗口。

## 取舍

**独立窗口，不寄生在桌宠或 Ping 覆盖层里。** 桌宠覆盖层可以被用户关掉、禁用、崩溃重启，Ping 覆盖层只在按快捷键时活跃。标注层要能随时被 Agent 叫出来，生命周期必须独立。代价是多一个全屏 WebView2，已知可控，桌宠、Ping、Computer Use 已经是三个同构窗口。

**状态放 Core 进程内存，不做数据库。** 标注是屏幕上的临时表达，进程重启后留在屏幕上没有意义。工具调用写入、覆盖层轮询读取，单向数据流，不需要事件总线。

**覆盖层轮询而不是 WebSocket。** 标注不是高频数据，400ms 轮询足够跟手，和 Computer Use 覆盖层同一套路，少一套连接管理。

**窗口跟随在前端算，Rust 只报窗口矩形。** 已有 `pet_desktop_windows` 返回真实窗口的 id、标题、矩形和层级，复用即可。窗口几何每 500ms 刷一次，绑定标注按窗口矩形做相对定位；窗口消失时标注降级为屏幕坐标并标记为“目标已关闭”。

**用户批注交给 Ping。** 圈选只是入口，真正说话、标注、发送全部复用 Ping 已有的静态截图窗口和 `channel.send()` 引导链路。标注层不再自己造输入框、待读队列或 turn/start，避免第二套“把屏幕上的意见送进会话”的实现。

被否掉的方案：

- 画在截图上再当图片贴回屏幕：窗口一动就错位，且用户没法对真实桌面圈选。
- 直接改造 Ping 覆盖层加实时标注：Ping 的输入模式和环形菜单已经复杂，混进去会把两件事绑死。
- 用一张 PNG 覆盖层：动态提示、跟随、点击命中全都要重做，不如直接上 WebView。

## 步骤

1. **Core 标注状态与工具**
   - 新增 `core/src/lamtools_core/overlay/store.py`：标注模型、批量应用、按 id 清除、过期清理、批注队列。
   - 新增 `core/src/lamtools_core/overlay/tools.py`：`desktop_overlay` 工具，action 为 `show` / `clear` / `list` / `feedback`。
   - `GET /api/core/overlay/state` 给覆盖层读；`POST /api/core/overlay/control` 收清除与批注。
   - 验收：`core/tests/test_desktop_overlay.py` 覆盖坐标模型、过期、按 id 清除、工具参数校验、批注入队。

2. **工具注册与权限**
   - `default_toolbox.py` 增加 spec、handler、`AUTO_ALLOW`、顺序、分类、失败模式。
   - 验收：同一测试文件断言工具出现在默认工具箱且 handler 可调用。

3. **Rust 标注层窗口**
   - 新增 `core/desktop/src-tauri/src/desktop_overlay.rs`：`overlay_open` / `overlay_ready` / `overlay_close` / `overlay_set_rects` / `overlay_heartbeat`，页面 `overlay.html`，透明置顶、默认穿透、心跳看门狗、Esc 收起。
   - `main.rs` 注册命令与托盘入口。
   - 验收：`cargo check` 通过；`cargo test --bin Sunday desktop_overlay::` 覆盖命中判定纯函数。

4. **覆盖层页面**
   - `core/desktop/overlay.html`、`core/desktop/src/overlay.ts`、`core/ui/src/overlay/OverlaySurface.vue`。
   - `core/ui/src/overlay/model.ts`：箭头路径、窗口跟随换算、过期判断、命中测试，纯函数。
   - 渲染层用 SVG，箭头带流动虚线，框选带呼吸边，文字标签带淡入。
   - 验收：`core/ui/tests/desktop-overlay-model.test.ts` 覆盖跟随换算、过期、命中、路径生成。

5. **批注交互交给 Ping**
   - 覆盖层拖拽圈选结束后，直接调 `pet_ping_capture_open` 并把选区带过去，由 Ping 的截图编辑器预置框选。
   - 用户在熟悉的那套工具条里加箭头、文字、说明，发送走 `CaptureApp` 的 `channel.send()`，截图作为附件、消息走引导。
   - 标注层自己不再收键盘输入，也不再有待读批注队列。
   - 验收：`regionToFrame` 的坐标换算与截断有前端测试；dev 实例圈选后截图窗口弹出且选区已经框好。

6. **打包与联调**
   - `vite.config.ts` 增加 `overlay` 入口；`core/desktop` 构建通过。
   - 本机起 dev，托盘打开标注层，用 CLI/工具画箭头、挪窗口、圈选批注各验一遍。

## 目标与完成判据

目标：Agent 解释界面、指出问题时，用户不用在截图和真实窗口之间来回找。

完成判据：

1. 托盘能打开、关闭标注层，打开时不挡鼠标，桌面照常可点。
2. 工具调用一次画出箭头、框、高亮、涂鸦、文字，屏幕上位置与给定屏幕坐标一致。
3. 绑定窗口的标记在窗口移动后跟随，误差在两个刷新周期内收敛。
4. 用户圈选一块并提交一句话，会话里出现这条用户消息，Agent 下一轮能引用。
5. 清除单个和清空都即时生效，标注不残留。
6. 关闭应用或标注层退出后，屏幕上不留任何图形，鼠标不被捕获。

## 风险

- 全屏透明窗口在部分缩放组合下坐标偏移。缓解：沿用桌宠的物理像素约定，换算用覆盖层实际宽高比而不是页面自报 DPR。
- 两个全屏置顶窗口（Computer Use 和标注层）同时存在时可能互相压住。缓解：标注层只在有标注时保持可见，Computer Use 进行中不主动叠加。
- 窗口绑定在某些游戏全屏或 UWP 窗口上拿不到矩形。缓解：拿不到就降级为屏幕坐标，并在工具返回里说明。
- 用户批注触发 turn/start 时会话正忙。缓解：入队，工具 `list` 返回待读批注。
- 覆盖层页面崩溃会盖住桌面。缓解：心跳看门狗 + Esc + 托盘关闭，三路兜底。

## 未答问题

1. 批注如何进会话：已定，走 Ping 的截图编辑器与 `channel.send()`，活跃回合里是引导，不新起回合。
2. 标注默认保留多久：默认 30 秒，`ttl` 参数可覆盖，最长 24 小时。
3. 用户圈选批注带不带截图：带，Ping 发送时会附上圈选区域的截图。

## 实现结果（2026-11-08/09）

已完成并验收：

- Core：`core/src/lamtools_core/overlay/` 状态与工具，`GET /api/core/overlay/state`、`POST /api/core/overlay/control`，`desktop_overlay` 已注册进默认工具箱并按 `AUTO_ALLOW` 放行。
- 桌面：`core/desktop/src-tauri/src/desktop_overlay.rs` 独立覆盖层窗口，托盘新增「打开标注层/关闭标注层」，支持 `--open-overlay` / `SUNDAY_OVERLAY_OPEN=1` 直接拉起。
- 前端：`core/desktop/overlay.html`、`core/ui/src/overlay/`，五种标记、窗口跟随、工具条、圈选入口。
- 合并：圈选结束直接打开 Ping 的截图编辑器，`pet_ping_capture_open` 接收屏幕选区，`CaptureEditor` 挂载时预置框选；发送复用 Ping 的 `channel.send()`。
- 验收：Python 23 条、前端 49 条、Rust 1 条通过；dev 实例实测箭头/矩形/椭圆/涂鸦/文字位置正确，窗口移动 300×200 后标注跟随，圈选 479×279 后截图窗口弹出且选区已框好。

已知限制：

1. 标注层自己不再收文字输入，所有用户表达都在 Ping 的截图编辑器里完成；如果截图窗口打不开，圈选只提示错误，不回退到第二套输入。
2. 工具条放在屏幕顶部，避开桌宠默认站位；桌宠如果被拖到顶部仍可能挡住。
3. 标注状态下整屏吃鼠标，最长 30 秒自动退出；按 Esc 关闭整个标注层。

## 瞬时表演层（2026-11-09）

用户原话：“这个东西最主要的是交互体验……比如说弹幕从右飘到左啊，比如说表情包啊，还有一些瞬时的东西，它有受控时长。比如说这个表情包标记的是 3 秒，我传的参数就是 3 秒，那我这个东西发出去 3 秒钟之后，它就自动淡出消失了。”“SVG 如果能够的话，能让它像流式一样逐渐画出，而不是直接贴一个完整的。”“不用专门分段，而是做流式渲染。”

新增两类标记和一种续画：

1. `danmaku`：整屏飘过的弹幕，默认从右往左，`ttl` 默认 3 秒，位移与 `ttl` 同步，走到尽头正好淡出。
2. `sticker`：表情包，可以是图片（`image`）或 emoji/文字（`text`），默认回弹放大入场，`ttl` 默认 3 秒。
3. `desktop_overlay` 新增 `action=append`：给已有 svg 标记追加图形，新图形从到达那刻开始画，`expires_at` 顺延到 `now + ttl`。

动效与描边：

- `motion` 支持 `fade / pop / float / drift / danmaku`，含 `duration / fade / easing / from`。弹幕默认 `danmaku + right + linear`；表情包默认 `pop`；其它默认 `fade`。
- `draw` 支持 `stroke / reveal / none`，默认 `stroke`，`duration` 默认 `min(ttl*0.6, 0.8)`。没有 `stagger`，不做人为分段或整批延迟。
- 描边用 `pathLength=1` + `strokeDasharray=1` + `strokeDashoffset` 归一化，不依赖 `getTotalLength`，长路径也不会断。

图片表情包：

- 工具收工作区图片路径，`overlay/assets.py` 复制到系统临时目录 `sunday-overlay-assets/`，服务端生成随机名，路由只按名读取，拒绝路径片段；单张上限 3 MB，只收 png/jpg/webp/gif/bmp。
- 状态里只存 `{asset, width, height}`，不塞 base64。

## 这一轮踩到并修掉的坑

**表情包图片被浏览器按 CORP 拦掉。** Core 所有响应都带 `Cross-Origin-Resource-Policy: same-origin`，而标注层页面和 Core 永远不同源（dev 是 5299 对 5298，打包后是 WebView 自定义源对 127.0.0.1）。表现极具误导性：图片请求返回 200，`<img>` 也在 DOM 里，但 `naturalWidth = 0`、高度 0，屏幕上什么都没有。修法是把响应头决策抽成 `api_access.apply_response_security_headers(path, headers, runtime_path=...)`，仅对 `/api/core/overlay/assets/` 放开 `cross-origin`，其余接口继续同源保护；验收测试 `tests/test_core_api_access.py::test_overlay_assets_can_be_embedded_by_the_overlay_page` 钉住这个边界。

**emoji 不显示。** 透明覆盖层默认字体栈没有彩色 emoji 字体，补 `'Segoe UI Emoji'` 后正常。

**肉眼验收会骗人。** 覆盖层窗口被前台全屏程序遮住时，心跳和 rAF 会被节流，抓屏可能拍到一个已经关掉的窗口。改成开 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333`，用 CDP 直接读页面 DOM 和 `Page.captureScreenshot`，既能拿到 `naturalWidth`、`strokeDashoffset` 这种硬指标，也不打扰用户前台应用。

## 瞬时层验收结果（2026-11-09）

- 图片表情包：`naturalWidth 256`、渲染矩形 262×262，截图可见。
- emoji 表情包：`😀🎉` 彩色渲染，矩形 212×103。
- 弹幕方向：同一元素 x 坐标 1250 → 933 → 616，从右往左。
- 受控时长：`ttl=3` 的表情包 1 秒时存在、3.6 秒时已从 DOM 消失；淡出段透明度 1 → 0.84。
- SVG 流式：`strokeDashoffset` 0.914 → 0.577 → 0，截图从一小段弧画到整条曲线；`append` 后新图形 0.986 → 0，原图形保持完整。
- 窗口：覆盖虚拟桌面 2048×1152（物理 2560×1440，125% 缩放），`WS_EX_TRANSPARENT` 生效即默认穿透；点“收起”后窗口销毁、页面从 CDP 列表消失、后端继续运行。
- 定向测试：Core `tests/test_desktop_overlay.py` 43 条、`tests/test_core_api_access.py` 与 `tests/test_app_factory.py` 81 条、前端 `desktop-overlay-model` 23 条、`ping-capture` 33 条；`vue-tsc --noEmit` 无 overlay 报错，`vite build` 通过。

未覆盖：托盘“打开/关闭标注层”的鼠标路径本轮没点（打开路径由启动参数验证，关闭路径由工具条按钮验证，两者走同一套命令）。

## 圈选入口改成全局热键（2026-11-09）

用户原话：“没必要搞那个圈选批注的键，就是把它的入口设成跟 ping 一样就行，不然屏幕上面多一个框还感觉怪怪的，Ping 的按键绑定支持了吗”。

结论：Ping 的热键本来就是可配置的，默认 `Ctrl+Alt+Space`，在桌宠设置里录制，存进桌宠配置，桌面端 `pet_hotkey_set` 换键，轮询 `GetAsyncKeyState` 实现按住显示、松开执行。标注层照同一套做。

改动：

1. 工具条去掉常驻的“圈选批注”按钮，只剩“清空标注”和“收起”。屏幕上不再多一个框。
2. 圈选入口改为全局热键，默认 `Ctrl+Alt+A`。按下即进框选态，拖完直接进 Ping 的截图编辑器。
3. 配置字段 `overlay.captureHotkey`，和 Ping 那条并排放在桌宠设置的“标注层”分组里，录制控件复用 `PetHotkeyField`；清空等于解绑。
4. 桌面端：`desktop_overlay_capture_hotkey_set` 换键，`desktop_overlay_take_capture` 给页面取挂起请求，`start_capture_watch` 在应用启动时按配置起轮询线程。
5. 层没开时按热键会先建窗再把请求挂起，页面挂载后自己来取；层开着就直接推 `overlay://capture` 事件。页面没有工具条入口，热键入是唯一路径。

验收：

- Rust `cargo test --bin Sunday desktop_overlay::` 4 条，覆盖配置缺省取默认、空串解绑、自定义值原样保留。
- 真机：热键前没有覆盖层窗口，按下 `Ctrl+Alt+A` 后窗口出现、根节点带 `overlay-root--annotating`、可点区域报成整屏 `[0,0,2560,1440]`、工具条只剩 1 个按钮；真鼠标拖 600,500 → 1100,800 后 `Sunday Capture` 窗口弹出，覆盖层退出框选态。
- 启动日志 `[overlay] capture hotkey: Ctrl+Alt+A` 证明配置被读到。

## 交互层：手绘笔迹、弹幕规则与代码审查（2026-11-09）

用户原话：“可直调用样式精致打磨一下，比如字幕，弹幕，表情包（图片），箭头，圈选等，让它们流畅一些，箭头和圈选更像手绘风格和手绘出现，弹幕流畅一点，不要一顿一顿地飘，弹幕位置调整一下，30%上方屏幕，速度根据长度调整快慢，越长越慢，设置中支持调节倍速、字体、字号。层改名作交互层，相似机制可以与ping环融合，减少未来维护工作量。对外开放API，可外部调用批注功能。对代码进行审查，不要出错或者低级漏洞或问题。”

改名：所有面向用户和模型的文案从“标注层”改为“交互层”，工具描述、托盘入口、设置分组、文档同步。窗口 label、命令名、接口路径不动，避免影响已接入的外部调用。

手绘笔迹：

- 箭头、矩形、椭圆、涂鸦全部用 `<path>` 手绘笔迹，不再用 `<line>/<rect>/<ellipse>`。
- 抖动由标记 id 派生的种子决定，同一标记每次重画是同一条线。
- 矩形四边分别抖动并在收笔处稍微出头，出头量不超过抖动幅度；椭圆按像素做径向抖动，大圈也不会抖成完美椭圆。
- 出现方式用 `pathLength=1` 加 `stroke-dashoffset` 从 0 长到 1，笔画是长出来的而不是贴上去。

弹幕：

- 位移改成 CSS 关键帧，跑在合成层；页面每帧不再写 transform，长句也不一顿一顿。
- 关键帧必须放在非 scoped 的全局 `<style>` 块：scoped 样式会重命名 `@keyframes`，JS 写进内联样式的动画名对不上，动画等于没跑。
- 轨道只在屏幕上方 30% 的带子里，锚点换算成页面坐标后按字高对齐成行，行距 = 字号 × 1.6 + 8。
- 速度按文字宽度估算，越长越慢，最多降 55%，倍速只做整体缩放。
- 寿命按句子长度估出跨屏时间（4 到 60 秒），动画时长永远不超过寿命，不会再飘到一半被抹掉。

设置：托盘菜单进“交互层设置”，可调弹幕倍速、字体、字号，改完立刻生效，不用重开窗口。能力开关与设置面板复用桌宠那一套。

对外 API：`agent_docs/interaction-layer-api.md` 记录了读状态、画标记、续画、清除、请用户圈选、读表情包图片六个入口，本机任何程序都能用。

## 代码审查修掉的问题

审查了 13 个位置，两条致命、若干一般问题，逐条对照代码确认真伪后修掉：

1. **致命：交互层关掉超过 10 秒再按热键打不开。** 看门狗拿上一轮会话的旧心跳判死新窗口，`desktop_overlay_open` 又从不复位心跳与 `ever_seen`。修法：建窗时 `begin_session()` 清空心跳并把 `opened_at` 置为当下；判死规则抽成纯函数 `session_is_dead`，报过心跳的会话按心跳超时判，没报过的按 20 秒加载宽限判，加载失败的页面也不会把不可见全屏窗口永远留在桌上。复现脚本先证红后证绿。
2. **致命：弹幕默认 3 秒寿命短于跨屏时间。** 一句二十来字的弹幕在宽屏上要飘六到九秒，走到三分之一就被抹掉。修法：store 按文字长度估出默认寿命，页面再把动画时长夹在寿命之内。
3. **一般：轨道按整屏比例摊进 30% 带子，锚点 90/180/270 只差 12 像素，20px 字号直接叠字。** 修法：按字高对齐成行，实测间距 40 像素。
4. **一般：可点区域每 1.5 秒上报的定时器没存句柄，页面销毁后还在跑。** 修法：存下来并在卸载时清掉。
5. **一般：几何取不到时换算比例是 0，坐标算成 Infinity/NaN，整层静默画不出来。** 修法：比例非法时退成 1。
6. **一般：空点集传给 `roughArrow` 会按下标取坐标崩掉。** 修法：长度检查前置。
7. **一般：清除接口没校验类型，`ids` 传字符串会按字符误删，`all` 传 `"false"` 被真值化成清空整屏。** 修法：store 与工具两层都校验类型。
8. **一般：图片资源只留一小时，标记最长能活 24 小时，长 ttl 图片标记必然裂图。** 修法：资源保留时间不短于标记上限。
9. **一般：页面缓存只在倍速/字号/字体/视口宽变化时失效，换显示器或窗口位置变了表情包停在旧坐标。** 修法：把覆盖层几何一起放进依赖。
10. **一般：图片弹幕的速度只按文字估，长短和速度脱钩。** 修法：速度用布局实际宽度。
11. **一般：读写图片的 `OSError` 会冒到工具层。** 修法：补捕并转成中文错误。
12. **一般：状态字典在 HTTP 轮询和工具执行两条线程上共享，没有锁。** 修法：给变更方法加可重入锁。

审查里判定不成立、没有改的：`/overlay/control` 没有来源校验（本机任意进程可清屏）——这是对外 API 的设计前提，`_copy_image` 已经把图片限制在工作区内，不构成任意文件读取；改成带 token 反而会让文档里的外部调用方式失效。60fps 重建手绘路径——箭头已缓存，其余标记数量有上限 400，先不改。

## 本轮验收结果

- 定向测试：前端 `desktop-overlay-model`、`overlay-danmaku`、`overlay-rough`、`tray-panel-model`、`ping-capture` 共 80 条通过；Python `tests/test_desktop_overlay.py` 48 条通过；Rust `cargo test --bin Sunday desktop_overlay::` 8 条通过；`vue-tsc --noEmit` 在 overlay、tray、rough、motion、pet/config 上没有报错。
- 重开窗口：关掉交互层等 12 秒再按热键，修复前 `after_reopen_3s = false`、`visible = false`、`inner_size = null`，修复后 `after_reopen_3s = true`、`visible = true`、`inner_size = [2560,1440]`、心跳 1.3 秒。
- 轨道：1384×779 视口、30% 带子上限 234，三条弹幕 top = 50/90/130，间距 40；全部在带子内。
- 速度与寿命：长句 ttl 14.53 秒、动画 10 秒，寿命过半时仍在向左移动；短句 3 秒已经飘完离场。
- 手势：箭头、矩形、椭圆路径都含二次曲线；`strokeDashoffset` 0.66 → 0.27 → 0.03 → 0，播放状态 `running`，笔画是长出来的。
- 表情包坐标：物理中心 [1280,720] 换算后落在 CSS [692.0,389.5]，实测中心 [691.99,389.49]，偏差 0.0 像素。
- 外部 API：`POST /overlay/control {"action":"capture"}` 之后页面进 `overlay-root--annotating`，`capture_requested` 变回 false。
- 证据图：`.lam/artifacts/interaction-layer-final.png`。
