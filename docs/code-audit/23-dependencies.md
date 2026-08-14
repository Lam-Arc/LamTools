# 23 依赖安全与健康 审计报告

> 审计日期：2026-08-13（联网核实，OSV / GitHub Advisory / npm audit）
> 审计员：第 23 区（依赖安全与健康）
> 仓库：E:\LamTools（Windows + Git Bash）

## 1. 概况（依赖面统计）

| 生态 | 清单文件 | 直接依赖数 | 锁定方式 | 审计结果 |
|---|---|---|---|---|
| Python | core/pyproject.toml | 运行时 6 + optional（dev/server/desktop 各 4-5） | **无 lock 文件**（仅有下限约束） | 约束版本全部查 OSV；另以全局环境实际安装版本核对 |
| npm（ui） | core/ui/package.json + package-lock.json | prod 21 / dev 7 | lock 已提交 | `npm audit --omit=dev`：4 项（2 高危传递 + 2 中危直接） |
| npm（desktop） | core/desktop/package.json + package-lock.json | prod 4 / dev 5 | lock 已提交 | `npm audit --omit=dev`：1 项（nanoid 高危传递） |
| npm（website） | website/package.json + package-lock.json | prod 3 / dev 3 | lock 已提交 | `npm audit`：**0 漏洞** |
| Rust | core/desktop/src-tauri/Cargo.toml + Cargo.lock | 直接 6 + build 1 | Cargo.lock 已提交（4576 行） | 关键 crate 查 OSV：仅 1 条信息性公告（gtk 不再维护） |

- Python 实际环境（无 venv，全局 Python 3.14）：httpx 0.28.1 / SQLAlchemy 2.0.51 / aiosqlite 0.22.1 / python-docx 1.2.0 / pypdf 6.14.2 / python-multipart 0.0.27 / fastapi 0.136.1 / uvicorn 0.46.0。
- Rust 关键解析版本：tauri 2.11.5、tauri-build 2.6.3、wry 0.55.1、tao 0.35.3、rfd 0.17.2、open 5.4.1、url 2.5.8、reqwest 0.13.4、tokio 1.53.1。

**问题统计：S1×1，S2×4，S3×2，S4×1（组合条目），合计 8 条。**

## 2. 问题清单

- **[S1] pypdf 约束过低（>=6.10.0），存在多个 DoS 公告（含 2 个 HIGH 无限循环），直接影响 PDF 解析功能**
  - 包与版本：pypdf，约束 `>=6.10.0`；当前实际安装 6.14.2；修复版 >=6.15.0（最新 6.16.0）。
  - CVE 与严重度：OSV 共 19 条公告，全部为 DoS（无限循环 / 内存耗尽），其中 2 条 HIGH：GHSA-5xf7-4p34-54qr（未终止内联图像无限循环，修复 6.14.1）、GHSA-g867-7843-wf8q（ASCII85/ASCIIHex 过滤器无限循环，修复 6.14.2）；17 条 MODERATE（跨引用流、字体宽度、FlateDecode 预测参数、XMP 流等导致的 CPU/内存耗尽）。约束下限 6.10.0 命中全部；当前环境 6.14.2 仍命中 4 条 MODERATE（GHSA-fp3f-mc75-235c、GHSA-fwg2-594c-jp42 及 PYSEC-2026-3655/3656，修复 6.15.0）。
  - 问题：`core/src/lamtools_core/tool/document_normalize.py` 使用 `PdfReader(path, strict=False)` + `page.extract_text()` 解析用户提供的 PDF，恶意 PDF 可致解析挂起（无限循环）或内存耗尽。
  - 影响：直接影响当前用法——文档归一化工具对不可信 PDF 输入无 DoS 防护；属本地文件触发的拒绝服务（需用户打开恶意 PDF），非远程利用。
  - 修复建议：将 pyproject.toml 约束提升为 `pypdf>=6.15.0`（覆盖全部公告）并重新安装；如环境已装 6.14.2，`pip install -U pypdf` 即可。成本极低，无 API 变更。

