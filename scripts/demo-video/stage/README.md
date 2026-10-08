# 真实前端渲染台（stage）

不录屏、不驱动桌面窗口：把 **真实的 `core/ui` 应用**挂在一个无头浏览器里，用一张
时间表喂给它状态，然后逐帧截图。画面是产品自己画出来的，所以"窄屏"是真的窄屏
布局、"流式"是真的在长出来的文字，而不是把截图缩放或贴一张伪造的图。

这条流水线解决的是之前卡住的那件事：**不必等真实任务跑完才有素材**。一段对话、
一次工具调用、一条子代理过程行，都可以先用时间表写出来看效果；等真实数据到手，
把对话内容换掉即可，画面逻辑一模一样。

---

## 一、怎么跑

```powershell
# 出一段片子
node scripts/demo-video/stage/capture.mjs --scene first-look

# 只取静帧（审排布用，快）
node scripts/demo-video/stage/capture.mjs --scene first-look --at 4.0,12.5,18.5

# 常用开关
--scene <名字>      scenes/<名字>.ts
--theme light|dark  覆盖场景里的主题（片子层面的决定，不用改每个场景）
--fps 30            帧率
--crf 18            画质
--audio <wav>       合入音轨（与 motion 那边共用同一张时间表）
--width/--height    画布尺寸，默认 1920x1080
--scale 2           高清倍图
--captions 0        关掉分镜字幕与计时，出干净版
--keep-frames       保留中间帧
```

产物落在 `E:/LamDemo/stage/<scene>/`（`<scene>.mp4` 或 `stills/`）。

### 依赖

这个目录下有一条 **junction**：`stage/node_modules` → `core/ui/node_modules`。
`capture.mjs` 会在缺失时自动创建（Windows 用 `mklink /J`，不需要管理员权限）。
这样 stage 借用产品自己的整棵依赖树，**全图只有一份 vue**——两份 vue 会白屏，
这是官网展示区已经踩过的坑。所以跑之前先确保 `core/ui` 装好了依赖：

```powershell
cd core/ui; npm ci
```

---

## 二、它是怎么搭起来的

```
      ┌─ index.html / src/main.ts ──────────── 舞台外壳（截的就是这一层）
      │    环境底色 · 光标 · 分镜字幕 · 计时
      │    #frame 是一个 iframe，位置和尺寸由场景给
      │        │
      │        └─ app.html / src/app.ts ────── 产品宿主
      │              真实 LamToolsApp + 内存后端
      │              window.stage.renderFrame(t)
      │
      └─ scenes/<名字>.ts ─────────────────── 时间表：frame(t) + data(t)
```

### 为什么产品要放进 iframe

产品的根节点是铺满窗口的（`position: fixed` / 100vh 那一类），放在普通 div 里会
直接冲出去铺满整个画布。放进 iframe 之后，**iframe 的尺寸就是产品的窗口尺寸**：
改这个盒子 = 改产品的真实布局，响应式是真的在生效。官网展示区用同一招把产品关
进展区的框里。

### 状态怎么喂进去

产品的状态只有一个来源：后端推给它的**快照**。真实链路里这来自
`thread/snapshot` 通知，渲染台照搬这条路径：

```ts
backend.pushSnapshot(snapshot)   // → transport.subscribe 收到 thread/snapshot
```

于是"文字在一点点长出来"不需要动产品一行代码：每帧推一份快照，快照里那条消息
的正文就是当前该有的长度。

### 一帧是怎么走的

```
驱动网页 renderFrame(t)
   → 外壳按 scene.frame(t) 摆好 iframe 的位置与尺寸、画上光标
   → 转交 iframe：产品宿主按 scene.data(t, revision) 造出新快照并推给产品
   → 等 Vue 落地 + 两帧 rAF
   → 截图
```

`renderFrame(t)` 返回的 Promise 在**画面稳定之后**才 resolve，所以驱动可以毫无
顾忌地一帧一帧走。

---

## 三、怎么写一个场景

`scenes/<名字>.ts` 导出两件事：

```ts
export default {
  id: 'first-look',
  duration: 24,

  // 产品窗口摆在哪、多大，叠在上面的东西（光标、点击涟漪）
  frame(t) {
    return {
      rect: { x: 120, y: 96, w: 1680, h: 888, radius: 20 },
      overlay: cursorHtml({ x, y, press }),
      caption: { title: '…', hint: '…' },   // 审阅用，--captions 0 关掉
    }
  },

  // 产品这一刻的状态
  data(t, revision) {
    return {
      projects: [PROJECT],
      sessions: [SESSION],
      threadId: THREAD,
      theme: 'dark',
      composerDraft: reveal(PROMPT, t, 3.0, 10),  // 输入框里正在打的字
      snapshot: snapshotAt(TURNS, t, { threadId: THREAD, revision, idPrefix: 'stage' }),
    }
  },
}
```

