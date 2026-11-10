# 调用台（API 直接调用）

不进 Agent Loop，选一个模型、给输入、拿结果。产物可以存进资料库，历史按次保留。

## 入口

- 桌面：最左竖栏「调用台」。
- 命令行：`lamtools direct catalog | run | list | retry | import-imagegen`。

## 复用了什么

| 能力 | 复用位置 |
| --- | --- |
| 供应商与模型配置 | `config/provider_store.py`、`config/model_store.py` |
| 文本调用、流式、错误分类 | `llm/http_client.py` 的 `CoreHttpLLMClient` |
| 适配档案与请求组装 | `llm/profiles.py`、`cli_commands/config.py` |
| 参考图下载与上传 | `tool/image_tools.py` 已验证的实现 |
| 产物与资料库 | `artifact/store.py` 的 `register` |
| RPC 宿主 | `app/http_agent_app.py` 的 `OperationCatalog` |

新增的只有现有代码没有的事：直调任务编排、历史落盘、媒体结果落成文件。

## 模型定义里的输出类型

模型 jsonc 新增可选字段 `output_type`：

```jsonc
{
  "model_id": "gpt-image-1",
  "output_type": "image"   // text | image | video | audio，缺省 text
}
```

`capability` 仍然表示输入模态（能不能看图）；`output_type` 表示能产出什么。设置 → 模型与供应商的编辑表单里可以改，模型卡片上会显示 图 / 影 / 音 标记。

## RPC

| 方法 | 作用 |
| --- | --- |
| `direct.catalog` | 可用模型（只含启用），带输出类型、供应商与生图工具状态 |
| `direct.run` | 发起一次调用，立即返回 `call`，后台执行 |
| `direct.get` | 查一次调用（界面轮询它） |
| `direct.list` | 历史，支持 `limit` / `offset` / `output_type` / `status` |
| `direct.retry` | 只重跑某一次调用里的第 `index` 条 |
| `direct.cancel` | 取消 |
| `direct.delete` | 删除记录 |
| `direct.save` | 把结果登记为资料库资产 |
| `direct.import_imagegen` | 把生图工具的配置导入成一条图片模型 |

`direct.run` 参数：`model_ref`、`prompts`（每行一条，最多 50）、`system`、`params`、`project_id`。

`params` 按输出类型取用：

- 文本：`temperature`、`max_tokens`、`thinking`、`non_stream`
- 图片：`size`、`n`、`quality`、`reference_urls`（参考图，最多 4 张）
- 视频：`seconds`、`aspect_ratio`、`poll_url`、`poll_attempts`、`poll_interval`
- 音频：`voice`、`format`
- 通用：`request_body`（合并进请求体）

## 执行路径

- 文本：默认走 `CoreHttpLLMClient.stream`，边生成边把增量写进记录，界面轮询就能看到字在长；供应商不支持流式时自动回退一次完整请求。
- 图片：`POST {base_url}/images/generations`；带参考图时走 `POST {base_url}/images/edits`（multipart）。
- 视频：`POST {base_url}/videos/generations`；返回任务 id 时轮询 `params.poll_url`、`/videos/generations/{id}` 或 `/tasks/{id}`。
- 音频：`POST {base_url}/audio/speech`。

媒体接口按 OpenAI 兼容格式解析 `data` / `output` 里的 `b64_json` 或 `url`。错误会区分鉴权失败、限流、供应商不可用与超时。

## 界面能力

- 模型按输出类型分组，缺密钥会标出来并禁止运行。
- 每行一条输入，批量执行；运行中显示第几条，支持取消。
- 失败或取消的单条可以重试，不影响其余结果。
- 参数按模型记忆，下次选中同一模型恢复上次那套。
- `Ctrl/Cmd + Enter` 运行。
- 历史按输出类型筛选，支持加载更多、点开回填参数、删除。
- 结果文本可复制，图片/视频/音频可预览与下载，可一键保存到当前项目资料库。
- 配了模型价格时显示这一次的费用。

## 生图工具与调用台

生图工具仍读 `imagegen.jsonc`；调用台读模型库。为了避免两套配置各配一遍，调用台在生图工具已配置且没有图片模型时提供「导入生图模型」，会创建或复用供应商，并建一条 `output_type=image` 的模型。导入是单向的，不改生图工具本身。

## 数据位置

- 历史：`{data_dir}/direct_calls/<call_id>.json`。
- 产物：`{work_root}/.lam/artifacts/direct-calls/<call_id>/`；无项目时落在 `{data_dir}/direct_calls/files/`。
- 应用重启时，未完成的记录会被标成「应用重启，任务已中断」。

## 测试

- `core/tests/test_direct_call_service.py`：执行、批量、取消、历史、保存。
- `core/tests/test_direct_call_advanced.py`：流式、回退、视频轮询、参考图、错误提示。
- `core/tests/test_direct_call_history.py`：分页、重跑、费用、生图导入。
- `core/tests/test_direct_call_operations.py`：RPC 契约。
- `core/tests/test_direct_cli.py`：命令行入口。
- `core/tests/test_model_output_type.py`：模型输出类型的读写与 RPC。
- `core/ui/tests/direct-call.test.ts`：页面交互、筛选、重试、导入、参数记忆。
