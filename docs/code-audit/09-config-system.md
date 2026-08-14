# 09 配置体系 审计报告

- 审计日期：2026-08-13
- 审计员：ZCode 全区审计第 09 区
- 审计方式：全程只读（grep/find/git log/python -c 只读验证），未运行测试、未启动服务、未修改任何代码或配置

## 1. 概况

配置体系已从共享 SQLite 表（`llm_providers`/`llm_models`/`app_settings`）整体迁移为 jsonc 文件体系，统一收敛到 `.lam/core/config/`（dev 下实际为 `core/.lam/core/config/`，打包后为 exe 旁 `.lam/core/config/`，`LAMTOOLS_CORE_CONFIG_ROOT` / `LAMTOOLS_HOME` 可覆盖）。总体设计质量较高：播种幂等、作用域合并（built-in → legacy → unified → project）语义清晰、损坏文件大多优雅回退、密钥掩码回写保护到位、AGENTS.md 声明的播种清单与实现一致。

主要风险集中在三处：**模型/供应商 id 未净化直接拼文件名的路径穿越**、**ModelStore 字段类型强转异常可被单个损坏文件引爆**、**migrate_projects 对受保护路径迁移后 work_root 指向不存在的目录**。另有 BOM/编码处理不一致、注释剥离三套实现、写入非原子等一批中低危问题。

- 源文件：`core/src/lamtools_core/config/` 12 个文件（约 2.2k 行）+ 资源 `core/config/resources/` 5 个文件 + `core/config/command/`、`core/config/llm_adapters/`
- 消费者核查：`plugins/hook_config.py`（hooks.json）、`mcp/config.py`（mcp.json）、`tool/loadtools.py` + `tool/approval.py` + `app/live_operations.py`（loadtools/access_tools）、`app/project_context.py`（load_context.jsonc/memory.md/AGENTS.md）、`app/base_agent.py`（subagent guide/settings）
- 播种调用点：`cli.py:1189-1191`（serve）、`cli.py:1216-1218`（setup）、`desktop_backend.py:93-95`；测试 `core/tests/test_config_defaults.py` 验证了幂等性

## 2. 问题清单

### S2（中等）

