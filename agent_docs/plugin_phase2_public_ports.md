# 第二阶段公开后端接口

user:“给我把 2 阶段做完，前端除外”+(按固定服务范围补齐真实可调用接口；差异交给迁移agent，不把空壳或缺少提供方冒充功能)。

这些是受管 Python 插件接口，不支持直接运行 Cordis/TypeScript。均在 `start/on_load` 后通过 `context` 取得，旧启动代停止后拒绝新调用。原生行为验收分别见本文列出的测试。前端没有修改。

| 入口 | 参数和结果 | 生命周期及差异 |
| --- | --- | --- |
| `context.attachments.create(session_id, filename=..., content=bytes, mime_type=None)` | ≤50 MiB，返回真实附件索引和保存路径 | 原内容寻址存储和SQLite索引；写入完成后传播取消，取消可能已保存，无重复请求去重 |
| `attachments.reference(session_id, path)` | 原项目内现有文件，≤50 MiB，不复制 | 校验路径后复用原引用登记；外部竞争修改仍存在，不是沙箱 |
| `attachments.list(session_id, limit=100)` | 1–1000，返回 `items/truncated` | 原仓库查询；返回数量有界，但已有仓库内部列表查询仍可能扫描全部记录 |
| `attachments.get/preview(session_id, attachment_id)` | 校验可见会话、原项目和附件会话归属 | 不开放系统应用启动；不是DSH图片解码准入、流式文件、opaque ref或模型投影协议 |
| `context.session_title.get/set` | `get(id)`返回标题及修订；`set(id,title,expected_revision=...,only_if_default=False)` | 原存储CAS和原默认标题判定；并发不覆盖，写入后取消仍收尾。不替换自动标题生成器，不增加前端通知协议 |
| `context.session_projections.get/events` | 最新摘要；事件页沿用原 `after_seq/limit/max_bytes` | 摘要不含元数据；标题修订与运行事件序号分别观察，跨两次读取不保证同一时点。直接读取现有权威，没有第二份缓存 |
| `context.message_feedback.list/put/delete` | `put(session_id,message_id,rating,if_version,note='',category='')`，rating为positive/negative；首次版本None，删除后保留版本墓碑 | 原会话元数据持久保存；插件之间分开。每插件/会话≤200消息，正文4000字符、分类100字符，所有反馈≤1 MiB。删除须当前版本；不是DSH反馈事件或公开共享评分 |
| `context.session_feedback.record/list` | `record(id,text='',category='',request_id=...)`，重复请求返回原提交 | 原会话元数据，每插件/会话≤100条；支持冷会话，DSH只接收活动Session。无外部提交或遥测隐式上传 |
| `context.browser_use/computer_use` | `provider_name`；`register(name,cleanup=None)`返回异步撤回函数 | 对应上游独占名称槽，**不包含浏览器或桌面操作**。清理期间保留名称，失败保留供重试，旧撤回不能影响新槽；实际工具由提供方自己登记 |
| `context.lsp.register_provider(id, extension_to_language, query)` | 原子预留ID与全部小写扩展名；返回撤回函数 | 复用原服务注册/发布/租约，启动失败和停用撤回。未安装语言服务器提供方时明确 unavailable，不伪造语义位置 |
| `context.lsp.query(operation,file_path,line=...,character=...,timeout=30)` | goToDefinition/findReferences/goToImplementation/hover；0基UTF-16，≤120秒；规范化JSON≤1 MiB、导航≤1000条 | 原项目内现有文件，按扩展名选提供方；取消进入提供方协程并等待它退出，提供方须配合取消。结果URI只是数据，不授予读文件权限 |
| `context.mcp_resources.servers/open` | 配置中存在且未禁用/封锁的名称；`async with open(name) as connection` | 原MCP配置/路径展开/传输；包含当前插件清单声明与用户配置，不启动工作区未声明配置。每视图≤8连接，停止/退出等待原子进程清理 |
| `connection.list/templates/read` | 显式服务器游标≤4096字符；URI≤8192字符；响应≤8 MiB、列表≤1000项 | 真实resources/list、resources/templates/list、resources/read；不自动重放、不提供订阅、不自动发布模型工具。请求取消不保证服务器端任务已停止；连接退出会回收本连接进程 |
| `context.tool_result_pruner.measure_content/prune_content` | 文本按Unicode码点计数；阈值/head/tail可配置，返回新blocks或None | 保留非文本块，不改输入；≤8 MiB JSON。纯内容裁剪，没有DSH Session shadow事件、重放或token定价；需由agent在适当工具钩子使用 |
| `context.file_references.list(query='',limit=100)/resolve(path)` | 确定排序的相对路径候选；resolve返回实际文件/目录路径 | 原项目内，≤5000条扫描、深度64，跳过观察到的链接和依赖目录，结果明确truncated；已有成果路径恢复保持唯一性。不是原子文件快照或跨平台路径身份 |
| `context.web.fetch(url,expect=None)/search(query)` | 返回原ToolResult的JSON，保留status/error/metadata | 复用原搜索提供方、代理、重定向和响应限额，SDK期限90秒；只允许HTTP(S)，不含inline credentials。不是DSH浏览器操作，也不授予模型工具审批 |
| `context.plan_mode.enter/get/exit(session_id)` | 返回active/persistent=false | 当前启动代/视图内的强制只读工具白名单；原审批仍生效，停用撤回。不持久化模式、不代替计划审阅或原Session模式日志，不撤销已进入执行的副作用 |

验收：`test_plugin_session_data.py`、`test_plugin_feedback_access.py`、`test_plugin_capability_seams.py`、`test_plugin_mcp_resources.py`、`test_plugin_content_access.py`。迁移扫描输出 `phase2Methods`，只为已实现且语义相近的方法给 `candidateContract`；未知方法、流式附件和历史裁剪继续由agent处理，`runtimeVerified`保持false。
