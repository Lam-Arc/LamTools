# 附件闭环：从选择器到模型输入

日期：2026-11-05
分支：`sunday/m16-projection`（worktree `.worktrees/m16`）
提交：`2d73437b`（附件进入回合）、`01f47f47`（Android 真实可用性）

## 要解决的问题

附件此前止步于托盘：记录写进了库、列表能查、删会话能一起清掉，但回合拿到的只有文字。
Agent 于是对着一个从没读过的文件作答——附件名出现在对话里，内容从未到过模型。

这一轮要把这条链打通，并顺手把设备上真正拦住使用的东西修掉。

## 现在的事实

### 附件由核心管理，Android 只负责选文件

- `core/sunday-core/crates/sunday-host/src/attachments.rs`：复制导入、去重、50 MB 上限、沙盒校验、
  MIME 与预览类型推断、按会话登记、按消息绑定。
- 路由（`projects_http.rs`）：`POST /sessions/{id}/attachments/reference`、
  `GET /sessions/{id}/attachments`、`GET /attachments/{id}`、
  `GET /attachments/{id}/download`（`content` 同义）、`GET /attachments/{id}/preview`、
  `POST /attachments/{id}/open`（本核心不开外部程序，明确回 501 而不是假装成功）。
- 界面早就在调这三个读接口，缺的一直没有；`download` 同时修掉了「图片被当文本读」的老问题。

### 内容真的进了模型输入

`AttachmentStore::briefing` 把附件变成两样东西：

- 文本：正文内联进提示，用**由内容摘要派生的定界符**包起来（文件不可能包含自己哈希的字符串，
  所以正文伪造不了结束标记），超过 32 KiB 截断并注明「只放了开头部分」。
- 图片：`vision` 打开时作为原生 `ImageInput` 送进 `Message::UserMultimodal`；
  关闭时明确写「当前模型没有开启图片输入，看不到这张图片」，并禁止它猜。
- 其它格式：明确写「这个格式暂时无法提取内容，只保存了文件本身」。
- 记录不存在：明确说「附件记录已经不存在，请让用户重新添加」。

`Command::TurnStart` 多了一个 `input_json`，附件随指令一起进日志；`projection.rs` 把
`input` 里的附件还原成用户消息的一部分，所以重开会话仍能画出附件条。

### Android 选择器

- `FilePickerBridge.kt`：系统文档选择器（`OpenMultipleDocuments`），在临时授权内把选中的
  文件复制进 `filesDir/picked/`，只把真实路径交回界面。**不留 `content://`**，也就没有
  随时会失效的外部引用，也不占用用户的持久授权名额。
- `files.rs`：Rust 侧发起、按请求 id 等一条回信；取消是空列表、单个文件失败带文件名和原因、
  只有选择器一直不返回才走超时（900 秒）。
- 界面侧 `appRuntime.capabilities.files.pick()` 走这条桥，上传依旧走桌面同一条
  `/attachments/reference` 导入路径。

## 设备上跑出来的三件事

装的是真 APK，走的是真界面：点「添加附件」→ 系统文件选择器 → Downloads → 选文件 → 发送。

### 1. 分屏状态会让输入栏整条消失

设备上恢复了分屏布局，但分屏层在手机端不挂载（`v-if="platform !== 'mobile'"`），
`workspace-shell--split` 却照样加上，输入栏去读一份没人发布的几何量，宽度算成 1 像素。

修法是把两处判断合成一个：`splitEnabled` 同时要求「不是手机端」。一行守卫，没有第二套布局。

### 2. 键盘一弹出就盖住输入栏

窗口是 edge-to-edge，键盘不让窗口变矮，样式表看不见键盘。CSS 里早就留了
`--native-keyboard-inset` 这个口子，但没有任何宿主给它赋值。