- **[S2] 模型/供应商 id 未净化即拼接为文件名，存在路径穿越与任意 .jsonc 覆盖**
  - 位置：`core/src/lamtools_core/config/model_store.py:258-261`（`write_path`）、`provider_store.py:235-238`（`write_path`）；入口 `operations.py:92`（`provider_create` 的 id/preset_id 直取 payload）、`operations.py:328`（`model_id` 直取 payload）
  - 问题：`write_path` 用 `f"{model_id}{MODEL_FILENAME_SUFFIX}"` 直接拼路径，`model_id`/`provider_id` 来自 RPC payload，无任何净化。已验证 `config/models/../../../../x.jsonc` 可解析到 `E:\LamTools\core\x.jsonc`（配置目录之外）；`path.parent.mkdir` 还会创建任意中间目录。该 RPC 经 `http_agent_app.py:336` 的 `_register_missing_operations` 暴露给前端 WebSocket/HTTP 通道（默认绑定 127.0.0.1）。`slugify` 只用于未显式提供 id 时的兜底，显式 id 完全绕过。
  - 影响：本地攻击者（或前端被注入的请求）可通过 `config.model.create` / `config.provider.create` 覆盖/创建任意 `.jsonc` 文件（含配置目录外、项目文件），`mkdir` 可创建任意目录；与"用户配置绝不被覆盖"的播种承诺相悖。
  - 修复建议：写入前对 id 做白名单校验（拒绝 `.`、`..`、`/`、`\`、路径分隔符，或统一走 `slugify` 并校验 `stem == id`）；在 `_model_config_from_payload` / `provider_create` 入口集中净化。

- **[S2] ModelStore._parse 字段类型强转异常未捕获，单个损坏模型文件拖垮整个模型体系**
  - 位置：`core/src/lamtools_core/config/model_store.py:182-186`（`int(data.get("context_window") or 0)`、`float(...)`、`int(... thinking_budget ...)`），`_load_map`（235-253 行）对 `_parse` 无 try/except
  - 问题：`load_jsonc` 的解析异常被捕获，但字段强转不在保护内。已验证 `int("128k")` 抛 ValueError；用户手写 `"context_window": "128k"`（或 `"max_output_tokens": "16k"`、`"temperature": "high"`）即触发。`OperationCatalog.execute`（`app/operation_catalog.py:52-68`）与 `http_agent_app.py:259` 的 `_config_models_list` 均无兜底 → RPC 500 或异常上抛；`resolve_default_multimodal_model`（`subagent_prompt.py:146`）同样会炸。对比 `ProviderStore._parse` 也只捕获 `load_jsonc` 异常——同样问题存在于 provider 侧。
  - 影响：jsonc 文件是文档化的用户可编辑配置，一个文件一个字段写错 → 全部模型列表、默认模型解析、多模态委派解析整体失败，且无任何"跳过该文件"的降级。
  - 修复建议：`_parse` 内将字段强转包进 try/except，非法值回退默认并记 warning（对齐 `retry_store._coerce` 的容错风格）；或 `_load_map` 对单个文件解析失败跳过并告警。

- **[S2] migrate_projects 对受保护路径"跳过移动但更新 DB"，迁移后项目 work_root 指向不存在的目录**
  - 位置：`core/src/lamtools_core/config/migrate_projects.py:109-118`（protected/temp 分支生成 `new_work_root = lam_projects/<name>` 但 action="skipped"）+ `apply_project_migration` 214-222 行（skipped 也执行 `project.work_root = action.new_work_root` + `_rewrite_db_references`）
  - 问题：`_is_protected_path`（repo 根或 core/ 目录）命中时文件原地保留，但 DB 行 work_root 被改为 `lam_projects/<name>`——该目录并不存在（文件未移动）。项目行、会话快照、arrange 作业的 work_root 全部指向空目录。
  - 影响：以仓库根为 work_root 的项目（开发期即为 LamTools 自身）迁移后，应用内对该项目的所有文件操作指向不存在的目录，项目文件"失联"；且迁移是一次性操作，事后难以察觉。
  - 修复建议：受保护路径分支应保持旧 work_root 不变（action="unchanged"），或明确创建空目标目录并提示"项目文件未移动、DB 已改指向"的风险；至少在报告中把该分支的 `new_work_root` 语义写清楚并加日志告警。

### S3（轻微）

- **[S3] UTF-8 BOM 处理不一致：jsonc 读取全部静默失效，配置"消失"**
  - 位置：`core/src/lamtools_core/llm/profiles.py:62`（`load_jsonc` 用 `read_text(encoding="utf-8")`）、`tool/loadtools.py:49`、`tool/approval.py:35`、`app/project_context.py:33`；对比 `mcp/config.py:31` 与 `plugins/hook_config.py:87` 已用 `utf-8-sig`（BOM 容忍）
  - 问题：已用 python 验证 `json.loads('\ufeff{...}')` 抛 "Unexpected UTF-8 BOM"。带 BOM 的 providers/models/settings/loadtools/access_tools/load_context 文件 → 解析异常 → 各 store 静默回退（provider/model 直接消失、settings 返回 {}、loadtools 回退内置默认）。中文 Windows 的记事本旧版本默认"UTF-8 带 BOM"保存，属高概率场景。
  - 影响：用户手改带 BOM 的配置文件后全部配置静默失效且无任何提示，排查成本高。
  - 修复建议：统一改用 `encoding="utf-8-sig"`（或 `utf-8` + 显式 strip BOM），与 hooks/mcp 加载器对齐。

- **[S3] 注释剥离三套实现，其中两套不尊重字符串上下文，字符串内 `//` 被截断**
  - 位置：`tool/loadtools.py:75-79`（`_strip_jsonc_comments` 正则）、`app/project_context.py:194-199`（`_parse_jsonc` 正则）；对比 `llm/profiles.py:19-58`（`strip_jsonc` 正确处理字符串/转义）
  - 问题：两处正则 `r"/\*.*?\*/|//[^\n]*"` 会剥离字符串内的 `//`。已验证 `"https://example.com/a"` 被截成 `"https:`（json 解析随即失败或值被截断）。三套剥离器行为各异（profiles 版支持单引号串与转义，其余不支持），且正则版均不处理尾逗号。
  - 影响：load_context.jsonc / loadtools.jsonc 中出现 URL 或含 `//` 的字符串值时配置被静默破坏；行为不统一增加维护成本。
  - 修复建议：统一复用 `profiles.strip_jsonc`（或抽取到公共模块），删除各文件里的私有正则实现。

