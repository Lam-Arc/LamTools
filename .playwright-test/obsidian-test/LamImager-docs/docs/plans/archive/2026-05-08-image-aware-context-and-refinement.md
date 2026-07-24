# 图像感知上下文与迭代精修

> 设计日期：2026-05-08 | 状态：已审批

## 目标

解决两个共性问题：**LLM 看不到之前生成了什么图**，以及**用户没有便捷的精修入口**。将已生成图片提升为对话中的一等公民。

### 具体效果

1. **LLM 视觉上下文**：优化/规划时 LLM 能"看见"之前生成的图片
2. **一键精修**：图片消息上增加精修按钮，点击即进入精修模式
3. **图片标注**：参考图有清晰编号，LLM 能区分哪张图是哪张

---

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 上下文图片编码 | URL 直传 | multimodal content 的 `image_url` 原生支持，无需编解码 |
| 精修图片编码 | Base64 | 图生图 API 必须拿到图像数据，base64 自包含兼容性最好 |
| 精修交互 | 直接精修模式 | 点击→图片进入 strip→输入指令→发送，最流畅 |
| 上下文图片数量 | 用户主动选择 | 复用勾选框，避免意外 token 消耗 |
| 图片标注 | 标准化编号 `[图N]` | 替代 `[参考图片: xxx]` 标签，与 images 数组索引对应 |

---

## 数据流

### 上下文（改后）

```
前端 buildContextMessages():
  messages.slice(-10).map(m => ({
    role, content,
    image_urls: 用户勾选的图片 URL → 最多 6 张（可配置）
  }))
       │
       ▼
后端 handle_generate():
  如果 context_messages 含 image_urls
  → 构建 multimodal content:
    [{type:"text", text:"[User]: ..."}, ...,
     {type:"image_url", image_url:{url:"http://...", detail:"auto"}}]
  → 传给 LLM 做优化/规划
```

### 精修（新增）

```
用户点击图片消息上的 [精修(N)] 按钮
  → 取选中的图片 URL
  → 清空输入区 reference strip
  → 把选中图加入 strip，标注 "图N / 精修"
  → 输入框 placeholder → "基于参考图进行修改..."
  → 用户编辑指令后点 [精修发送]
  → fetchImageAsBase64 → reference_images
  → 后端 3 层回退 (chat_edit → edit → vision fallback)
```

---

## 前端改动

### 输入区（精修模式 vs 常态）

**常态**（不变）：
- 附件缩略图区（上传时显示，含 `×` 移除）
- textarea + negative prompt input
- 上传图片/文档按钮、数量选择、尺寸输入
- [助手] [发送]

**精修模式**（新增标签切换）：

```
✦ 精修模式                                              [× 退出]
┌──────┐ ┌──────┐ ┌──────┐       ┌──────────┐
│ 图1  │ │ 图2  │ │ 图3  │       │ + 上传   │  ← 参考图 strip
│[缩]  │ │[缩]  │ │[缩]  │       │ 追加图片  │
│ 精修 │ │ 上下文│ │ 上传 │       └──────────┘
│  ×   │ │  ×   │ │  ×   │
└──────┘ └──────┘ └──────┘

输入框 placeholder: "基于参考图进行修改..."
数量/尺寸控件不变
[助手] [精修发送]
```

变化：
1. 顶栏：`✦ 精修模式` + `[× 退出]`
2. 附件缩略图区 → 参考图 strip（标注来源，每张可 `×` 移除，可 `+ 上传` 追加）
3. 发送按钮文案 → `精修发送`
4. 布局、控件、尺寸顺序不动

### 图片消息区

```
已生成 4 张图片
┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐
│ 图1   │ │ 图2   │ │ 图3   │ │ 图4   │
│ [缩]  │ │ [缩]  │ │ [缩]  │ │ [缩]  │
│ ☑     │ │ ☐     │ │ ☐     │ │ ☐     │
└───────┘ └───────┘ └───────┘ └───────┘

[下载选中(1)] [全部下载] [对比选中] [精修(1)]
```

- 复用现有 `selectedImages` 勾选框
- 新增 **[精修(N)]** 按钮（N=选中数，0 时置灰）

### 精修按钮逻辑

