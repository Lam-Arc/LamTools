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

| `context.types.register/get/require` | register接收ServiceKey及对象；get/require返回ServiceRef，调用使用`await ref.call(method,...)` | 原运行时Protocol校验、版本、发布与撤回；get仅对缺失返回None，不吞掉版本或类型错误。对应typert本地类型注册近似，不含生成的Remote/schema/resource协议 |
| `context.inspector.snapshot(limit=1000)/query(kind,name)` | 仅services/operations名称、归属、版本与可用性描述；≤1000条、≤1MiB JSON | 原宿主注册表，没有原始服务值或执行入口；对应inspector/cordisInspect后端只读发现近似，无Cordis事件/slot/浏览器实例查询 |
| `context.agent_presets.list/resolve/compose` | 异步返回原AgentPresetRegistry的JSON快照；compose显式参数优先 | 原服务租约、停用拒绝和结果副本，目录≤1000条、≤1MiB；非DSH逐会话mount/revoke，配置来源及组合规则沿用Sunday |
| `context.session_projection_cache.get/invalidate` | get先重新核对原投影权威，缓存≤128会话；invalidate返回清除条数 | 当前启动代/项目视图内缓存；运行字段和元数据都参与比较，返回副本，停用清空。不缓存DSH自定义投影或声称减少数据库读取 |
| `context.session_references.list_candidates/prepare` | 原项目可见会话候选；prepare显式选择1–8个不同会话，总摘录≤65536字符，返回sha256和截断标志 | 排除自身/隐藏/其他项目；摘要是原消息摘录，不自动调用模型、不自动注入。metadata_revision_observed只说明元数据读取修订，非多次读取的原子快照；原列表内部可能扫描整份消息 |
| `context.ptc_runtime.run(source,input=None,timeout=30)` | Python源≤8KiB，输入≤8KiB JSON，定义main(input)；支持异步main；结果≤32KiB、每路输出尾≤64KiB | 原Windows Job进程所有者及期限≤3600秒，异常/期限/不完整回执分别返回；取消等待进程树回收。`confined=false`，不包含DSH生成SDK、Node运行时或宿主回调；不把该入口当沙箱 |
| `context.dynamic_runner.define/run/stop/undefine` | 内容哈希固定Python定义，≤32份；run返回原PluginJob，结果和日志尾受原作业限额约束 | 当前视图/启动代内，不持久化；停止时关闭准入并排空固定集合，取消停止请求也要收尾。不是Cordis宿主VM、TS插件或客户端半边执行器，host_callbacks=false |
| `context.terminals.open(argv,timeout=...)` | 返回管道终端句柄：send/read/wait/close、pid及pty=false | 原Windows Job，不接受外部PID。可多次输入，send≤16KiB、写入期限≤30秒；已开始的写入超时/取消须先回收进程并等待写线程。无PTY/窗口大小/交互信号或持久重启恢复 |
| `context.authorization.register_flow/list/begin/cancel` | 流提供label、methods、credential键和异步run(control)；begin明确method及可选prompt/notify回调，期限≤300秒 | commit写入并回读提供方自己的受管凭据才返回authorized，不导出值。发起方或提供方停用均取消并排空；同流只允许一个尝试。cancel独立取消仅供流所有者，发起方可取消自己的begin任务；取消可能已经提交凭据，须核对后重试；不充当工具审批或DeepSeek平台OAuth实现 |

验收：`test_plugin_session_data.py`、`test_plugin_feedback_access.py`、`test_plugin_capability_seams.py`、`test_plugin_mcp_resources.py`、`test_plugin_content_access.py`、`test_plugin_host_views.py`、`test_plugin_session_references.py`、`test_plugin_program_access.py`、`test_plugin_terminal_access.py`、`test_plugin_authorization.py`。迁移扫描输出 `phase2Methods`，只为已实现且语义相近的方法给 `candidateContract`；未知方法、流式附件和历史裁剪继续由agent处理，`runtimeVerified`保持false。

审查修正：资源连接关闭后必须重新显式open，固定句柄不会自动重连；标题读取最多1024字符且明确title_truncated；计划白名单包含原list_dir/search_content；动态停止与授权撤回均有并发/取消复现测试。子代理SDK创建时捕获父执行目录并保存到原成员记录，重新开启保留原目录；子工具每次请求核对该目录，丢失时失败，不重绑项目配置。原生调用未提供execution_directory时继续使用原项目，DSH目录事件和即时通知仍需适配。


## 无人值守续做的原生接口

user:“继续，无人值守模式，不要停下来”+(补齐真实后端接口并记录差异，定时续做接续同一清单)。