- **[S3] 配置文件写入非原子 + 损坏文件静默回退 {} 后整体覆盖，存在设置丢失链**
  - 位置：写入 `settings_store.py:84,107`、`provider_store.py:243`、`model_store.py:266`、`imagegen_store.py:43`、`subagent_prompt.py:98,172`（全部 `path.write_text` 直写，docstring 却声称 "atomic-ish"）；读侧 `settings_store.py:47-53`（`_read_map` 损坏返回 `{}`）
  - 问题：无临时文件+rename 的原子写入；进程崩溃/断电留下截断文件 → `_read_map` 返回 `{}` → 下一次 `set_setting` 用空 map 重写整个 settings.jsonc → 此前所有命名空间设置被静默抹除。
  - 影响：settings.jsonc 是多个前端命名空间共享的单一文件，任何一次非原子写中断即可造成全部设置丢失且无备份。
  - 修复建议：写盘统一走 `tmp 文件 + os.replace` 的原子写工具；损坏文件读取时应保留原文件（如 .bak）而非直接以 {} 覆盖。

- **[S3] subagent guide/settings 读取不处理 UnicodeDecodeError，GBK 编码文件可致 agent 组装崩溃**
  - 位置：`core/src/lamtools_core/config/subagent_prompt.py:78-84`（`load_subagent_guide` 仅捕 OSError）、`120-128` 与 `164-170`（settings 仅捕 OSError/JSONDecodeError）；调用点 `app/base_agent.py:196`（agent 组装期）
  - 问题：`path.read_text(encoding="utf-8")` 遇 GBK/ANSI 内容抛 UnicodeDecodeError（ValueError 子类，不属于已捕获类型）→ 传播到 agent 初始化。对比 `agents_md.py:52-53` 用 `errors="replace"` 优雅降级，`project_context.py:33-35` 也捕获了 UnicodeDecodeError——本模块是三处中唯一漏网的。
  - 影响：中文 Windows 用户用非 UTF-8 编码保存 guide.md/settings.json 即触发崩溃或 RPC 500。
  - 修复建议：读取统一 `errors="replace"`，与 agents_md.py 保持一致。

- **[S3] 项目作用域配置被更新时默认写 global，被项目文件 shadow 造成"静默无效更新"**
  - 位置：`core/src/lamtools_core/config/operations.py:120-131`（`provider_update` 默认 scope=global）、`178-202`（`model_update` 默认 scope=global）
  - 问题：当 provider/model 源文件位于项目作用域（`{work_root}/.lam/config/...`），RPC 未传 scope 时更新写入 global 副本；而读取合并顺序是 project > global，项目文件继续生效 → 更新"成功"但实际配置未变；响应 `get_sync` 读回的仍是 shadow 的旧值，前端无任何错误提示。
  - 影响：用户在项目级供应商/模型上执行编辑操作，界面显示成功但行为不变，误导排查。
  - 修复建议：更新默认 scope 取源文件所在作用域（`model.source_path`/`provider.source_path` 判断），或当源作用域与写入作用域不一致时返回明确提示。

- **[S3] hooks.json 结构错误以 ValueError 直抛到启动流程，与"绝不让应用崩溃"注释相悖**
  - 位置：`core/src/lamtools_core/plugins/hook_config.py:92-145`（`_load_file` 对 `hooks` 非对象、groups 非列表、handler type 不支持等 raise ValueError）；调用点 `app/base_agent.py:904`（`hook_registry.load()` 无 try/except）
  - 问题：JSON 语法错误被优雅跳过（87-91 行），但结构错误（如 `"hooks": []`、`{"type": "unknown"}`）直接抛 ValueError 穿透 agent 组装。播种的 `hooks.json` 是用户必读可编辑文件，手改时极易出现此类笔误。
  - 影响：一个 hooks.json 结构笔误导致 agent 启动失败/插件装配失败；同文件内其余合法 hook 也全部丢失。
  - 修复建议：结构校验失败改为记录 warning 并跳过该文件（与 87-91 行语义一致），或至少把 ValueError 包装成带路径的可诊断错误。

