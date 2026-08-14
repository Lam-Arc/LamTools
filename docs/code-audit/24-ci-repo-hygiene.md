# 24 CI 与仓库卫生 审计报告

- 审计时间：2026-08-13
- 审计范围：.github/workflows/ci.yml、release.yml、core/.github/workflows/ci.yml、全部 .gitignore（根级/core，website 与 core/desktop 无独立 .gitignore）、根级杂项脚本、e2e/ 配置与 spec、git 历史敏感信息
- 审计方式：全程只读（git log / git grep / git ls-files / grep / cat），未执行任何脚本、未运行 CI

## 1. 概况

仓库整体卫生状况良好，有以下突出亮点：

- **git 历史与当前树均未发现真实密钥**。全历史 diff 扫描（`git log --all -p` 匹配 api_key/secret/token/password/BEGIN PRIVATE KEY）仅命中代码变量名、测试 mock（`test-api-key-mock`）、占位符（`sk-xxxxx`、`sk-test-secret-key-abc123XYZ789-do-not-expose`、`sk-runtime-shared-secret`）等误报，无任何可用的真实 API key/私钥。
- 没有提交过 .env（仅 3 个 `.env.example`，均属正常模板）、没有 *.pem / id_rsa / *.pyd / *.exe / *.pyc / *.db 入库。
- 根级 .gitignore 覆盖完整：根目录截图（dev-verify-*、frame-*、hero*、shimmer-*、verify-*）、probe/verify 脚本（probe-api.mjs、verify-beam*.mjs）、临时脚本（check-port.ps1、kill-*.ps1、start-core.bat）、data/、dist/、build/、网站 /website/ 均已忽略，`git status` 干净（仅未跟踪的 docs/code-audit/）。
- 版本单一事实源工作良好：core/pyproject.toml、core/desktop/package.json、tauri.conf.json、Cargo.toml、lamtools_core/__init__.py 五处版本全部一致为 0.2.3，`scripts/bump-version.ps1` 一次更新 5 处。
- release.yml 的 backend 冒烟测试与代码一致：`create_app`（factory.py）无条件挂载 `/api/health`，`desktop_backend.py` → `create_default_core_agent_http_app()` 链路成立，`/api/health` 探测是真实有效的。
- ports.json（backend 5172 / frontend_dev 5173）与 core/src/lamtools_core/cli.py 默认端口 5172、core/ui/vite.config.ts 的 CORE_BACKEND_PORT=5172、core/desktop/package.json dev 端口 5173 全部一致。

## 2. 问题清单

- **[S2] core/.github/workflows/ci.yml 是必然失败的僵尸重复工作流**
  - 位置：`core/.github/workflows/ci.yml:18-33`（test job）、`:39-51`（build job）
  - 问题：该工作流与根级 ci.yml 重复（根级 backend job 已在 Windows 上跑同一份 pytest），且两个 job 都缺少 `working-directory: core` 或 `cd core`——`pip install -e ".[dev]"` 与 `python -m build` 均在仓库根执行，而根目录没有 pyproject.toml/setup.py/setup.cfg（构建元数据只在 core/），必然报 "Directory '.' is not installable" 失败。另：触发分支 `[main, develop]` 中的 develop 分支不存在（本地与远程均无）；文件为 CRLF 行尾。
  - 影响：每次 push 到 main 都会同时触发根 ci.yml（绿）与 core ci.yml（红），Actions 页面长期挂红叉、双倍消耗 runner 分钟；若有人配置 branch protection 以该工作流为必须检查，会直接阻塞合并。
  - 修复建议：删除 core/.github/workflows/ci.yml（根级 ci.yml 已覆盖 backend 测试）；或至少补 `defaults: {run: {working-directory: core}}`、删除 develop 触发、改为 LF 行尾。若想保留 Linux 平台覆盖，改为在根级 ci.yml 中加 Ubuntu 矩阵，而不是单独一份重复工作流。