| 入口 | 真实行为与限额 | 差异及清理 |
| --- | --- | --- |
| `context.storage_domain.open(name,tables=[...],version=1)` | 领域read/commit，表和global_value在原SQLite单快照事务提交；必须expected_revision，整域≤1MiB、≤64表、每次≤100项变化 | 精确版本和表名，错误不部分写入；无DSH schema推断/compatibleVersions/后端路由。写入确认未知时保持原KV未知状态保护 |
| `domain.on_change(callback)/close` | 每插件/领域≤64个同步观察者，提交确认后发name/revision，观察者失败不推翻已提交结果 | 当前进程通知；关闭/停用撤回，read回原权威，不承诺跨进程广播或异步写链 |
| `context.agents.create(request_id=...,title='')/attach(id)` | 原会话存储+桌面thread.start，固定插件/项目命名空间；目录必须存在，相同创建ID回原会话 | 记录与事件为两次原提交；交接失败报may_have_changed，同ID重试修复且不覆盖原标题。全局可见性仍归原宿主，不称SDK命名空间为系统ACL |
| `handle.followup/steer/state/wait/events/cancel/resume/dispose` | 原接收/队列/持久回执；resume继续同一已提交paused回合，重复请求回原事件；dispose撤回句柄并请求原取消，保留历史 | 插件停用撤回门面，已接收工作归原宿主；可重载后attach。非DSH AgentHandle/activation或根插件挂载协议 |
| `context.otel.create_event_reporter/create_session_reporter` | 默认sharing=disabled；启用须显式HTTP(S)收集端及共享选择，feedback-only只收显式kind=feedback；共享策略只读，headers由调用方显式提供 | 不自动采集/上传会话或读取密钥，不实现DSH完整session-log/record waterfall/产品自动统计；OTLP scope仅带插件名，不隐式添加项目/会话身份 |
| `reporter.emit/status/flush/shutdown` | 原记录≤64KiB、编码后≤128KiB，每视图≤8报告器，队列≤128、每批≤16；HTTP及关闭各≤30秒 | 真实OTLP JSON HTTP，HTTP2xx计数sent只代表传输响应，不保证collector部分成功或仓库落库。失败不重放；溢出/失败/关闭丢弃显式计数，停止排空并取消挂起HTTP |
| `context.settings.read/validate/replace/reset/public` | 原Config/CAS加Draft2020-12标准校验；问题只含位置/规则，reset用根或直接属性default | 拒绝schema远程引用，default/examples仍为普通数据；format默认按标准作注释。public保守隐藏writeOnly/password/x-secret、未知投影/未声明字段，不返回schema默认值；无动态namespace/volatile/继承reset/前端接线 |
| `context.workspace_changes.snapshot/compare_status` | 原Windows Job只读Git；固定仓库根，拒绝父仓库，隔离GIT_DIR等变量、关闭fsmonitor和可选index锁；NUL解析路径/rename，≤1000项、输出≤1MiB | status_revision是状态签名而非文件内容指纹，同一M状态内容再变化不会变成新状态；不冒充文件历史或DSH事件/投影 |

新增验收：test_plugin_storage_domain.py、test_plugin_agent_access.py、test_plugin_telemetry_access.py、test_plugin_settings_access.py、test_plugin_workspace_changes.py。迁移报告对遥测消费者给factoryContract，必须先显式创建默认关闭的reporter；全部仍为agent-required，runtimeVerified=false。

`context.agent_loop`是原根会话工厂门面的公开入口，复用已验收的context.agents实现；create/attach和handle.resume走原desktop kernel/持久历史，不能替换内核、挂载Cordis scope插件或获取原Session writer。原生同回合模型续跑和重复请求的测试为test_plugin_agent_access.py。


## 子代理模型政策

user:“给我把 2 阶段做完，前端除外”+(模型目录与获准路由区分，政策复用原父会话持久元数据与修订)。

`await context.subagent_models.read(parent)`返回`revision/configured/allowed/default`；allowed是模型记录ID、wire ID、provider_id和provider名称的固定身份快照，不包含凭据。`await set(parent, allowed=[record_id,...], default=record_id或None, expected_revision=revision)`最多32项，默认必须在名单内，空名单明确拒绝。修订冲突报subagent-model/conflict，调用方重读后自行决定；不自动覆盖并发政策。写取消会等原SQLite短提交结束再传播取消。

