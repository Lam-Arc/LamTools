# 脚本、根入口与成员脚手架

## 一句话结论

当前入口主线已经成形：根 `*.cmd` 做薄转发，`lamtools_cli.py` 管仓库维护，`member_cli.py` 管 Writer/Artist 产品 CLI。主要债务是注册表分散、旧启动入口并行、脚手架生成后仍要手工接入、模板和真实成员结构已经漂移。

## 路径覆盖

- `scripts`
- `writer.cmd`、`artist.cmd`、`lamtools.cmd`、`start.bat`
- `core/templates/member`
- `core/docs/new-member-core-onboarding.md`
- 必要核对：`README.md`、`AGENTS.md`、`package.json`
- `docs/architecture-audit/2026-07-08-structure-organization-plan.md`

## 主要职责和入口

- 根 `writer.cmd` / `artist.cmd` / `lamtools.cmd`：只做 UTF-8 codepage 设置和转发到 `scripts\*.cmd`，职责可靠、够薄。
- `scripts\writer.cmd` / `scripts\artist.cmd`：成员 CLI shim，调用 `scripts\member_cli.py`，但 Python 选择顺序是 `python3 -> python -> py -3`，和 `lamtools.cmd` 不一致。
- `scripts\lamtools.cmd`：仓库维护 CLI shim，优先 `py -3.14`，并设置 `PYTHONUTF8` / `PYTHONIOENCODING`。
- `scripts\lamtools_cli.py`：仓库级命令门面，已覆盖 `dev/build/test/open/doctor/members/scaffold`；但 dev/build/test/open/doctor 目标仍硬编码 `core/writer/artist`。
- `scripts\member_cli.py`：产品级命令统一入口，Writer 走 `writer_cli`，Artist 走 `app.cli`，并提供 `health/session/run/resume/image` 等转发。
- `scripts\dev.ps1`：开发启动入口，用 `Start-Process` 启前后端；适合人工开发，但不是可等待、可采集退出码的自动化入口。
- `scripts\build.ps1`：只构建 `core/ui`、Writer 前端、Artist 前端。
- `scripts\test.ps1`：只跑 `core`、Writer 后端、Artist 后端 pytest；未覆盖前端测试、E2E、桌面打包验证。
- `scripts\scaffold-member.ps1`：从 `core/templates/member` 生成新成员、分配端口、写 UTF-8 no BOM 文件、生成根 cmd shim；但生成后仍提示手工改 `dev/build/test`。

## 可靠

- 根 shim 足够薄：`writer.cmd`、`artist.cmd`、`lamtools.cmd` 都只转发。
- `lamtools_cli.py` 作为仓库维护总入口方向正确，避免用户直接记多个脚本。
- `member_cli.py` 把 Writer/Artist 的产品 CLI 收到同一个入口，符合“成员 CLI 统一”的方向。
- `ports.json` 作为端口事实源被 `dev`、`open`、`doctor`、`members list` 复用，优于散落常量。
- 脚手架写文件使用 UTF-8 no BOM，且模板是最小 Core 接入骨架。

## 存疑

- `dev/build/test` 仍是 PowerShell 内硬编码目标，`lamtools_cli.py` 又有一份 argparse choices，新增成员至少要改两层。
- `members list` 扫描真实目录，现场输出包含 `members\imager`，但它无端口、无 CLI、无 dev/build/test 注册；“目录存在”和“成员已注册”语义混在一起。
- `build.ps1` 名称像全量构建，但实际只构建前端；对桌面、后端可发布性没有覆盖。
- `test.ps1 all` 名称像全量测试，但实际不含前端测试、E2E、打包 smoke。
- `dev.ps1` 用 `Start-Process` 后立即返回，适合打开服务，不适合 CI 或需要确认服务已健康的流程。
- 模板 `enable_core_routes=True`，而 Writer/Artist 真实成员都关闭自动 Core 路由并手动挂 `/api/core` 适配层；新成员会按旧模式起步。
- Artist CLI 更像直接调用产品内部服务，和 GUI 不是同一 HTTP/运行协议；Writer 更接近同接口。