- **[S3] migrate_projects 文件系统移动与 DB 更新非原子，中途失败留下半迁移状态**
  - 位置：`core/src/lamtools_core/config/migrate_projects.py:214-222`
  - 问题：`shutil.move` 先执行，随后才更新 DB 行并 `commit`；若 `_rewrite_db_references`/flush 失败或进程中断，文件夹已移动而 DB 仍指向旧路径；`_is_temp_residue` 只保护系统 temp 目录，其他任意系统目录（如 C:\Windows 下残留 work_root）会被整目录移动。
  - 影响：迁移中断后项目记录与磁盘状态不一致，无回滚机制；极端情况下整目录被移动。
  - 修复建议：每行先写 DB 再移动或移动失败时反向移动回滚；对非项目目录形态的 work_root 增加白名单校验。

### S4（建议）

- **[S4] subagent guide.md 注入 system prompt 无大小上限**
  - 位置：`core/src/lamtools_core/config/subagent_prompt.py:70-84`（整文件读入）+ `app/base_agent.py:292`（直接拼入 system prompt）；对比 `project_context.py:75-78` 有 20000 字符截断
  - 影响：误写入大文件/二进制内容导致 prompt 膨胀、token 浪费，无法优雅降级。
  - 建议：沿用 `ProjectContextLoader._read` 的截断策略（截断 + 提示）。

- **[S4] provider_create 与 _clear_other_defaults 的默认标记语义不完整**
  - 位置：`core/src/lamtools_core/config/operations.py:85-118`（provider_create 不清理旧 is_default，对比 model_create 173-175 行有 `_clear_other_defaults`）、`369-372`（`_clear_other_defaults` 一律写 global scope，源在 project scope 时被 shadow，两个默认并存）
  - 影响：默认供应商/默认模型可同时存在多个，`default_sync`/`default_model_id_sync` 按文件顺序取首个，行为不确定。
  - 建议：provider 侧补对称清理；按源作用域写回。

- **[S4] imagegen api_key 明文经 settings.get 返回前端**
  - 位置：`core/src/lamtools_core/config/operations.py:224-228`（`settings_get` 直接返回 `load_imagegen_config()` 全文，含 api_key）；对比 providers 响应做了 `mask_api_key` + `has_api_key`（49-53 行）
  - 影响：同一 RPC 层面对密钥处理策略不一致；本地应用风险有限，但若前端日志/快照外泄则密钥随行。
  - 建议：`settings.get` 对 `core.imagegen` 至少补 `has_api_key` 字段，或对齐 providers 的掩码约定。

- **[S4] 播种清单文档与实现存在小偏差**
  - 位置：`core/src/lamtools_core/config/defaults.py:9-11`（docstring 声称清单未列 mcp.json/README.md/model_retry.jsonc/subagent/），`root.py:52-54`（docstring 清单同样不全）；AGENTS.md:46-49 的清单与实现一致
  - 影响：仅文档偏差，无功能影响；维护期易被误读为播种缺失。
  - 建议：docstring 改为引用 `ensure_default_config_files` 实现为唯一事实源。

- **[S4] 杂项小问题**
  - `default_agent.py:1884-1893`：`load_tools is default_load_tools()` 用身份比较判断"未加载配置"，依赖同一对象引用，重构易碎，建议改 `load_tools == default_load_tools()` 或显式标记。
  - `model_store.py:192` / `provider_store.py:172`：`bool(data.get("is_default") or False)` 使字符串 `"false"` 被当真值，建议严格 `isinstance(x, bool)`。
  - `operations.py:144-145,153-154`：`provider_delete`/`model_delete` 直接写私有缓存字段 `_cached_*`，建议提供 store 级失效方法。
  - `defaults.py:148-152`：播种只 mkdir `models/` 不 mkdir `providers/`（写时懒创建），不对称但无功能影响。