```
点击 [精修(N)]：
  1. 取 selectedImages
  2. 切换到精修模式
  3. 图片加入 reference strip，标注 "图N / 精修 / 第N轮"
  4. 可选：原有上传图也保留在 strip 中（合并）
```

### 上下文图片纳入规则

每次 `sendGenerate()` / `精修发送` 时：

1. 精修模式 → 精修 strip 中的图自动作为 `image_urls` 进入上下文
2. 普通模式 + 用户勾选 → 勾选的图进入上下文
3. 都没选 → 不自动带入（避免意外 token 消耗）

---

## 后端改动

### Schema（`schemas/session.py`）

```python
class GenerateRequest(BaseModel):
    # ... 现有字段不变 ...
    reference_images: list[str] = []          # base64（不变）
    reference_labels: list[dict] = []         # 新增
    #   [{index: 1, source: "upload"|"context"|"refine", name: "photoA.png"}]
    context_messages: list[dict] = []         # 扩展
    #   [{role, content, image_urls?: [str]}]
```

### 上下文处理（`services/generate_service.py`）

`handle_generate()` 中，如果 `context_messages` 条目的 `image_urls` 非空：

```python
if any(msg.get("image_urls") for msg in data.context_messages):
    context_multimodal = _build_multimodal_context(data.context_messages)
    # 传给优化/规划 LLM 时使用 multimodal content
```

新增辅助函数 `_build_multimodal_context()`：将文本+图片 URL 组装为 OpenAI multimodal content 格式。

纯文本路径不变。

### chat_edit() 标注化（`utils/image_client.py`）

```python
# 改前：strip 掉所有 [参考图片: xxx]
clean_prompt = re.sub(r'\[参考图片:\s*[^\]]+\]\s*\n?', '', prompt).strip()

# 改后：标准化编号，LLM 可对号入座
# [图1] 对应 images[0], [图2] 对应 images[1] ...
image_labels = []
for i in range(len(images)):
    name = reference_labels[i]["name"] if reference_labels and i < len(reference_labels) else f"图片{i+1}"
    image_labels.append(f"  [图{i+1}]: {name}")

system_hint = (
    "你收到了以下参考图片，编号与图片顺序一一对应：\n"
    + "\n".join(image_labels)
    + f"\n\n请根据这些参考图片和以下指令生成新图片。\n\n指令: {prompt}"
)
```

LLM 收到的 multimodal content：
```
text:  "参考图片: [图1: photoA.png] [图2: photoB.png]\n用户指令: 把图1的角色放到图2右边"
image: photoA_base64   ← 图1
image: photoB_base64   ← 图2
```

编号与数组索引一一对应，LLM 可精确引用。

### 兼容性

| 场景 | 行为 |
|------|------|
| 旧版前端 | 新字段全部可选，纯文本上下文行为不变 |
| 没传 `image_urls` | 纯文本上下文 |
| 没传 `reference_labels` | chat_edit 用 `图片1, 图片2...` 编号 |
| 旧版前端使用精修 | 旧版没有精修按钮，完全不受影响 |

---

## 改动文件清单

### 前端

| 文件 | 改动 |
|------|------|
| `src/views/Sessions.vue` | 图片消息区加精修按钮；输入区加精修模式状态和参考图 strip；`sendGenerate()` 扩展 context_messages 逻辑；`executePlan()` 中 iterative 策略复用新机制 |
| `src/types/index.ts` | `GenerateRequest.context_messages` 扩展 `image_urls` 字段；`GenerateRequest` 增加 `reference_labels` |
| `src/stores/session.ts` | 可能需要新增精修模式状态（或放在 Sessions.vue 本地） |

### 后端

| 文件 | 改动 |
|------|------|
| `app/schemas/session.py` | `GenerateRequest` 加 `reference_labels`，`context_messages` 条目加 `image_urls` |
| `app/services/generate_service.py` | `handle_generate()` 中上下文处理支持 multimodal；新增 `_build_multimodal_context()` |
| `app/utils/image_client.py` | `chat_edit()` 接受 `reference_labels`，保留编号而非 strip 标签 |

---

## 不做的

- **不作默认自动带入上下文图片**：避免意外 token 消耗
- **不改变纯文生图流程**：无参考图时行为完全不变
- **不限制精修模式下的数量/尺寸控件**：和常态一样可调