- **[S2] mermaid 11.16.0 未达修复版 11.16.1（CSS 注入 / 原型污染 / DoS 共 5 条公告）**
  - 包与版本：mermaid，lock 解析 11.16.0（约束 `^11.15.0`）；修复版 11.16.1。
  - CVE 与严重度：GHSA-6x64-9x62-f2gx（MODERATE，CSS 注入可作用于图元兄弟元素，CWE-94）、GHSA-3rrr-jr9j-h3q3（MODERATE，Architecture 图原型污染）、GHSA-2v8p-3f2j-5mp7（MODERATE，XY 图无限循环 DoS）、GHSA-rhh3-jpg6-66xh（MODERATE，雷达图 DoS）、GHSA-c4c3-pg64-4m4v（LOW，配置 API 原型污染）。全部修复于 11.16.1。
  - 问题：`core/ui/src/components/MarkdownRenderer.vue` 将 Markdown 中的 ` ```mermaid ` 代码块经 `mermaid.render()` 渲染，内容来源为 LLM/Agent 消息（`MessageView.vue` 的 `part.content`，可能含提示注入产物或导入的对话）。
  - 影响：影响当前用法——渲染不可信 Markdown 时，恶意图可注入 CSS 影响图中元素外的兄弟节点（界面篡改）、触发渲染线程无限循环（UI 卡死）。属中危（本地/内容驱动，非远程未认证利用）。
  - 修复建议：将约束提升为 `mermaid>=11.16.1` 并刷新 lock（`npm update mermaid`），纯补丁级升级，零 API 变更。

- **[S2] dompurify 3.4.12 存在 XSS 公告（GHSA-55q2-fjhq-7xh7），当前调用方式不受影响但建议立即升级**
  - 包与版本：dompurify，lock 解析 3.4.12（约束 `^3.4.11`）；修复版 3.4.13。
  - CVE 与严重度：GHSA-55q2-fjhq-7xh7（MODERATE，CWE-79）——`IN_PLACE` 模式清理过程中移除 hook 会遗留可执行的分离子树导致 XSS。
  - 问题：`MarkdownRenderer.vue` 对 `marked` 输出的 HTML 执行 `DOMPurify.sanitize()`（默认返回字符串模式），未使用 `IN_PLACE` 模式、未在清理中移除 hook——**当前调用方式不触发该漏洞**。
  - 影响：不影响当前用法；但因 DOMPurify 是渲染管线的最后一道防线（XSS 防护核心），且修复版已发布，升级零成本。
  - 修复建议：升级至 `dompurify>=3.4.13` 并刷新 lock。

- **[S2] nanoid 传递依赖过旧（ui 3.3.12 / desktop 3.3.16），2 条高危 DoS 公告，实际调用不受影响**
  - 包与版本：nanoid（传递依赖，经由 postcss → vue 的 @vue/compiler-sfc 及 vite 引入）；ui lock 3.3.12、desktop lock 3.3.16；修复版 3.3.17。
  - CVE 与严重度：GHSA-28wg-ghj8-5hjv（HIGH，CVSS 5.9，非安全生成器传入负数 size 无限循环，修复 3.3.16）、GHSA-2v37-7h3g-55p8（HIGH，CVSS 5.9，自定义生成器 size=0 无限循环，修复 3.3.17）。
  - 问题：postcss 仅以固定正数 size 调用 nanoid 生成唯一 ID，攻击者无法控制 size——**实际不可利用**；属"高危但影响未用功能"。
  - 影响：无实际产品影响（构建期 ID 生成）；npm audit 计入高危导致告警噪音。
  - 修复建议：`npm update nanoid`（或整体刷新 lock）使 postcss 的 `^3.3.x` 约束解析到 3.3.17+；desktop 需同样处理。

- **[S2] postcss 8.5.15（ui 传递依赖）存在源映射路径遍历（HIGH），仅构建期、desktop 已修复**
  - 包与版本：postcss，ui lock 8.5.15（经 vue→@vue/compiler-sfc 与 vite 引入）；修复版 >=8.5.23；desktop lock 已为 8.5.23（干净）。
  - CVE 与严重度：GHSA-r28c-9q8g-f849（HIGH，CVSS 7.5，CWE-22，sourceMappingURL 路径遍历可泄露任意 .map 文件，修复 8.5.18）、GHSA-fxqj-rqcc-2cmp（MODERATE，8.5.17 修复不完整，`from` 未设时可读任意 .map 文件，修复 8.5.23）。
  - 问题：仅作用于构建期处理"带前序 sourceMappingURL 的 CSS"这一场景；本项目构建管线不处理攻击者控制的 CSS，**实际不可利用**。
  - 影响：无运行时影响（构建期组件）；因 vue 的 compiler-sfc 挂载在 prod 依赖树，npm audit --omit=dev 仍会报告。
  - 修复建议：ui 包刷新 lock 使 postcss 升至 >=8.5.23（与 desktop 对齐），`npm update postcss` 即可。

- **[S3] gtk 0.18.2 不再维护（RUSTSEC-2024-0415），rfd 的 Linux 传递依赖**
  - 包与版本：gtk（gtk-rs GTK3 绑定），Cargo.lock 0.18.2，经 rfd 0.17.2（Linux 文件对话框）传递引入。
  - CVE 与严重度：RUSTSEC-2024-0415（信息性，无 CVE 编号）——gtk-rs GTK3 绑定上游宣布不再维护，未修复的潜在内存安全问题不再得到维护。
  - 问题：本项目目标平台为 Windows（WebView2），gtk 仅参与 Linux 目标编译。
  - 影响：对当前 Windows 产物无影响；未来若发布 Linux 版本需关注 rfd 对 GTK4 的迁移（rfd 0.17 仍走 GTK3）。
  - 修复建议：暂无需处理；跟踪 rfd/gtk-rs 迁移计划，Linux 打包前再评估。

- **[S3] ui 包 dev 工具链存在高危 DoS 公告（brace-expansion、undici），仅构建/测试环境**
  - 包与版本：brace-expansion（经 vite/vitest 链传递，HIGH DoS：指数级展开 / 内存耗尽，含 CVE-2026 系列 3 条）、undici（经 vitest/jsdom 测试链传递，HIGH：CRLF 注入、cookie 属性注入、下游响应失同步等多条公告）。
  - CVE 与严重度：brace-expansion：GHSA-…（DoS 类，HIGH）；undici：GHSA-…（CRLF 注入 / 响应失同步 / cookie 注入，HIGH）。均为 dev-only（`--omit=dev` 下不出现）。
  - 问题：仅影响开发者本机构建/测试与 CI 环境，不进入发布产物。
  - 影响：无产品影响；CI 运行 vitest 时理论上可能受影响（需攻击者控制测试依赖内容，现实中不可达）。
  - 修复建议：下次 `npm update`（dev 依赖）时一并刷新；不阻塞发布。

- **[S4] 版本过时建议（无已知 CVE，升级成本低）**
  - 包与版本：
    - katex 0.17.0 → 最新 0.18.4（落后 1 个 minor；`MarkdownRenderer.vue` 用于数学渲染，0.17 无已知 CVE，但 0.18 为活跃主线）
    - marked 18.0.6 → 18.0.9（落后 3 个 patch，渲染管线核心，建议跟进）
    - vue：ui 3.5.38 / desktop 3.5.40 / website 3.5.41（最新 3.5.41）
    - vite：ui 8.0.16 / desktop 8.1.5 → 最新 8.2.1；vitest 4.1.9 → 4.1.10；jsdom 29.1.1（最新）
    - fastapi 约束 `>=0.137.2` → 最新 0.141.1；uvicorn `>=0.49.0` → 最新 0.52.2；sqlalchemy 2.0.51 → 最新 2.0.52（约束均无上界，直接升级即可）
    - typescript 6.0.3（最新已 7.0.2）、pinia 3.0.4（最新已 4.0.3）：均为 major 变更，**建议维持当前 major**，等生态适配后再评估
  - CVE 与严重度：无已知 CVE。
  - 问题：依赖面整体非常新（vite 8 / TS 6 / vue 3.5 / tauri 2.11 均为当季版本），仅少量 patch/minor 落后。
  - 影响：无安全影响；跟进 patch 版可保持修复通道畅通。
  - 修复建议：对 Python 提升下限约束并重装；npm 侧 `npm update` 刷新 lock（dev 与 prod 一起）；TS 7 / Pinia 4 不急于升级。

## 3. 该区 Top 3 问题

1. **pypdf 约束过低（S1）**：19 条 DoS 公告、含 2 条 HIGH 无限循环，且 `document_normalize.py` 直接用 `PdfReader` 解析用户 PDF；把下限提到 `>=6.15.0` 即可全量修复，成本最低收益最大。
2. **mermaid 11.16.0 差一个补丁版（S2）**：LLM 输出中的恶意图可造成 CSS 注入与渲染 DoS，`^11.15.0` 约束下 `npm update mermaid` 即可到修复版 11.16.1。
3. **ui 传递依赖 postcss/nanoid 高危公告（S2）**：实际不可利用（构建期、固定参数调用），但被 `npm audit --omit=dev` 计入高危并产生告警噪音；一次 lock 刷新即可清零，且 desktop 侧 postcss 已是修复版，两侧不一致。

## 4. 亮点

- **Tauri 2.11.5 已包含最新安全修复**：GHSA-7gmj-67g7-phm9（Origin Confusion 允许远程页面调用本地 IPC，修复版 2.11.1）在当前解析版本之上；wry 0.55.1 / tao 0.35.3 / rfd 0.17.2 / open 5.4.1 / url 2.5.8 / reqwest 0.13.4 / tokio 1.53.1 在 OSV 中均无匹配公告。
- **Python 依赖安全基线良好**：httpx 0.28.1、SQLAlchemy 2.0.51、aiosqlite 0.22.1、python-docx 1.2.0、python-multipart 0.0.32、fastapi 0.137.2、uvicorn 0.49.0、pytest 9.1.1 在其版本上均无已知 CVE；且大部分已是或接近最新版。
- **website 包 npm audit 0 漏洞**；desktop 的 postcss 已处于修复版（8.5.23）。
- **无 S1 级 RCE/反序列化类漏洞**：核心渲染链（marked 18.0.6、katex 0.17.0、vue 3.5.x、@codemirror 系）OSV 全部干净；DOMPurify 采用默认安全模式调用。
- Rust 直接依赖清单精简（6 个直接依赖），无多余攻击面。

## 5. 审计范围与方法（含实际执行的命令与网络结果）

**范围**：core/pyproject.toml（运行时 + optional dev/server/desktop）；core/ui、core/desktop、website 的 package.json 与 package-lock.json；core/desktop/src-tauri/Cargo.toml 与 Cargo.lock。

**执行的只读命令**：
- 依赖提取：`node -e` 解析三个 package-lock.json 的 `packages['node_modules/<pkg>'].version`；Python 脚本解析 Cargo.lock 关键 crate 版本。
- npm：`npm audit --omit=dev --json`（ui / desktop / website，只读查询 registry）+ 全量 `npm audit --json`（核对 dev 项）。网络正常，返回真实审计结果。
- OSV API：`POST https://api.osv.dev/v1/query`（curl 与 Python urllib 双通道），按包名+版本精确匹配 PyPI / npm / crates.io 公告；另查询 `https://api.osv.dev/v1/vulns/<GHSA-id>` 获取修复版本区间（如 pypdf 两条 HIGH 的 fixed 版本）。网络正常。
- PyPI / npm registry：`https://pypi.org/pypi/<pkg>/json`、`https://registry.npmjs.org/<pkg>/latest` 获取最新版本做过时评估。网络正常（python-docx、pypdf 等个别请求首次 SSL 中断，改用 curl 重试成功）。
- 使用情况核对：grep 确认 pypdf（document_normalize.py）、mermaid/dompurify/marked/katex（MarkdownRenderer.vue）的实际调用方式，判断漏洞是否影响当前用法。

**未执行**（环境缺失，改用 OSV 手工核对）：pip-audit 与 cargo-audit 未安装；仓库无 Python lock 文件，故 Python 侧以"约束下限 + 全局实际安装版本"双口径查 OSV。全程未修改任何依赖文件。

**口径说明**：Python 无 lock，实际部署版本可能高于下限；本报告对约束下限与已知实际版本分别标注命中情况。Rust 侧 tauri/wry/tao 的 OSV 公告极少，另以 GitHub Advisory 交叉核对了 tauri 的 8 条历史公告（全部在 2.11.1 之前修复）。