- **[S2] Vite 构建产物 core/ui/dist-core-app/ 被反复提交入库（164 个文件，约 6.3MB）**
  - 位置：`core/ui/dist-core-app/`（164 个已跟踪文件，如 `core/ui/dist-core-app/assets/index-core-BewLOIO3.js` 1.4MB、KaTeX 字体等）；与 `.gitignore:82` 的 `core/ui/dist-core-app/` 忽略规则直接矛盾
  - 问题：该目录是 `vite build --config vite.config.core-app.ts` 的输出（`core/ui/vite.config.core-app.ts`），非源码；2026-07-29（a263fe6）首次入库后，每次前端改动都会更新这批产物（最近一次 2026-08-02 312ff56），说明提交者绕过 gitignore 强制 add。
  - 影响：每次 UI 改动产生约 6MB 的二进制 diff、污染代码评审、仓库持续膨胀；且产物可能与源码不同步（CI 中 release 流程实际会重新构建，入库产物是死数据）。.gitignore 规则形同虚设。
  - 修复建议：`git rm -r --cached core/ui/dist-core-app` 一次清理，后续禁止强推该目录；确认 desktop 打包不依赖入库产物（release.yml 中 `npm run build` 会现场构建，依赖关系应已满足）。

- **[S2] e2e/ 套件整体过期，指向已归档的 Writer 产品**
  - 位置：`e2e/playwright.config.ts:16`（baseURL `http://localhost:6174`）、`e2e/tests/writer-smoke.spec.ts:31-49`（断言 LamWriter 品牌、`.drawer-left`、`.floating-composer`）、`e2e/README.md:17-23`（指引 `E:\LamTools\members\writer\frontend`）
  - 问题：端口 6174、LamWriter/.drawer-left/.floating-composer 均为已归档产品 Writer（现位于 archive/members/）的专属元素；当前活跃前端是 core/ui（Vue 库 + core/desktop Tauri 壳，端口 5172/5173）。`members/writer` 目录已不存在，README 中的启动指引无法执行；且该套件未接入任何 CI 工作流。
  - 影响：README 声称是 "active LamTools frontend" 的冒烟测试，实际永远无法跑通，对新维护者是误导；spec 中 `expect(problems).toEqual([])` 等断言质量尚可，但测试对象已死。
  - 修复建议：要么改写为针对 core/desktop 或 core/ui 的冒烟测试并接入根级 ci.yml，要么整体删除 e2e/（连同 test-apps 测试脚手架）并归档；至少更新 README 标注"已归档、不可运行"。

- **[S3] scripts/start.bat 引用不存在的路径**
  - 位置：`scripts/start.bat:5`（`py -3.14 "members\writer\start.py"`）
  - 问题：根目录无 members/（已归档至 archive/members/），该 bat 一执行即报错。它是 3056322 遗留的旧 Writer 启动入口，与当前 core 架构无关。
  - 影响：误导使用者；与 scripts/ 下其他活跃维护脚本（dev.ps1/test.ps1）并存造成混乱。
  - 修复建议：删除，或在注释中标注废弃；活跃入口应统一走 `.\scripts\lamtools.cmd dev core`。

- **[S3] 遗留 NSIS 模板副本含开发者硬编码绝对路径**
  - 位置：`core/desktop/installer/installer.nsi:47,107`（`!define ADDITIONALPLUGINSPATH "C:\Users\Administrator\AppData\Local\tauri\NSIS\Plugins\x86-unicode\additional"` + `!addplugindir`）
  - 问题：这是 251 行的旧版模板；实际生效模板是 `core/desktop/src-tauri/installer.nsi`（999 行，tauri.conf.json:52 `"template": "installer.nsi"` 引用，用 `{{additional_plugins_path}}` 占位符，正确）。旧副本引用的本机用户目录路径在仓库中可见（泄露用户名 + 本地路径），且若被误用为模板会在任何其他机器上构建失败。
  - 影响：本地绝对路径入库（隐私/可移植性问题）；双份模板并存增加维护者误用风险。
  - 修复建议：删除 `core/desktop/installer/installer.nsi`，统一保留 src-tauri 模板。

- **[S3] core/ui/obs-profile.json 为 V8 CPU profile 调试产物**
  - 位置：`core/ui/obs-profile.json`（约 1MB，内容为 `{"nodes":[{"id":1,"callFrame":...}]}` 性能采样数据）
  - 问题：性能分析导出的临时文件被提交入库。
  - 影响：仓库噪音与无意义二进制 diff（每次重新 profiling 都会变动）。
  - 修复建议：`git rm --cached` 并在 .gitignore 增加 `core/ui/obs-profile*.json`。

