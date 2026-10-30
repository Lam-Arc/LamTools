# 插件模型目录与场景选择 v1

实际调用扩展：context.llm.complete/stream/estimate 见 [第二阶段运行能力](plugin_phase2_runtime.md#实际模型调用与结构化流)；context.models 本身仍是只读目录与选择门面。

<!-- user:“宿主能力补齐和接口完善与文档更新，自动化兼容脚本，脚本不必能处理所有问题，剩下问题交给 agent 来移植”+(模型查询保留项目和场景边界，错误明确，不能以目录查询冒充模型调用兼容)。 -->

Sunday 桌面进程内 Python 插件在受管 `start/on_load` 中通过 `context.models` 查询模型目录、精确解析引用，或只读查询某个场景应使用的模型。该接口复用原 ModelStore 和场景选择器，不请求外部模型，不修改配置或场景记忆。

## 使用

```python
class Runtime:
    def start(self, context):
        self.models = context.models
        self.catalog = self.models.list()

    def choose_background_model(self):
        choice = self.models.select("background")
        # choice.model.id 是路由使用的模型记录 ID。
        # choice.notice 非空时，调用方应展示同场景模型替换提示。
        return choice

def create_plugin(context):
    return Runtime()
```

宿主在插件启动前提供 model_catalog。新门面捕获当前插件启动代和 `context.work_root`，之后读取当前配置，但不会因共享旧目录的 `set_work_root()` 而切换项目。需要另一个项目时，先取得相应 context，再重新获取 `.models`；已持有的门面保留原项目。停用或重启后旧门面拒绝调用，新启动代需要重新取得门面。

接口同步读取本地配置，没有异步 provider 或额外调用排空租约；它不建立会话，也不要求查询者已有运行中的模型请求。

## 方法

| 方法 | 结果 |
| --- | --- |
| `list()` | 当前项目可见的 `list[ModelDescriptor]`；沿用项目、用户与内置配置的合并规则 |
| `resolve(ref)` | 一个精确匹配的 `ModelDescriptor`；不存在、模糊或歧义时明确报错 |
| `select(scene, *, ref=None)` | `ModelSelection`；显式引用优先，否则只解析该场景的已有模型记忆 |

`scene` 必须为 `chat`、`study` 或 `background`。不省略场景，不把主对话的最近模型当作后台默认。`ref=None` 才表示按场景记忆选择；其他引用必须是非空字符串。

### 模型描述

冻结的 `ModelDescriptor` 包含：

| 字段 | 含义 |
| --- | --- |
| `id` | 配置记录 ID，标识具体提供方路由；传给 Sunday 子助手等接收记录引用的入口 |
| `model_id` | 提供方持有的模型名称，可以在不同路由间重复 |
| `display_name` | 展示名称，可以重复 |
| `provider_id/provider` | 关联提供方的记录 ID 与名称 |
| `capability` | Sunday 当前的粗粒度文本/多模态能力 |
| `context_window/max_output_tokens` | 本地记录配置的容量；0 表示未提供，不代表模型没有容量 |

`to_dict()` 只返回上述字段，使用 snake_case。不会返回 API key、请求 headers/body、连接地址或本地源文件路径。该描述不包含 DSH 的 reasoning efforts、inputModalities、systemPromptUpdate 或适配器默认控制项。

解析首先匹配记录 `id`；没有该记录时，只接受唯一匹配的完整 `model_id` 或不区分大小写的完整 display_name。不使用子串猜测；同名对应多个记录时，必须改用准确的记录 ID。目录读取成功但为空返回 `[]`，读取失败会抛错，不能把失败当作已确认不存在。

### 选择结果

冻结的 `ModelSelection` 包含 `scene`、`model`、`replaced_from` 和 `notice`。没有显式 ref 时复用 `resolve_scene_model(scene, work_root=...)`：只在同场景记忆中寻找可用项；首选失效而下一项可用时，结果保留原记录 ID 和替换提示。调用方负责处理提示，接口本身不写入、不弹通知、不记忆本次选择。

显式 ref 不可用时直接失败，不替换为其他提供方或其他场景。选择检查仅验证当前本地模型和提供方关联及端点格式；不联网检测端点可达性、账号额度或凭据有效性。

目录成员资格不是子助手路由授权，选择结果也不是模型执行许可证。把结果交给实际会话/子助手入口后，仍由其运行档、预设、权限及请求构建规则决定最终行为；该查询没有覆盖或绕过这些规则。

## 错误

`ModelAccessError` 从公开 SDK 导出，稳定的 `code` 包括：

| code | 含义 |
| --- | --- |
| `model/invalid-ref` | 引用不是非空字符串 |
| `model/not-found` | 当前目录中没有对应记录，或选择后记录已被撤回 |
| `model/ambiguous` | 完整别名对应多个记录 |
| `model/invalid-scene` | 场景不受支持 |
| `model/no-selection` | 该场景没有可用的已记忆模型 |
| `model/unavailable` | 显式选择的提供方不存在或端点格式无效 |
| `model/store-error` | 配置或选择读取失败；对外错误文字不转发底层异常载荷 |
| `model/invalid-record` | 描述字段无法构成有效元数据 |

已停止的插件门面沿用受管服务的 scope-closed 错误。接口返回独立不可变值，但这些值只是查询时的事实：稍后配置可以改变，没有 DSH prepareCall 捕获适配器代次的分派保证；已返回描述和旧对象不会自动作废。

## DSH 对应和未覆盖项

上游固定为 `f3803c96974ad4a94195fb97e5c637e9c2a3afe3`：
[LLM 作者说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/llm/llm/README.zh.md)、[默认模型说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/core/agent-default-model/README.zh.md)、[子助手选模说明](https://github.com/deepseek-ai/deepseek-harness/blob/f3803c96974ad4a94195fb97e5c637e9c2a3afe3/packages/subagent/tool-subagent/README.zh.md)。

| DSH 入口 | Sunday 对应或差异 |
| --- | --- |
| `llm.listModels` | `context.models.list`，仅本地配置目录，不是适配器在线发现 |
| `llm.resolveModelInfo` | `context.models.resolve`，必须先适配 provider/model 与记录 ID，能力字段也不完全相同 |
| `agentDefaultModel.currentSelection` | `context.models.select(scene)` 近似查询；Sunday 按场景分离，没有相同的单一进程默认规则 |
| `agentDefaultModel.saveSelection` | 本批无对应写入接口 |
| 子助手获准路由目录和会话持久政策 | 本批未实现 DSH 等价规则，不能拿全部模型目录代替 |
| `llm.stream/prepareCall/registerAdapter/listProviders` | 本批未实现；不生成空代理或假流 |
| 模型更新事件、适配器代次与取消/终止分片 | 本批未实现 |

旧 `context.service("model_catalog")` 的 list/resolve/default 等方法保留原兼容行为，包含旧的默认字段与宽松查询；不应据此推导新的场景选择规则。DSH 移植优先使用本门面并记录差异。

迁移报告新增 `modelMethods`，只为已核对的目录/查询方法提供 `agent-required` 建议。流式调用、配置写入和子助手策略仍逐项留给 agent；不会自动把提供方模型名当作唯一记录 ID。

验收：`core/tests/test_plugin_model_access.py`。覆盖记录/上游 ID 区分、唯一精确别名、项目视图隔离、真实 ModelStore 项目覆盖、停用代际、同场景替换、无跨场景回退、显式选择不写入、读取错误、元数据字段，以及真实桌面启动和本地脚本子助手请求。