## 3. 该区 Top 3 问题

1. **模型/供应商 id 路径穿越（S2）**：RPC 可写任意 `.jsonc` 文件/创建任意目录，直接击穿"用户配置绝不被覆盖"的核心承诺，修复成本低（入口净化）。
2. **ModelStore 字段强转异常单点引爆（S2）**：用户可编辑 jsonc 的设计下，一个字段笔误瘫痪全部模型解析，且无降级提示；容错风格与 retry_store 不一致。
3. **migrate_projects 受保护路径迁移后 work_root 悬空（S2）**：仓库根项目迁移后文件"失联"，属一次性破坏性迁移，事后难恢复。

## 4. 亮点

- **播种幂等性扎实**：`ensure_default_config_files` 全部走"不存在才写"，`_copy_if_missing`/`_write_if_missing` 双守卫 + `test_config_defaults.py` 覆盖"用户改动在二次运行后保留"；历史 NSIS 打包 `.lam` 覆盖用户配置的教训已固化为 AGENTS.md 规则（"新增默认文件一律放 core/config/resources/ 并注册到播种清单"）。
- **密钥掩码回写保护到位**：`_provider_update_fields`（operations.py:353-355）正确忽略掩码/空 api_key 回写；`MASKED_API_KEY` 哨兵贯穿响应层。
- **损坏文件优雅回退覆盖面广**：mcp.json（`mcp/config.py:32-35`）、hooks.json 语法错误、retry_store 全字段 `_coerce` 校验回退、settings/loadtools/access_tools 的空值回退，均不导致崩溃。
- **作用域合并语义清晰**：built-in → legacy → unified → project 的候选目录有序去重（provider_store.py:101-138、model_store.py:106-156），mtime+size 签名缓存设计正确（路径含在签名内，换 work_root 不串缓存）。
- **AGENTS.md 播种声明与实现逐项一致**（loadtools/access_tools/hooks/mcp/README 从 resources 复制；AGENTS.md/load_context/memory/model_retry/subagent 代码内默认），无夸大声明。
- `retry_store._coerce` 是全区容错解析的范本：逐字段 try/except + 默认值回退 + 类型白名单（`jitter` 仅接受 bool）。

## 5. 审计范围与方法

**范围**：
- 源码：`core/src/lamtools_core/config/` 全部 12 文件（defaults/root/provider_store/model_store/settings_store/agents_md/imagegen_store/retry_store/subagent_prompt/operations/migrate_projects/`__init__`）
- 资源：`core/config/resources/`（access_tools.jsonc/hooks.json/loadtools.jsonc/mcp.json/README.md）、`core/config/command/`、`core/config/llm_adapters/`
- 相关消费方（只读交叉核查）：`llm/profiles.py`（load_jsonc 核心）、`plugins/hook_config.py`、`mcp/config.py`、`tool/loadtools.py`、`tool/approval.py`、`app/project_context.py`、`app/base_agent.py`、`app/http_agent_app.py`、`cli.py`、`desktop_backend.py`、`core/lamtools-core-backend.spec`
- 运行时参考（只读）：`core/.lam/core/config/`（dev 运行目录，含真实 providers/models/settings）
- 历史：`git log` 相关提交（861d00d .lam unbundling、a58c13f jsonc stores 等）

**方法**：
- 全量阅读 config 模块源码，追踪每条配置的"播种 → 解析 → 读写 → 消费"链路
- 用 `python -c` 只读验证关键行为：BOM 破坏 json.loads、`int("128k")` 抛 ValueError、正则剥离截断 URL、`slugify('../evil')` 净化结果、路径穿越解析目标（`Path(.../models/../../../../x.jsonc).resolve()`）
- 对比三套注释剥离器、两套 BOM 策略、mask 策略在 providers 与 imagegen 的差异
- 对照 AGENTS.md/README.md 的播种声明与实际实现
- 未运行 pytest、未启动任何服务、未写除本报告外的任何文件

**统计**：S2 × 3，S3 × 7，S4 × 5，共 15 条。