- **[S4] 根级 ci.yml 的 `git diff --check` 在 CI 上是空操作**
  - 位置：`.github/workflows/ci.yml:21-22`、`:47-48`
  - 问题：`git diff --check` 比较工作区与索引；CI 全新 checkout 两者一致，永远返回 0，检查不到任何 whitespace 问题。想要的效果应是校验本次提交/PR 的 diff。
  - 影响：步骤形同虚设（无害但误导）。
  - 修复建议：改为 `git diff --check HEAD^ HEAD`（push 场景）或移除；或改用 `git diff-tree --check` 配合 fetch-depth。

- **[S4] CI 缺少常见加固项**
  - 位置：`.github/workflows/ci.yml`、`.github/workflows/release.yml`（全局）
  - 问题：无 `timeout-minutes`（job 级）、无 `concurrency` 组（连发 push/重复手动触发会并行重复构建）、无 pip 缓存（`actions/setup-python` 未开 `cache: pip`）；Python 侧无 lint/静态检查步骤（前端有 typecheck，后端只有 pytest）。
  - 影响：资源浪费与偶发竞态（release 重复 tag 触发时两个 job 同时构建、同时尝试发布）；坏代码在 lint 层面无防护。
  - 修复建议：为两个工作流补 `concurrency` + `timeout-minutes`；backend job 开 pip cache；可选加 ruff/mypy 快速检查。

- **[S4] .superpowers/ 有 8 个文件被跟踪，与 .gitignore 冲突**
  - 位置：`.gitignore:79`（`.superpowers/` 已忽略）vs `git ls-files '.superpowers/'`（8 个 sdd 报告）
  - 问题：忽略规则加入前已入库，规则对已跟踪文件不生效。
  - 影响：Agent 工作产物（报告 md）混入仓库历史，且继续被更新提交。
  - 修复建议：`git rm -r --cached .superpowers`（若确属本地 agent 工作状态）。

- **[S4] .worktrees/ 仅在本机 .git/info/exclude 中排除**
  - 位置：`.git/info/exclude`（`.worktrees/`）——该文件不随仓库分发
  - 问题：worktree 检出目录（内含 sage-agent-local 等完整检出，甚至含 LamWriter.exe）只在当前机器被排除；其他开发者克隆后若创建同名目录，未忽略的整棵树会出现在 `git status` 中，存在误提交风险。
  - 影响：潜在的大规模误提交。
  - 修复建议：把 `.worktrees/` 加入根 .gitignore。

- **[S4] lamtools_cli.py 中关于 /api/health 的注释已过期**
  - 位置：`scripts/lamtools_cli.py:77-80`
  - 问题：注释称 "Core's backend health is served under the app-server path, not a plain /api/health endpoint"；实际 `core/src/lamtools_core/app/factory.py:114-115` 无条件挂载 `/api/health`（health_payload 为空时返回 {"status":"ok"}），release.yml 冒烟测试正是依赖该端点。
  - 影响：注释误导后续维护者（例如据此移除健康探测）。
  - 修复建议：更新注释，说明 /api/health 始终存在（create_app 默认行为）。

- **[S4] README.md 徽章版本号过期**
  - 位置：`README.md:6`（`version-0.2.2-green.svg`）
  - 问题：当前版本 0.2.3（pyproject/Cargo/tauri/__init__ 五处一致），README 徽章仍为 0.2.2；README 其余声明（pip install -e "core[desktop]"、scripts\dev.ps1 core all、127.0.0.1:5173、仓库结构、archive/members 归档说明）与仓库实际一致。
  - 影响：徽章展示版本与 Release 不符。
  - 修复建议：更新徽章版本（可与 bump-version.ps1 联动或手动）。

- **[S4] release.yml 缺少 tag 与版本号一致性校验**
  - 位置：`.github/workflows/release.yml:8-11`（`push tags 'v*'` 直接构建）
  - 问题：tag `v0.2.4` 与 `__version__=0.2.3` 不一致时仍会构建发布，桌面端 update.check 用 `lamtools_core.__version__` 比对 Releases，会出现"已是最新"误判。bump-version.ps1 已保证五处一致，但 tag 依赖人工。
  - 影响：版本漂移风险（与 14 区版本管理主题衔接，此处仅指出 CI 侧缺护栏）。
  - 修复建议：在 build-windows job 加一步：解析 tag 名并与 `core/src/lamtools_core/__init__.py` 的 `__version__` 比对，不一致即失败。

