# 模型、流式与附件调用链审计

基线：2026-09-23 当前工作树；Android standalone 的 TypeScript → Tauri → Rust，与桌面 Python Core 的请求装配比较。paired remote 使用桌面宿主，不能套用本页 standalone 结论。代码审计与本地模拟服务测试，不调用用户供应商、不读取或输出密钥。

## M1 · P1：附件返回成功，但内容没有保存，也没有进入模型

- `core/mobile/src/standalone/StandaloneTransport.ts:435-445` 对 multipart 上传只生成元数据并返回 201，没有存储 `request.body`；大小及类型还取自整个 multipart 请求。
- 同文件 `:1498-1506` 的 `inputContent` 只将附件变为 `[附件: filename]`。`core/mobile/src/native/rustAgent.ts:9-13` 和 `core/runtime-rs/src/lib.rs:103-127` 的用户消息也只有字符串内容。
- 对照桌面 `core/src/lamtools_core/app/http_agent_app.py:751-778` 调用 attachment store 保存 bytes；`core/src/lamtools_core/app/base_agent.py:797-801` 及 `llm/profiles.py:1135-1156,1905-1932` 支持图像内容块。
- 触发：上传一张只有图片中含答案的图片，发送“读出图片中的文字”。界面可显示上传成功，而模型只有文件名，重启也无法通过该 ID 取回附件。
- 需要修复整个链路：持久化真实文件、正确 MIME/大小、预览/下载、提取文本或多模态块、历史回放和删除。只隐藏附件按钮不满足能力对等要求。

## M2 · P2：只有 OpenAI Chat 协议有实时增量输出

- `core/runtime-rs/src/provider.rs:733-735` 仅在 `OpenAiChat` 且存在 stream 回调时设置 `stream=true`。
- Responses body 在 `:968` 明确 `stream:false`；Gemini URL 在 `:341` 使用 `generateContent`；Anthropic 构造和解析也没有对应 SSE 增量状态机。
- `:447-455` 对 `stream=true` 统一使用 `read_openai_stream`，因此通过 extra 强行打开其他协议的 stream 也不是修复，不能正确解释其事件格式。
- 桌面 `core/src/lamtools_core/cli.py:392-438,448-498` 按协议组装 streaming 请求，并分别转换 Anthropic、Gemini、Responses 事件。
- 触发：相同模型改走 Responses/Anthropic/Gemini native adapter。移动端等待完整响应才展示结果；OpenAI Chat 路径通过 SSE 测试，不能泛称移动端完全不流式。
- 应为各协议接入增量解析、推理/工具参数聚合、结束和截断处理、重试 reset；不应靠打字动画模拟流式。

## M3 · P2：重试配置与流式空闲超时未接到本机运行时

- `HttpModelBackend::new` 在 `core/runtime-rs/src/provider.rs:244-246` 固定使用 `RetryPolicy::default()`；原生构造点 `core/mobile/src-tauri/src/lib.rs:583,786,1352` 都调用它。
- `core/mobile/src/native/rustAgent.ts:97-210` 没有重试策略参数；`StandaloneConfigStore` 的 settings 通用存储不会自动改变 Rust policy。
- Rust policy `provider.rs:163-184` 包含总超时/尝试次数/间隔/空响应重试，**没有流式 idle timeout 字段**；`:536` 直接等待 response.chunk，依赖整个请求的总 timeout。
- 桌面 `config/retry_store.py:133-162` 读取 `model_retry.jsonc`，`app/default_agent.py:191-216` 装配，`kernel/loop.py:2095` 使用流式空闲超时。
- 影响：桌面已配置的重试、延迟和空闲时限不能在本机端等价生效；流中断后等待行为不同。Rust 已有连接 15 秒、响应头 120 秒和整个请求总超时，不能误报为当前代码完全没有超时。

## M4 · P2：模型备注编辑后被丢弃，也未进入模型提示词

- 共享设置 `core/ui/src/components/CoreSettings.vue:965,2044,2075` 允许编辑并提交 `notes`。
- `core/mobile/src/standalone/StandaloneConfigStore.ts:17-29,323-345` 的模型结构和 upsert 不读取 `params.notes`；新填写的备注不会保存。
- `core/mobile/src/native/rustAgent.ts:270-289` 和 `core/runtime-rs/src/provider.rs:140-156` 的 provider payload 没有 notes 注入。
- 桌面 `core/src/lamtools_core/cli.py:195-223,502` 将模型备注加入请求系统上下文。
- 触发：在模型备注填入唯一指令/用途，保存并重新打开；移动端丢失新备注，请求也不会包含它。这属于配置丢失，不是 Android 限制。

## 已检查且不能误报为缺失的部分

- 当前 Rust HTTP 客户端使用 rustls，源码没有关闭证书验证；HTTP 4xx 致命错误、5xx/429 重试、响应头等待提示、连接失败分类和取消 send task 均有实现。
- OpenAI SSE 支持跨网络分片 UTF-8、工具参数聚合、重试清除临时输出，拒绝 `[DONE]` 之前的 EOF 及 length 截断工具调用。
- 多协议非流式请求体、工具 schema、模型推理状态回放与运行时模型身份已有实现，不能从 streaming 缺失推出其他协议完全不能调用。
- 上述连接逻辑通过本地模拟服务测试；没有重新验证真实 Command Code 账号、Android TLS 链或真机逐字输出，不宣称供应商端验收完成。

## 本轮代码验证

- `npm test`（`core/mobile`）：29 文件，175 测试通过。
- `cargo test --manifest-path core/runtime-rs/Cargo.toml`：80 单元 + 50 集成测试通过，共 130。
- `cargo test --manifest-path core/mobile/src-tauri/Cargo.toml --lib`：18 测试通过，包含脚本模型加载 Study skill/reference 并建图、读取回执。
- mobile `vue-tsc --noEmit` 通过（本轮恢复并读取此前运行结果，退出码 0）。
- 测试通过表示既有断言通过，不代表已经覆盖上述缺失链路；本轮审计发现仍为未修复项。