现在 `KeyboardBridge.kt` 监听 IME inset，Rust 转成 `keyboard-inset` 事件，界面写成 CSS 变量，
输入栏随之抬到键盘上方（设备实测：`--native-keyboard-inset: 352px`，输入栏从 y≈1410 抬到 882）。

### 3. 模型宁可去读沙盒路径，也不看已经内联的内容

输入框里带着 `@"/data/user/0/com.lamtools.sunday.core/attachments/att-…/sunday-note.txt"`。
3B 模型看到路径就去 `read_file`，工具按规矩拒绝（绝对路径），它再回头告诉用户「读不到」。

改成：给模型的文本里，这个应用自己的副本路径一律换成文件名；指令放到提示末尾
（小模型读末尾比读中间可靠）。日志里记的是用户说的话，不是拼给模型的那段。

## 设备实证

| 场景 | 结果 |
| --- | --- |
| 点「添加附件」→「文件」 | 系统选择器打开（`documentsui/PickActivity`） |
| 选中 `sunday-note.txt` | 复制进沙盒并导入：`POST …/attachments/reference -> 200`，记录 `att-20b576b4deec5416` |
| 重复选同一个文件 | 返回同一条记录（按内容摘要去重），不产生第二份副本 |
| 发送 | `command_accepted` 带 `input`（含 attachment 项）与用户原文 |
| 模型收到的提示 | 含 `<<<20b576b4deec5416 … SECRET-WORD-7788 … >>>`，即文件真实内容 |
| 模型回答 | 原文引用 `SECRET-WORD-7788the file arrived` |
| 强停后重开 | 会话在、附件条在、记录与副本在（`attachments.json` + `attachments/att-…/sunday-note.txt` 内容一致） |
| 51 MB 文件 | 选择器拒绝：`超过 50 MB`，不产生记录 |
| 图片（vision 关） | 模型明确回「当前模型没有开启图片输入，无法直接查看这张图片的内容」 |

残留：小模型偶尔仍会先调一次 `read_file`（用文件名），失败后才读内联内容。这是模型行为，
不是链路问题；换更强的模型或以后做工具感知的附件读取可以消掉这一步。

## 测试

| 范围 | 结果 |
| --- | --- |
| `cargo test -p sunday-host --lib` | 87 passed, 1 ignored |
| `cargo test --lib`（android-host） | 56 passed |
| 界面相关子集 `vitest`（审批链/附件托盘/选择器/投影/引用） | 59 passed |
| `npx vue-tsc --noEmit`（主配置） | 通过 |
| `cargo clippy`（sunday-host / sunday-llm / android-host） | 仅剩既有告警（`type_complexity`、`div_ceil`、`secrets::Mode` 未构造） |
| APK 构建 + 校验 | `android_project.py all --debug --target x86_64`：原生库、LifecycleBridge、FilePickerBridge、KeyboardBridge、MainActivity 全在 |

界面全量 `vitest` 在本 worktree 有 41 个与本次无关的失败（样式令牌、左栏、wiki、产出面板等），
改动前就是这个状态，未纳入本次结论。

## 没做的

- 图片原生输入（`vision`）只做了链路上的准备与「看不到就说看不到」的诚实路径，设备上没用
  能看图的模型验证过原生图片输入。
- `/attachments/{id}/open` 明确 501：用系统程序打开附件属于宿主职责，还没接。
- 多选一次挂多个文件的设备复测没做，机制与单文件相同（界面早已按数组处理，单测覆盖多文件内联）。

## 顺带修掉的

- `http_surface.rs`：非 `application/octet-stream` 的回复一律当文本，图片被
  `from_utf8_lossy` 洗过一遍，缩略图永远是空白。改成只有 JSON 和 `text/*` 走文本。
- `AndroidSettings.vue`：`config` 从 `null` 起步，模板直接解引用，类型检查报 5 处、首帧会崩；
  改成空记录起步。
- `@tauri-apps/api` 2.11.1 → 2.12.4：Rust 侧 Tauri 已是 2.12.5，CLI 因此拒绝构建。