## 债务

- `start.bat` 直接走 `members\writer\start.py`，绕过 `lamtools dev` 和 `member_cli`，是并行旧入口。
- `lamtools doctor` 仍检查旧 `AppData\LamWriter\lamwriter.db`，但当前 Writer 默认数据目录已经是 `members/writer/data`，这是明确漂移。
- `scripts\writer.cmd` / `artist.cmd` 与脚手架生成 shim 的 Python 策略不同：现有 shim 允许 `python3/python/py -3`，新 shim 固定 `py -3.14`。
- PowerShell 脚本没有统一设置 `[Console]::InputEncoding`、`[Console]::OutputEncoding`、`$OutputEncoding`；仅靠文件 BOM 或 cmd 的 `chcp 65001` 不够稳。
- 成员注册信息分散在 `ports.json`、三个 ps1、`lamtools_cli.py` choices、根 shim、文档中，后续成员必然漏改。

## 重构/优化建议

### P0

- 删除或降级 `start.bat`：保留时只转发到 `lamtools dev writer all --open`，不要继续维护 Writer 专用启动链。
- 修正 `lamtools doctor` 的 Writer 数据库检查：以 `LAMWRITER_DATA_DIR` / `members/writer/data` 为主，旧 AppData 只作为迁移来源提示。
- 明确处理 `members/imager`：确认是空残留就从成员清单过滤或删除；若是占位成员，就补注册。

### P1

- 建一个最小成员注册表，至少统一 `id/path/backend_port/frontend_port/cli/build/test/dev`；`lamtools_cli.py` 和 ps1 都读它，减少硬编码目标列表。
- 让 `scaffold-member` 自动更新注册表，生成后不再提示手工改 `dev/build/test`。
- 统一 Python shim 策略：根成员 shim、`scripts\writer.cmd`、脚手架生成 shim 使用同一套选择逻辑。
- 在 PowerShell 入口顶部显式设置 UTF-8 输入/输出编码，尤其是 `dev.ps1`、`build.ps1`、`test.ps1`、`scaffold-member.ps1`。

### P2

- 把 `build` 拆清楚：`build frontend`、`build desktop`、`build all`，避免“all 但不全”。
- 把 `test` 拆清楚：`test backend`、`test frontend`、`test e2e`、`test all`，默认保持轻量，显式全量才跑重测试。
- 更新模板：按当前 Writer/Artist 主线生成“产品适配 `/api/core`”骨架，或在文档里明确自动 Core 路由和产品适配路由的选择条件。

## 不建议现在做

- 不建议新增复杂插件式命令框架；当前问题是注册源分散，先合并事实源即可。
- 不建议把 Writer/Artist CLI 强行抽成完全一致的命令集；先统一入口和协议，再处理产品差异。
- 不建议现在把 ps1 全部改成 Python；PowerShell 作为 Windows 薄入口仍可保留。
- 不建议把脚手架做成“复制真实 Writer/Artist 结构”；模板应保持最小，但要对齐当前主线接入方式。

## 需要主线程核对的证据

- `.\lamtools.cmd members list --json` 当前列出 `artist`、`imager`、`writer`；其中 `imager` 无 ports、无 cli。
- `scripts/lamtools_cli.py` 仍按旧 AppData Writer DB 做 doctor 检查；`members/writer/backend/app/config.py` 显示当前默认数据目录在项目内。
- `scripts/scaffold-member.ps1` 明确要求生成后手工更新 `dev.ps1/build.ps1/test.ps1`。
- `core/templates/member/backend/app/main.py` 使用自动 Core 路由；Writer/Artist 真实入口关闭自动路由并挂产品适配。
- `start.bat` 仍直启 `members\writer\start.py`，没有进入统一入口。