对话本身只写"什么时候、说什么"：

```ts
const TURNS = [{
  id: 'one',
  at: 5.8,                       // 你的话什么时候出现在记录里
  prompt: '把上周的数据整理成一份周报，按上次的格式',
  steps: [
    { kind: 'thinking', at: 6.0,  text: '先看上周的数据…', cps: 24 },
    { kind: 'tool',     at: 8.4,  text: '…', title: '读取上次的周报',
      tool: 'read_file', args: { path: 'reports/…' } },
    { kind: 'command',  at: 10.2, text: 'python tools/weekly.py …', title: '汇总上周数据' },
    { kind: 'answer',   at: 12.0, text: ANSWER, cps: 26 },
  ],
}]
```

`cps` 是每秒"打"多少字，文字长度就是这一刻该显示的长度。`at` 与 `cps` 定死了
到达时刻，**没有任何 setTimeout、没有 CSS 动画**——这就是确定性的来源。

### 出字速度要按片子定，不按真实模型定

真实模型的吐字速度是给"人在用"的，放进片子里就是拖沓。两个速度分开定：

| 谁在出字 | 建议 | 为什么 |
|---|---|---|
| 自己在输入框里打 | 12–16 字/秒 | 快了就不像人在打字 |
| 它的回答正文 | **70–80 字/秒** | 比阅读速度再快一截：字是"落下来"的，不是让人等着读完的 |
| 过程行 / 路径 / 命令 | 50–60 字/秒 | 本来就不当散文读 |

段与段之间不要留缝：上一步的字落完，下一步紧接着开始，间隔压到 0.3–0.8 秒。
片子里"什么都没发生"的时间超过一秒，观众就开始觉得慢。

时间刻度跟 motion 那边共用：100 BPM，一拍 0.6 秒，一小节 2.4 秒。两半片子可以
对同一张表来剪。

---

## 四、确定性：规则和陷阱

**必须守住的三条**

1. **CSS 动画与过渡全关**（`index.html` / `app.html` 里的 `*{transition:none;animation:none}`）。
   任何跟墙钟走的动效都会让同一帧两次渲染不一致。
2. **时钟钉死**：驱动在浏览器上下文里 `setFixedTime`，`Math.random` 换成种子伪随机。
3. **快照的版本号必须递增**。产品会丢掉 revision 不比手上新的快照——不递增就等于
   什么都没推，画面停在第一帧。（`renderFrame` 里每帧 `revision += 1`。）

**踩过的坑**

- **产品会冲出容器**：根节点铺满窗口，必须用 iframe 关，不能拿 div 套。
- **平滑滚动不是 CSS**：`scroll-behavior` 关不掉 JS 里的 `scrollIntoView({behavior:'smooth'})`。
  产品会把新消息滚进视野，所以两边的入口都覆盖了 `scrollIntoView` 强制瞬时。
- **输入框里的字**：输入框是组件自己的状态，不走快照。做法是直接设 `textarea.value`
  再派发 `input` 事件，让 Vue 的 `@input` 接住——即"用真手打字"，而不是造假画面。
- **字体没就绪就截第一帧**，中文会掉字重。驱动里等了 `document.fonts.ready`。
- **进程行只在回合进行中显示**：一条回合做完了，产品会把思考与工具调用收起来。
  所以"过程行"这类要给人看的东西，场景必须安排在**回合还在跑的时候**。
- **两张 vue 会白屏**：靠上面那条 junction 保证全图只有一份。

**还没解决的**

- 产品内部的滚动条会随内容出现，属于它的真实行为，目前没有刻意隐藏。
- 真实后端的其他事件（审批、子代理、工作流画布）还没有对应的假事件；要用到时
  再补 `push('<method>', params)`。

---

## 五、文件

| 文件 | 作用 |
|---|---|
| `index.html` / `src/main.ts` | 舞台外壳：底色、iframe 框、光标、字幕、计时 |
| `app.html` / `src/app.ts` | 产品宿主：真实 `LamToolsApp` + 内存后端 + `renderFrame` |
| `src/runtime.ts` | 内存传输与 RPC：应用问什么都当场答，另附 `pushSnapshot` |
| `src/snapshot.ts` | 把"什么时候说什么"编成产品认的快照（`CoreAppSnapshot`） |
| `src/timeline.ts` | 时间词汇表：`seg / ease / stagger / reveal / cursorHtml` |
| `scenes/*.ts` | 一段片子一张时间表 |
| `capture.mjs` | 起服务、逐帧驱动、编码；静帧模式 |
| `vite.config.ts` | 只做两件事：指到 `core/ui`、起在 5299 |
