# 对话样式块

Sunday 桌面对话支持辅助说明、折叠详情、可编辑成稿和隔离的交互页面。模型提示词已包含格式说明；可直接说“用说明块解释”“写成可以编辑复制的成稿”“给我一个可以调节参数的计算器”。

## 本轮参考的官方能力

| 官方能力 | Sunday 的对应方式 |
| --- | --- |
| 文本、卡片、列表 | Markdown、说明块、提示块、警告块、成功块 |
| 折叠辅助内容 | 原生详情块，支持键盘展开收起 |
| 可复用成稿 | 成稿块，支持本地编辑、预览和复制 |
| 图表、计算器、模拟器、可交互说明 | `interactive-html`，在独立隔离文档中运行 |
| 表单和按钮 | 支持交互块内的本地输入、计算、筛选和切换 |
| 按钮触发服务端操作 | 本轮没有接通；展示块不获得工具调用、发送或保存权限 |
| 静态关系图、表格、数学公式 | 沿用已有 Mermaid、Markdown 表格及公式能力 |

参考：

- [官方 Visualizations 文档](https://learn.chatgpt.com/docs/visualizations)
- [官方 ChatKit 组件与操作文档](https://developers.openai.com/api/docs/guides/custom-chatkit#add-inline-interactive-widgets)

本轮复用 Sunday 现有消息架构，不引入 ChatKit 或限定模型供应商。官方的服务端操作属于明确注册的动作协议，不等于任意 HTML 可以直接执行主程序操作。

## 辅助说明

```text
:::note 说明
支持 **Markdown**、列表和链接。
:::

:::tip 建议
优先使用简单直观的说明。
:::

:::warning 注意
这里写需要用户留意的事项。
:::

:::details 展开依据
可以放较长的推导或补充材料。
:::
```

其他类型：`info`、`danger`、`success`。标题可省略，界面显示对应语言的默认标签。支持嵌套说明块，代码围栏中的示例不作为样式块处理。未闭合的块保持可读文本。

兼容 GitHub 警示引用：

```markdown
> [!NOTE]
> 辅助说明。

> [!WARNING]
> 需要注意的事项。
```

还支持 `[!TIP]`、`[!IMPORTANT]`、`[!CAUTION]`。

## 成稿

```text
:::writing{variant="document" title="项目说明"}
可复用的 **正文**。
:::

:::writing{variant="email" subject="进展同步"}
邮件正文。
:::
```

可选类型：`standard`、`document`、`email`、`chat_message`、`social_post`。兼容成稿语法中的 `id`、`recipient` 等属性；本轮仅展示标题与正文，不发送邮件。编辑只作用于当前展示实例，离开或重新渲染会恢复消息原稿，复制取得当前修改后的文字。它不修改历史消息或后台文件。

## 交互页面

````text
```interactive-html
<label for="quantity">数量</label>
<input id="quantity" type="range" min="1" max="100" value="10">
<output id="result">100</output>
<script>
const quantity = document.getElementById('quantity');
quantity.addEventListener('input', () => {
  document.getElementById('result').textContent = String(Number(quantity.value) * 10);
});
</script>
```
````

交互块必须闭合，并在回复生成完毕后启动。普通 `html` 围栏只显示代码；原始 HTML 不能伪造内部交互挂载标记。源码限制为 262144 个 UTF-16 字符，展示高度为 160–800px，超出部分在隔离页内滚动。

源码保存在原回复中，重访时重新运行。输入与计算是当前页面内的临时状态，不写入聊天历史或磁盘。命令行得到同一块的可读源码，不尝试运行界面。

可用主题变量：`--background`、`--foreground`、`--control`、`--control-text`、`--border`。主题从当前工作区继承并随工作区颜色更新。使用原生且有标签的控件，动画遵循减少动态效果偏好。

运行文档由固定的本地后台路由提供，内容通过消息传入，避免把源码或凭据放入地址。访问检查照常执行。默认本机桌面模式可用；需要每次请求携带 Bearer 的 LAN 模式不能直接载入此 iframe，当前会进入失败提示，不开放免鉴权例外。

隔离页只开放脚本，禁止同源权限、存储、后台接口请求、外部资源加载、子页面、表单提交与弹窗；不提供主程序操作桥。主窗口继续禁止内联脚本。加载或脚本失败提供源码和重试入口。生成的计算结果与算法仍需按任务核对。

## 验收

仅执行本轮新增测试：

```powershell
cd E:\LamTools\core\ui
npx vitest run tests/inline-visualization.test.ts tests/message-style-blocks.test.ts
node tests/message-style-blocks.browser.mjs
npx vue-tsc --noEmit --pretty false

cd E:\LamTools\core
python -m pytest tests/test_inline_visualization.py -q
```

浏览器代码验收覆盖真实按钮与滑块操作、隔离、网络限制、主题继承和切换、成稿编辑、详情展开、生成状态转换、运行错误兜底与清理。该验收不使用 Computer Use。