- **[S4] 文档类文件含本机绝对路径 C:\Users\Administrator**
  - 位置：`core/desktop/installer/installer.nsi:47`（见 S3 条目）、`docs/archive/audit-reports/…`、`.superpowers/sdd/…` 等若干 md
  - 问题：历史文档中残留本机用户名与绝对路径（主要位于 docs/archive 历史文档，影响有限）。
  - 影响：轻微隐私暴露与文档不可移植。
  - 修复建议：仅对活跃文档清理；archive 文档可保留或批量替换为相对路径说明。

## 3. 该区 Top 3 问题

1. **core/.github/workflows/ci.yml 僵尸工作流**——每次 push 必然失败（缺少 core 目录上下文），长期红叉 + 与根级 ci.yml 重复跑同一批后端测试，双倍消耗且制造噪音。
2. **core/ui/dist-core-app/ 构建产物反复入库**——164 个文件约 6.3MB，与 .gitignore 规则冲突，仓库膨胀与评审噪音的主要来源。
3. **e2e/ 套件整体指向已归档 Writer 产品**——README/配置/spec 全部过期（端口 6174、LamWriter 元素、members/writer 路径已不存在），且未接入 CI，属于"死测试"。

## 4. 亮点

- 全历史无真实密钥/凭证/私钥入库（仅有占位符与测试 mock）；无 .env、*.pem、*.exe、*.pyc、*.db 入库；`git status` 干净，根级杂项全部被 .gitignore 覆盖且未跟踪。
- 版本五处一致（0.2.3），bump-version.ps1 单点更新 + README 结构/命令与仓库实际吻合（除徽章版本号）。
- release.yml 质量高：单一 spec（core/lamtools-core-backend.spec，与本地 scripts/package.ps1 共用）、真启动冒烟（/api/health 轮询，与 factory.py 实际行为一致）、tag 触发才发 Release、手动触发只留 artifact、`fail_on_unmatched_files` 防静默漏包。
- ports.json 与代码端口（5172/5173）完全一致；scripts/lamtools_cli.py（doctor/dev/test/open）与 scripts/*.ps1 引用关系完整，目标文件全部存在。
- 根级 ci.yml 前端 job 覆盖 npm ci + typecheck + vitest contract + build，后端覆盖 editable 安装 + 全量 pytest，`setup-node` 带 npm cache 且 cache-dependency-path 正确。

## 5. 审计范围与方法

- 范围：.github/workflows/ci.yml、.github/workflows/release.yml、core/.github/workflows/ci.yml（对比差异）；根级/.core/website/core/desktop 的 .gitignore 与 .gitattributes（无 .gitattributes，未要求必建）；根级杂项（scripts/ 全家、lamtools.cmd/core.cmd/start-core.bat、scripts/start.bat、ports.json、probe-api.mjs/verify-beam*.mjs 的忽略状态）；e2e/（playwright.config.ts、tests/writer-smoke.spec.ts，未评审 real-task-runs 产物内容）；README.md/PRODUCT.md/MAINTENANCE.md 构建命令与结构抽查；git 历史敏感信息扫描。
- 方法（全部只读）：`git log --all -p` 全文扫描密钥模式（api_key/secret/token/password/BEGIN PRIVATE KEY 等）并人工剔除占位符/测试值；`git log --all --name-only` 检索被删敏感文件名（.env/.pem/id_rsa/.key）；`git ls-files` 审计跟踪文件（png/mjs/ps1/db/log/env/大文件）；`git check-ignore` 验证忽略规则覆盖；`git log --diff-filter=A` 定位产物首次入库提交；代码交叉核对（端口、health 端点、版本、spec 路径）。
- 未执行：任何脚本（.ps1/.mjs/bat）、CI、写文件命令（仅写入本报告）。
- 边界：e2e/real-task-runs 与 e2e/test-apps 产物内容不在本次审计结论内（按任务约定跳过），仅就其"是否应入库"给出 S2 条目的上下文说明。
