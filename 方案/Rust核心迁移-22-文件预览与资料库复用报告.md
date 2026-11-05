# 文件预览与资料库复用

日期：2026-11-05
分支：`sunday/m16-projection`
提交：`e99abe83`（引用解析 + 资料库 + 资料上传）、`09519cfc`（CSP 与启动调用）

## 复用了什么，补了什么

先看桌面侧怎么做的，再把同一份语义接到 Rust Core，没有另起一套。

| 界面已有的能力 | 桌面实现 | 现状 |
| --- | --- | --- |
| 引用解析 `workspace://x`、`/artifacts/x.png`、只写文件名 | `app/file_references.py` | 移植成 `file_refs.rs`，规则一致，边界改成「必须落在授权目录内」 |
| 读取引用字节 | `GET /files/read-reference` | 已接，按扩展名给内容类型 |
| 用系统程序打开 | `POST /files/open-reference` | 明确 501：这是宿主职责，核心没有窗口管理器 |
| 资料库（方案） | `方案/` 下的 markdown + frontmatter | 移植成 `plan_library.rs`：列表、文件夹、新建、重命名、移动、收藏、删除 |
| 资料上传 | multipart 落到 `资料/` | 手机选择器只给沙盒路径，所以加 `POST /projects/{id}/artifacts/reference`，落点相同 |

资料库不是新存储：一份方案就是一个 markdown 文件，标题取第一个 `# `，状态/摘要/收藏在
frontmatter 里，和桌面同一批文件。

## 设备上又抓到三个只有真机才看得见的

1. **缩略图全是裂图**：CSP 只允许 `img-src 'self' data:`，界面用 `blob:` 显示图片，
   于是一个刚刚成功下载的文件被浏览器拒绝渲染。补上 `blob:`（图片与音视频）和
   `font-src data:`。设备复核：`@sunday-pic.png` 下面现在显示的是那张绿色方图。
2. **一启动就弹红色提示**：`goal.list` / `plugin.ui.list` 在这个核心里是 "method not found"。
   核心确实没有目标和插件面板，空列表是事实，改成空列表后启动零报错。
3. 控制台里那条 `Refused to load the font 'data:font/woff2…'` 也是同一次 CSP 收紧造成的。

另外把附件文本预览截到 64 KiB（按字符边界切），卡片只显示十行，不该让一整份日志在界面
线程上被 JSON 解析。

## 验证

| 层级 | 内容 | 结果 |
| --- | --- | --- |
| 单元 | 引用解析 10 条：别名、同性文件、歧义、越界、scheme、file:// 转义 | 通过 |
| 单元 | 资料库 11 条：新建、重名拒绝、嵌套文件夹、移动、收藏写回、删除、路径越界、无 frontmatter 的文件 | 通过 |
| 契约（路由） | 引用 resolve/read/open 三步；沙盒外 work_root 被拒；资料库往返；资料上传去重与重名编号 | 通过 |
| 汇总 | `cargo test -p sunday-host --lib` | 113 passed, 1 ignored |
| 界面 | 计划库/引用/预览/编写器子集 `vitest` | 53 passed |
| 类型 | `vue-tsc --noEmit`（主配置） | 通过 |
| 设备 | 缩略图渲染、启动无报错、资料库路由可达 | 通过 |

## 效率记录（这一轮）

- APK 构建 2 次（第一次为看清缩略图与启动报错，第二次验证 CSP 与空列表修复后复装），
  设备往返 2 次，没有重复安装同一版本。
- 没有为查看界面另开脚本：直接用既有的 `android_ui.py` 与 `logcat`，日志里一次就拿到
  CSP 拒绝与两条 method not found。
- 三次失败都是补丁脚本的锚点问题（`eol.join(str)` 把字符串按字符拼），修正方式固定为
  「先 split 再 join」，没有重复试同一个命令。
- 学习到的一条：字符串批量替换必须把多行文本 `split("\n")` 后再 `join(eol)`，否则 CRLF
  文件里会得到逐字换行的垃圾。

## 没做

- 资料库的 UI 交互没在设备上逐项点过（新建/移动/收藏），核心侧已有契约测试覆盖；
  这类协议无需模拟器，按分层原则不再复测。
- `/files/open-reference`、`/attachments/{id}/open` 仍是 501：Android 上用系统应用打开
  文件需要 FileProvider 与清单条目，属于宿主平台能力，留作独立一项。
- 多模态原生输入仍未用真实视觉模型验证过（本机只有 qwen2.5 文本模型）。

## 补上：用系统应用打开文件

Android 从 API 24 起不接受把 `file://` 交给别的应用，必须走 FileProvider 的 `content://`
加一次性读授权。这件事只有宿主能做，所以核心留了一个口子：
`Projects::set_opener` 装上回调后，`/files/open-reference` 与 `/attachments/{id}/open`
就真的打开文件；没装时仍然回 501，不会假装成功。

- Kotlin `OpenFileBridge.open(path, mime)`：生成 content URI，`ACTION_VIEW` + 读授权；
  失败返回原因文本，界面上能看见。
- 生成的工程里 Tauri 已经声明了 FileProvider（authority `${applicationId}.fileprovider`，
  paths 只放开 cache 与 external），所以待分享的副本放进 `cache/open/` 再借出去，
  不需要改清单。已核对构建产物：`aapt2 dump xmltree` 里 authority 是
  `com.lamtools.sunday.core.fileprovider`，与运行时算出来的完全一致。
- APK 校验清单加上了 `OpenFileBridge`。

验证到宿主边界为止：路由层有契约测试（无 opener → 501；装了就带着真实路径与 MIME 被调用）。
「点开之后真的弹出看图应用」这一步没能在自动化里点到（缩略图上的菜单不可靠命中），
记录为限制，不再反复试。