`await select(parent, ref=None)`以原模型目录精确ID/唯一别名解析，再检查政策固定身份和原background显式提供方可用性，不发模型请求；返回ModelDescriptor字典。未配置政策报not-configured，无允许默认或不在名单报denied，修改路由身份报retargeted，原生无法保留唯一提供方身份报ambiguous-route；模型目录自身错误沿用model/*。未知/不可见/异项目父会话沿用session-data/*，旧启动代沿用service/*。仅根父会话，插件所有者相互隔离，重载仍保留政策。

`context.subagents.create`允许省略model以使用此默认；create/message/resume均执行SDK准入，interrupt/close不受收紧名单阻塞。原监督器仍持有执行和最终路由权限。尚未配置政策的旧SDK调用仅保留原显式model行为；选择接口自身始终要求政策。政策收紧不会追溯取消已接收运行。

这是一项插件自设的SDK准入政策，不能限制绕过SDK的本机Python代码或原生工具，不是全局模型ACL/最终HTTP授权。政策读取、提供方预检查和原生创建没有跨配置文件的代际锁；配置在准入后改变仍可能影响后续调用。provider字段身份固定不意味着URL或凭据固定。不同记录共用wire模型名会丢失原生路由身份，因此明确拒绝。无DSH session投影事件、模型发现开关、父模型继承或推理等级默认协议；reasoning_level仍显式交原监督器验证。迁移保留agent-required。


## Office 转 PDF

`await context.office_to_pdf.convert(content: bytes, extension="docx"|"xlsx"|"pptx", timeout=60)`返回`pdf: bytes/bytes: int/engine: "libreoffice-cli"/missing_fonts: None`。每次用实际LibreOffice CLI、独立profile和原Windows Job执行；两项同时转换/视图，超限报office/busy，不排队。安装位置或PATH没有转换器报office/unavailable；默认期限60秒、可设(0,120]，超时报office/timeout；取消先等原受管进程关闭再移除临时目录。停用沿原作用域等待已接收调用排空，最迟仍受转换期限约束，旧门面拒绝调用。

只接收已由调用方取得授权的OOXML字节，输入≤16MiB，ZIP≤2048项、总声明解包大小≤64MiB，检查CRC、重复/越界名称、加密及VBA条目；不支持doc/xls/ppt或文件路径读取。参数报office/invalid-input，归档报office/invalid-document，非成功退出报office/failed，缺失/过大/非PDF报office/invalid-output，临时读写或清理失败报office/io-failed；原进程和启动代错误仍为process/*、service/*。PDF≤32MiB，成功返回前已清理scratch，不写会话记录或缓存。测试用安装的LibreOffice实际转换三种格式并从PDF读取页和文本，另验证限额/取消/原Job期限回收。

命令结构沿用现有office-renderer的LibreOffice方式，接到原插件进程所有者；不启动或结束用户Microsoft Office。独立profile设高宏安全等级；此转换不是对恶意文档的隔离沙箱。未实现DSH延迟授权文件读取、source/version身份、优先队列、缓存去重、generation、转换器池或字体信息（None表示未知，不是缺失字体为空）。调用方负责源读取和额外授权，迁移render不能直接替换为此字节接口，保留agent-required。


## 无界面启动事实

`context.headless_startup.get()`同步返回当前`run-local`调用的`task/thread_id/requested_session_id/json_summary/permission_preset/approval_policy/work_root/additional_writable_roots`副本。源为冻结宿主值，在原CLI装配插件factory前写入，任务/身份及有效权限来自原入口解析；读取不修改权限。additional_writable_roots固定为空，未承诺额外写授权。桌面没有对应调用时为startup/unavailable；该次调用收尾移除源后旧门面为startup/host-changed；受管启动代关闭为service/*。只读同步操作无需取消或持久化，实际CLI仍负责原任务执行和数据库保存。

原run-local当前使用factory-only插件装配，所以此只读接口也允许factory取得，不伪造start钩子；正常或kernel失败收尾撤回，早于kernel收尾区的既有装配异常不保证回收已泄漏factory引用。测试从实际磁盘插件factory取得值，运行原kernel并检查原数据库与返回结果，退出后旧门面拒绝。

DSH headlessStartup本身仅是CLI参数提供服务。Sunday的raw表示最终JSON summary，非DSH NDJSON事件流；stdin/参数语法、--add-dir、DSH精确既有Session采用与退出IO协议不在这个快照接口内。requested_session_id是原请求，thread_id是原入口实际身份，Sunday原入口可以为请求ID建立新会话；不能把它当成DSH已存在Session的证明。迁移需读取字段并调整语义，保留agent-required。


## 目录选择 browse 后端

`context.directory_picker.capability()`返回同一视图/启动代内稳定的`kind="browse"`对象。同步`list(path=None, limit=100)`默认列固定项目根，path若提供必须全限定且在原项目内；最多1000个原始目录项，不遍历全目录后排序，返回`path/entries[{name,path}]/ancestors[{name,path}]/truncated`。entries只含普通目录，不含文件/链接；原始层被截断时truncated为真，即使其中目录数量小于limit。祖先最多到固定项目根。

同步`create_directory(parent,name)`在明确给出的既有父目录下创建一个孩子，返回绝对路径；拒绝分隔符、保留设备名、尾点/空格和越界。失败分别为directory-unreadable、directory-exists、directory-create-failed；关闭作用域为service/*。两个入口使用原PluginFilesystemAPI检查路径、链接及项目边界，不自行授予根外权限或改变工作目录。真实目录创建即持久副作用，无额外选择记录/回滚。

仅支持固定本地盘，拒绝UNC/映射网络盘和可移动盘。同步本地扫描无等待/取消句柄，不能在进入系统目录操作后中断；不提供DSH异步网络扫描取消保证。沿用原可信插件文件门面的检查边界，不防并发恶意链接替换。没有native系统对话框、项目根外workspace选择、前端浏览器或Remote接线；DSH调用方须调整默认home、异步API和结果字段，迁移保留agent-required。


## 模型请求扩展字段

`context.llm_extensions.register(field, prepare)`返回原ServiceRegistration撤回句柄；按插件启动代与固定项目使用原注册权威，跨插件同字段冲突、并发启动仍按原发布事务冲突。field为≤64字符普通标识符，不能替换model/messages/stream/tools等base字段；若与具体base body其他键冲突，该次省略并在omitted给出base-field-conflict。最多32字段/项目请求。

同步或异步`prepare(ExtensionRequest)`回调读取`body/session_id/purpose`：body为原HTTP客户端应用默认值、模型注记和适配序列化后的**扩展前**JSON快照，递归只读dict/tuple，无凭据/headers；session_id来自元数据_runtime_session_id，仅标签，不授予会话访问；purpose为compaction/session-title或None。回调返回None或`{value: finite_json, accept?: callback}`。可手动`await api.prepare(body, session_id=None, purpose=None)`得到fields/omitted和幂等异步accept。base≤1MiB，每字段≤64KiB，数据复制冻结后提供方修改原对象不影响发送。参数为llm-extension/invalid-request，过多字段为too-many，注册参数为invalid-provider/base-field。

准备逐字段运行，每个协作式回调期限5秒，失败/无效值只省略该字段（omitted=provider-failed），不暴露底层错误正文；调用取消传播并释放原租约。`context.llm.complete/stream`通过调用上下文接到原CoreHttpLLMClient；HTTP2xx响应头到达后、响应体读取/JSON/SSE解析前调用accept，响应随后失败也不会撤销接收事实，非2xx不调用。正常/流式及取证记录开关均有真实httpx序列化/响应体边界测试，未发付费模型请求。手动prepared.accept只供已确认HTTP接收的调用方使用。

接收callback逐个原提供方租约执行、各5秒，所有callback结算后统一llm-extension/accept-failed（SDK外层仍为llm/provider-error）；同一prepared的并发或重试accept共享一次任务，包括失败。接收期间调用方取消仍等该任务结算再传播，不能将模型请求误当作未接收后盲重试。提供方已撤回时不进入旧callback，会显式失败；字段一旦准备/发送可能已被远端接收，撤回不追溯移除。准备与接收各自取得/释放租约，不跨空闲流保留租约，关闭时不锁住宿主；不合作的同步callback与其他原Python扩展一样不能被抢占。

这是SDK请求范围内、项目分隔的近似接口；主助手后台HTTP调用没有自动安装插件扩展。支持明确声明supports_request_extensions的原HTTP客户端；自定义客户端不能保证接线时，在实际派发前报llm/extensions-unavailable。异步上下文在每次complete/stream入口与pull结束恢复，回调不进入LLMRequest JSON元数据。没有DSH TypeScript字段声明合并、AbortSignal对象、全局官方DeepSeek适配器生命周期或首次失败日志协议；迁移保留agent-required。HTTP文件已有用量记录改动逐处保留。


## SSH 本机 OpenSSH 传输

`await context.ssh.connect(host=..., user=..., port=22, identity_file=..., known_hosts=..., timeout=10)`固定明确主机、用户、端口及原项目内身份/已知主机文件，先实际发起SSH并执行exit 0探测，返回配置句柄。身份文件和known_hosts≤1MiB，使用前复用原文件路径规则；不读取文件正文到SDK。每次`await connection.execute(command, timeout=30, max_output_bytes=65536)`新建独立SSH连接，执行≤8KiB远端shell文本，返回原Job的status/exit_code/quiescent、stdout/stderr字节与lost标记，transport=openssh、remote_cleanup_guaranteed=False。期限(0,120]，输出限额沿原进程1MiB上限，最多8配置/视图；不把句柄当作常驻SSH会话。

强制StrictHostKeyChecking、公钥、BatchMode及显式身份，禁用密码/交互/agent、默认配置、默认known_hosts、主机记录更新、复用和转发；不修改所给文件，生产不生成/调整密钥ACL。私钥权限和加密口令必须由提供方预先满足系统OpenSSH要求。身份/主机文件按每次原路径再检查，内容变化由下一次OpenSSH重新读取，不是配置代际锁或对恶意路径替换的OS安全边界。

ssh/invalid-config、busy、unavailable、probe-failed、invalid-command、closed为本门面错误；ssh/timeout和transport-failed表示远端效果可能已经存在，may_have_changed=True。OpenSSH退出255不能区分传输故障与远端程序255；其他非零退出保留给调用方，原进程/fs/service错误仍按原契约返回。取消或close等本机Job回收；close先关准入并等待已接收但尚未得到句柄的spawn，不能漏掉迟到进程。插件停用沿原作用域排空期限内调用和回收；不能据本机进程退出保证远端孙进程已停止，也不自动重试远端命令。

验收用临时127.0.0.1 AsyncSSH服务、临时ssh-keygen身份及明确known_hosts，系统OpenSSH实际认证并驱动测试服务的真实shell；另验证主机密钥不匹配不改文件、取消与close/启动竞争。AsyncSSH仅dev测试依赖，当前测试安装在项目.lam/tmp/dsh-ssh-testdeps，未改全局Python环境。上游SshConnection明确是POSIX客户端的已校验helper/hash/hello、RPC、独立流转发与心跳租约；这些协议不在本近似接口中，DSH request/connectStream没有自动方法映射，迁移仍交agent重构。


## Windows 文件写隔离及政策

`await context.sandbox_policy.resolve(session_id=None, mode=None)`返回mode/workspace_root/project_root/session_id/revision/additional_writable_roots/consumer。默认read-only，项目及目录取自原固定视图或同次原会话读取，复用原目录校验，缺失目录拒绝。`await set(session_id, mode=..., expected_revision=...)`在原会话元数据按插件保存三种模式，冲突sandbox/conflict；其他元数据保留，重载持久。保存取消等原短提交结算再传播。隐藏/异项目会话仍按session-data/*，原目录失败按working-directory/*；模式/修订/状态错误为sandbox/invalid-mode、invalid-revision、invalid-policy。

`await context.sandbox.run(argv, session_id=None, mode=None, timeout=30, max_output_bytes=65536)`从上述同一政策入口取得模式和目录，mode显式覆盖存储值，仅是可信SDK调用方的政策输入，不是审批。最多256参数/32KiB、期限(0,120]、输出≤1MiB/流；预校验后调用实际安装的官方Windows ACL runner，由原Windows Job持有runner及子进程。返回status/exit_code/quiescent/stdout/stderr/lost标记、policy、backend、confined和enforcement；只有显式danger-full-access返回confined=False/enforcement=none，其余enforcement=partial。超时沿原结果status=timed_out；调用取消先等Job清理再回收scratch。成功返回中的scratch_directory仅是已删除目录的诊断路径，不是可复用资源。

Node22+及独立`core/runtime/windows-sandbox` npm依赖必须实际安装；锁文件记录官方0.2.2-alpha.2和完整integrity图，Python打包资源包含该目录。没有前提报sandbox/unavailable；有签名的runner失败为runner-failed，不重试不受限命令，临时读写/清理失败为io-failed；原process/*和service/*照常传播。运行时使用已发表官方版本，不声称npm产物与固定上游源码逐字节相同；真实行为与固定契约单独验收。

采用官方限制令牌、Low完整性、能力SID及ACL机制。workspace-write允许工作区及该次私有临时目录写入；read-only没有写授权，旧工作区grant对只读令牌无效。**工作区允许ACE、环境删除拒绝及Low标签是官方后端为复用保留的常驻修改**；每次私有临时目录和临时grant归该次运行，原Job已停止后回收。测试只在可丢弃目录施加这些修改；不会为验证而修改真实项目或用户密钥。

隔离是partial：保留官方Everyone/logon SID环境许可和硬链接别名边界，不提供读、网络或进程可见性限制。UNC不支持；私有临时根必须在工作区外，不满足时拒绝。没有additionalWritableRoots、DSH confine返回argv、任意后端选择、远端执行或全局工具接线。普通filesystem/processes/shell/terminals与主助手仍沿其原权限；仅此显式SDK消费者消费该政策，不能把保存政策当作它们已获得OS隔离，也没有DSH Session事件或模型runtime-context投影。迁移confine必须把包装argv流程改成run并人工处理返回值，保留agent-required。

行为证据涵盖实际文件效果、只读/工作区写区别、不可用不回退、显式不隔离、原政策持久化/CAS、目录变更、插件/隐藏父会话/代际，以及取消真实受限子进程后Job和临时目录回收。构建前独立npm ci及完整依赖边界见core/runtime/windows-sandbox/README.md；前端依赖未改动。


## Web 运行胶合

`context.web_app.get_advertised_url()`同步返回原HTTP静态宿主明确配置的浏览器根地址，不包含token、用户信息、query或fragment。`create_core_agent_http_app(frontend_dir=..., advertised_url=...)`在原插件start前发布不可变值，关闭时撤回；已有serve入口为明确frontend_dir及非0端口提供协议/地址，wildcard bind的本地广告地址转换为127.0.0.1或::1。端口0尚未知时不发布，既有serve诊断行不在此修改范围。API-only、纯Tauri窗口及未提供广告配置时为web-app/unavailable，不推测一个URL。

值只做HTTP(S)/地址格式和尾斜线标准化，不改变认证、代理、静态文件挂载或判断监听已就绪；显式advertised_url必须配合既有frontend_dir。错误为web-app/invalid-url、unavailable、host-changed，原启动代停用为service/*。读取同步无副作用，无取消/持久化要求；源替换和关闭后旧门面拒绝，不撤销调用方此前复制的字符串。

实际原HTTP应用加载磁盘测试插件，start读取地址，并由原静态路由真实返回临时测试文件；另验证URL字段拒绝、关闭门面及原serve的已知/未知端口。没有改动产品前端/样式，没有自动打开浏览器、DSH_WEB_URL环境注入、DSH loader审核/进程token发布协议或Tauri广告地址。反向代理URL仍由宿主明确提供并自行配置代理，迁移保留agent-required。

验收避开了并行模型配置改动的无模型占位构造错误：LLMConfig已有必填provider_id，http_agent_app.py该旧分支尚未补；未替他人修改，测试使用明确模型配置。此点待统一处理，不能把Web验收解释为该启动分支已修复。

后续统一修复：上述无模型占位构造现已补齐provider_id=""，新增实际无模型应用启动与/api/health验收通过。另已补齐CoreConfigRoutingLLMClient对原HTTP扩展能力的声明，新增普通/流式SDK经实际配置路由包装器发送字段和接收回调验收通过。先前的阻塞描述保留为历史证据，现不再属于未处理项。


## DeepSeek 账户（后端近似）

`context.deepseek_account.open(platform_origin="https://platform.deepseek.com", inference_origin="https://api.deepseek.com", allow_loopback_http=False, request_timeout=10, locale="en-US", client_version=None, timezone_offset_seconds=0)`返回当前插件代/项目/发行环境内缓存的账户客户端（≤8个）。固定HTTPS origin禁止用户信息/路径/query/fragment；仅显式开发选项允许loopback HTTP，推理令牌只给配置的完全相同origin，不跟随重定向。version默认原包版本，timezone_offset_seconds默认0、由调用方明确提供所需客户端偏移。客户端不在open或状态读取时发起登录。

异步get_state、sign_in(callback_origin=明确loopback HTTP带端口, prompt=回调, timeout≤300)、cancel_sign_in、sign_out、get_profile、get_balance、resolve_token、reject_token、get_platform_session和get_device_identity。sign_in等待完成，复用原authorization流/撤回/取消/期限；回调收到authorize_url/callback_uri，调用方负责打开浏览器、接收回调并返回{code,state}，本接口没有内置浏览器或HTTP回调路由。按官方auth_init/auth_exchange/auth_cancel路径和双层业务envelope执行，校验S256 PKCE、state、TTL、同源固定授权/完成页；每个请求≤30秒、响应≤64KiB，错误只返回account/*安全代码，不含响应正文、code/verifier或token。

grant和device只存在原插件所有者的DPAPI凭据空间；原凭据新增同步compare_exchange(key, expected=None|string, value=None|string)，在同一原跨进程锁内比较/加密提交，None表示无值/删除。原AuthorizationControl.commit新增可选expected_value，默认行为不变；账户使用条件提交并回读，旧登录不能覆盖更新grant。拒绝或HTTP401/code40003只按令牌匹配删除当前grant，旧查询不删除新登录。sign_out先取消本客户端登录，再条件移除本地grant，尽力发原logout；失败不恢复本地grant，无后台重试，不影响API keys或device。普通资料/余额/退出请求持有原作用域租约，停用排空期限内请求；调用取消关闭HTTP流，授权取消等原流清理。

状态不含凭据。资料仅投影id/name/avatar_url/contact，余额保留经过校验的CNY/USD十进制字符串，不把失败当零余额；grant变化时丢弃旧查询结果。get_platform_session和resolve_token是Host-only凭据读取，不可暴露给前端RPC；身份只用当前grant匹配的资料缓存，get_device_identity读取不创建设备。所有数据仅为当前插件/项目与origin组合，无全局系统账户接管。

近似差异：没有DSH立即返回的startSignIn、完整AccountView/watch/identity事件、bonus通知/确认、自动生产浏览器登录、内置callback/SSH端口桥接、部署自定义headers或logout重试。测试在临时本地HTTP Platform服务执行真实请求、校验PKCE并驱动原DPAPI/授权控制器，未登录生产平台；这证明协议和宿主行为，不声称平台当前生产登录已实测。迁移必须先open并提供callback bridge，所有方法仍agent-required，未知方法不生成候选。

Office补充边界：LibreOffice在过长临时profile目录下可能退出0但不生成PDF，门面会报office/invalid-output，不报告成功。三格式验收使用真实系统临时根并记录/确认实际scratch删除，不把长pytest目录作为Office profile前提。

持续审查补充：SDK克隆实际配置路由时保留浅层思考包装及其系统提示，普通/流式HTTP扩展行为均有新增验收。显式models.select、llm.complete和已配置子代理政策准入复用原enabled检查，禁用记录仅保留只读发现；不声称原CLI全部加载路径都已强制禁用。

账户open的不同请求期限实例可共存，授权流标识与缓存配置对应，同插件/项目/来源的grant仍共享并经CAS保护；重复相同配置复用实例。回调state须为ASCII且恒时匹配，无效值返回account/protocol，清理已初始化远端授权，不交换或持久化令牌。这两条行为由临时真实HTTP服务新增验收证明。

SSH命令准入也校验UTF-8可编码性，孤立代理字符返回ssh/invalid-command且不启动传输；拒绝后原配置仍可使用。新增验收以真实临时SSH服务和系统OpenSSH确认后续命令成功。

文件引用list取消会请求扫描线程在目录/条目之间协作停止，等待实际线程退出后才传播取消和释放原作用域租约；重复取消及同时停用均不能提前放弃扫描。已经进入的本地系统目录调用不能强制中断，可能延迟取消；仍无原子快照、跨平台身份或网络目录截止时间保证。

迁移包PORTING.md现逐方法保留机器报告中的candidateContract或suggestedContract、conversion和difference。未知方法仅列人工核对差异，不生成未经验证的候选；输出仍标记runtimeVerified=false，不能将这份交接文档当作已移植代码。

授权取消补充（2026-11-05）：撤回单个流、停用发起方、显式cancel、超时及调用者取消均关闭本次原AuthorizationControl，再取消并等待提供方。提供方即使捕获取消，也不能继续commit/prompt/notify，返回authorization/closed；控制器固定原提供方和发起方作用域。撤回/取消不会回滚此前已经提交的凭据，也不能撤销已经进入的交互回调；本改动限制后续调用。同一流的下一次正常授权不受影响。15项撤回/取消交叉验收及1项重新授权/旧控制器拒绝验收通过。

模型流并发关闭：aclose会等待初始化/读取提供方操作退出，再关闭来源；取消后的迟到来源会被回收，迟到事件不发布。关闭调用者取消在清理完成后传播。六项新增验收涵盖四种操作/取消组合、重复取消和原HTTP SSE/扩展完整接收。必须配合取消，细节见plugin_phase2_runtime.md；不声明强制终止Python代码。

设置公开投影补充：声明属性还会应用匹配的patternProperties，以及属性存在时触发的dependentSchemas中的writeOnly、x-secret和format=password标记。触发依据是属性存在，值为false也触发；未触发的依赖不影响公开属性。未知字段仍保守隐藏，这不是完整JSON Schema注解收集协议。七项新增实际配置保存/公开读取验收证明保密值不会进入public结果，同时原配置值不被改写。

会话查询失效检查补充：原只读扫描返回后再次核对宿主和存储，公开门面再检查原插件启动代；扫描期间关闭宿主、更换存储或撤回启动代，不返回迟到页面，分别报告session-query/closed、session-query/host-changed或service/scope-closed。已有查询租约仍正常排空，不承诺对多次数据库读取提供原子快照。三项新增真实SQLite扫描竞争验收通过。

MCP资源清理重试补充：失败或被取消的关闭任务可重新执行原传输清理，失败期间资源句柄继续由原插件拥有；原MCPClient在进程退出和读取任务结算前保留它们的引用，不能先丢失进程再将重试报告成功。关闭开始即禁止新请求，重试不重新启动旧连接、不重放资源请求。两项新增验收使用真实MCP子进程，分别注入门面清理失败和实际terminate首次失败，证明重试确实回收同一个进程并释放句柄；不声明对任意逃逸孙进程的新增保证。

审批决定补充：决定事务在写入前复核原会话服务和宿主身份；等待提交期间原服务关闭或宿主替换，先前allowed-once答复转为cancelled并写入原审计库，不返回批准。同宿主/同持久化权威的临时上下文对象刷新仍有效。三项新增实际审计库验收覆盖两种失效和正常上下文刷新；不声明跨宿主状态与SQLite事务的原子快照，也不增加前端审批能力。

反馈参数补充：message_feedback.put的rating必须是positive/negative字符串，对象或数组返回session-data/invalid-rating；消息note/category及会话text/category必须可编码为UTF-8，否则返回session-data/invalid-feedback。原有字符长度、NUL、反馈版本与原CAS限制不变。五项新增实际SQLite验收确认拒绝后反馈列表为空、会话元数据不变，且下一次正常提交从版本1成功；不把参数错误归为存储失败。

检查接口补充：inspector.query(kind,name)从原describe_host目录精确匹配名称，不再受snapshot默认1000项截断影响；命中后使用与snapshot共用的描述字段白名单和1MiB结果限制，不导出服务值或执行操作。snapshot仍保留1–1000条上限及truncated标志，没有新增分页。两项新增验收使用真实服务/操作目录各1101项，确认可查询末项、结果复制及启动代撤回。

权限偏好失效检查补充：permissions.read在原get_readonly返回后复用原宿主/存储检查，公开门面返回前复核插件启动代；等待期间宿主关闭、更换存储或撤回插件，分别报告permissions/closed、permissions/host-changed或service/scope-closed，不返回旧偏好。三项新增真实SQLite读取竞争验收通过；此结果仍不是授权凭证，不改变预设规则或运行策略，不提供跨多次读取的原子快照。

执行目录失效检查补充：原get_readonly_revision返回后再次核对原宿主/存储；等待期间关闭宿主或更换存储时，目录get/set及原运行时缺失目录恢复都在继续操作前拒绝，不返回旧路径或因这次读取向旧存储提交恢复。公开门面沿用working-directory/closed、working-directory/host-changed，原内部运行时关闭沿会话错误返回。六项新增实际SQLite验收覆盖三条路径与两种失效，确认原元数据/修订不变；不增加跨宿主状态与后续CAS写入的原子保证。

共享会话数据失效检查补充：原会话记录读取前后复核宿主/存储；标题、附件、反馈、投影和引用的共用只读门面在返回前再次核对启动代及宿主。关闭/替换报告session-data/closed或session-data/host-changed，撤回启动代按service/*；失效初次读取不能继续标题修改。七项新增真实SQLite验收覆盖标题get/set的四种读取竞争及只读发布的三种失效，确认原存储未变。已经开始的写入仍沿原finish_on_cancel收尾，不新增提交后失效即回滚或多次读取原子快照保证。

目标/计划只读失效补充：goals和schedule的get/list在原业务操作返回后再次检查原操作目录及插件启动代；等待期间目录替换报告durable/host-changed，启动代撤回按service/*，不发布旧结果。八项新增实际持久管理器/SQLite验收覆盖两种业务、两种读取及两种失效。写入继续按原持久化事实结算，插件停用不删除已提交任务，不改变原Arrange执行器，也不增加读写原子快照或提交回滚保证。

检查点失效检查补充：会话可见性读取后复核原操作目录、会话服务、宿主和存储，失效时不继续向旧目录派发；列表在原操作返回后再检查启动代和上述绑定，沿checkpoint/closed、checkpoint/host-changed或service/*返回。十二项新增真实检查点/SQLite验收覆盖派发前失效、只读发布失效及已派发写入的原提交收尾；后者不会伪装为回滚。仍不回退工作区文件，也不提供跨宿主状态和SQLite操作的原子保证。

管理只读失效补充：plugins.list和profiles.list/resolve在原业务操作返回后复核操作目录及插件启动代；目录更换返回host/changed，启动代撤回按service/*，不发布旧列表/运行档。六项新增验收走真实插件管理目录和manifest运行档解析器。启停、重载仍沿原管理器与提交事实结算，不改变自停拒绝或增设前端管理入口。

根代理失效检查补充：创建在原会话actor中读取前后复核宿主/启动代，记录读取后也复核，state/wait/events在原会话调用返回后复核。失效的创建读取不继续向旧存储创建孤立记录；挂接和只读结果不越过失效发布。十五项新增实际会话/SQLite验收覆盖五种操作及关闭宿主、更换存储、撤回启动代；错误沿原session/closed、agent/host-changed或service/*。已发生持久写入仍按原create-incomplete/同request_id修复或提交事实结算，没有原子读写或提交回滚保证。agent_loop复用同一门面，没有新增kernel。

子代理失效检查补充：父可见性读取后、创建模型准入后/原生派发前，以及列表原操作返回后，复核原目录、会话服务、宿主/存储和启动代；失效时不继续派发，列表不返回迟到结果。十八项新增原监督器/持久业务验收包含十六项边界组合及两项已派发创建的真实提交收尾；不回滚已经创建的持久成员，也不声明跨这些检查的原子事务。机器清单另修正历史“目录捕获未覆盖”措辞：现有SDK创建确实捕获父目录，仍没有完整DSH目录事件或activation协议。

模型扩展冻结快照补充：prepare的字段冲突判断与提供方收到的body共用同一冻结请求，不再读取调用者仍可改变的原字典。调用者在某提供方等待期间新增字段，不会让后续合法扩展被误省略；删除原有字段也不能让扩展覆盖该请求快照中的基础字段。两项新增受管提供方验收证明这两个方向；不增加新的HTTP派发、全局adapter或可变请求协议。


CLI启动清理补充：原run-local从取得数据库起保护整个启动准备和kernel执行，先撤回headless_startup，再按原顺序清理插件、运行任务、MCP和数据库；一项清理失败仍尝试其余已取得资源的清理，错误继续传播。四项新增真实CLI/SQLite验收覆盖装配、MCP构造、技能初始化和插件清理失败。运行档modelScene先通过原场景解析器选模型，显式model_id优先；选定结果用于配置加载及运行，不被后续缺省值覆盖。另四项新增验收覆盖显式/场景模型与配置加载/注入客户端两条路径，其中配置加载在入口截获，不进行真实网络请求。不新增DSH CLI或JS运行兼容。


CLI运行档覆盖补充：使用原ProfileSpec的字段替换而非手工重建，保留mcp_servers、mcp_tools、skills、approved_tools及后续原生声明字段；只更新CLI明确覆盖的工具、审批和预算。两项新增真实manifest/CLI验收覆盖无覆盖及混合覆盖，检查原apply_profile实际接收到声明且MCP allowed_tools和approved_mcp_tools确实生效，任务正常结束。保留字段不等于CLI已激活指定MCP服务器或加载指定技能，此处不新增这些能力。


CLI运行档发现补充：显式plugin_roots同时用于运行档查找和插件装配，未指定时保留原默认根；不改变PluginHost状态文件或运行档解析规则。两项新增真实manifest/CLI验收覆盖显式目录与默认回退，两条路径均完成任务并将选中的运行档交给原apply_profile。修复前显式目录无法找到运行档。


代理预设只读失效补充：list/resolve/compose等待提供方后，在发布JSON快照前检查原请求启动代和原ServiceRef。撤回请求启动代返回service/scope-closed，替换提供方返回service/stale，不发布迟到旧值，原调用租约正常释放。六项新增验收通过真实AgentPresetRegistry业务及可控异步提供方等待覆盖三种查询与两种失效。只加强只读门面，不改变通用ServiceRef.call对已执行业务的结算语义，也不新增挂载协议。


后台作业只读等待补充：jobs.wait在原等待完成或超时后、返回JobView前复核原启动代；等待期间撤回返回service/scope-closed，不发布迟到结果。两项新增真实回调验收覆盖正常结果及撤回后拒绝；回调本身均实际完成，拒绝发布不伪装为回调撤销。kill和原停用回收沿原语义，不新增会话ACL或持久化。


动态程序停止失败补充：stop/undefine对固定作业集合逐一执行原jobs.kill，某项异常不会跳过后续作业；全部尝试后以ExceptionGroup报告，原_runs只保留失败作业供重试。失败的undefine保留定义，重试全部成功才删除。两项新增验收使用真实运行中的作业回调，注入第一次kill失败，确认另一作业实际退出、失败所有权保留、重试实际回收剩余作业及定义语义。未增加强制终止不合作Python回调或DSH VM能力。


Web只读响应失效补充：fetch/search共用入口在原工具等待完成后、公开结果前复核请求启动代。撤回返回service/scope-closed，成功及失败响应都不越过失效发布；原网络请求已经发生，不伪装为撤销。四项新增验收经真实本地TCP/HTTP与原抓取处理器覆盖200/503及正常/撤回组合，确认原结果和错误语义、租约释放。没有新增搜索提供方、模型审批或网络隔离保证。


语言查询只读失效补充：hover/goToDefinition/findReferences/goToImplementation在提供方等待后、结果规范化前复核原请求启动代及同一ServiceRef。请求撤回返回service/scope-closed；提供方撤回沿原service/unavailable或替换时service/stale，不发布迟到结果。十二项新增验收覆盖四类操作与正常/请求撤回/提供方撤回，实际注册并调用异步提供方，检查双方租约释放。此证据仅证明受管接口，不等于安装或验证了真实语言服务器，不新增DSH语言服务器启动协议。


语言查询参数补充：operation先验证字符串类型再匹配四类操作，数组/对象等统一返回capability/invalid-query，不泄露集合查找TypeError，也不派发提供方。四项新增验收覆盖数组、对象、null和整数，确认错误归属、租约释放以及随后正常hover仍可调用。不增加语言服务器能力。


作业/遥测枚举参数补充：job.emit的stream先验证字符串类型，数组/对象返回job/invalid-output，回调可处理后继续正常输出；遥测sharing/severity同样先验证类型，按原ValueError拒绝，错误sharing不分配报告器，错误severity不入队。六项新增验收覆盖三入口与两类输入，作业实际完成且只保留正常输出，遥测通过真实本地HTTP仅发送随后合法记录。默认关闭和共享规则不变。


领域存储通知撤回补充：提交后的本地通知在每个回调前复核原注册令牌，前一个回调撤回后续观察者或关闭其句柄，后续观察者不会因旧遍历快照继续执行。三项新增真实SQLite验收覆盖正常通知、显式撤回及关闭句柄，并确认数据已提交、后续修订正常。已进入回调不可撤销，不新增跨进程通知或回滚提交。


CLI重复取消收尾补充：整组插件/任务/MCP/数据库清理在原finish_on_cancel中执行，调用者首次或再次取消不会截断某个已开始的清理；清理实际结束后传播取消。两项新增真实CLI/SQLite验收在受控装配失败后，分别阻塞原任务清理和数据库关闭，重复取消调用者，确认其等待及原任务/数据库清理确实完成。单清理失败仍沿AsyncExitStack继续其余资源，不提供强制终止不合作清理函数。


沙箱政策读取失效补充：政策resolve/set在原会话读取前后复核同一session_data、working_directory宿主及原启动代。等待期间宿主替换返回sandbox/host-changed，撤回启动代返回service/scope-closed，不返回旧策略、不继续向旧存储派发政策修改。六项新增真实SQLite验收覆盖两种操作和三种失效，确认原记录/修订不变及租约释放。已派发写入保留原finish_on_cancel提交收尾，不新增跨绑定检查与SQLite提交的原子保证；未改变沙箱执行策略或审批。


子代理模型策略绑定补充：read/set/select在原父会话读取前后复核同一session_data宿主及启动代。等待期间替换宿主返回subagent-model/host-changed，撤回启动代返回service/scope-closed，不发布旧策略、不继续选模或向旧存储派发修改。六项新增真实SQLite/模型目录验收覆盖三操作与两失效，确认原记录/修订不变及租约释放。已派发写入沿原finish_on_cancel提交收尾，不新增原子绑定/提交保证或全局模型ACL。

`context.session_projections.get/events`返回前再次通过原只读会话核验可见性与绑定项目；等待期间隐藏或迁移时不发布旧摘要/事件。5项新增验收覆盖两种接口、隐藏/迁移及真实Remote；不是原子授权快照。
