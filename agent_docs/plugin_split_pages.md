# 插件分屏页面

<!-- user:“支持一下”+(插件自绘界面可作为独立分屏页面打开，明确声明和生命周期约定)。 -->

用户可以在插件管理中点击“分屏打开”，或在分屏的“打开内容 → 插件页面”菜单选择页面。页面作为独立标签存在，可以移动到其他分屏，不切换主聊天模式。B 站插件的“B站卡片墙”是可运行示例：`plugins/bili-scroll/ui/wall-page.mjs`。

## 声明

在 `plugin.json` 中加入：

```json
{
  "name": "demo",
  "version": "1.0.0",
  "ui": {
    "pages": [
      { "id": "wall", "title": "卡片墙", "entry": "./ui/wall.mjs", "order": 50 }
    ]
  }
}
```

`id` 在同一插件内唯一；不同插件可使用相同 ID。`order` 为整数，默认 50。入口必须是插件目录内已有的 `.js` 或 `.mjs` 文件，路径以 `./` 开头。Vue、TypeScript 等源码需要先构建成浏览器可执行的 ES 模块；宿主不编译入口源码。

`ui.pages` 用于分屏标签，`ui.modes` 用于主界面模式，`ui.windows` 用于独立桌面窗口，三者分别声明。

## 页面入口

入口提供命名导出 `mount(root, context)`。可以同步或异步返回清理函数：

```js
export function mount(root, context) {
  const button = document.createElement('button');
  button.textContent = '读取状态';
  const output = document.createElement('p');
  root.append(button, output);

  async function refresh() {
    try {
      const result = await context.rpc('demo.status', {});
      if (!context.signal.aborted) output.textContent = JSON.stringify(result);
    } catch (error) {
      if (!context.signal.aborted) output.textContent = String(error);
    }
  }
  button.addEventListener('click', refresh);
  return () => button.removeEventListener('click', refresh);
}
```

每个标签拥有自己的 `root` 和上下文。模块可能被多个标签共享，模块顶层应保持无副作用；DOM、计时器、监听和可变页面状态放在 `mount` 内。只在传入的 `root` 内绘制，样式优先使用宿主主题变量和插件自己的类名前缀。

## 上下文

| 字段或方法 | 约定 |
| --- | --- |
| `instanceId` | 当前标签实例 ID |
| `workRoot`、`projectId`、`sessionId` | 打开时捕获的工作目录、项目及可选会话；后续切换主项目不会改变它们 |
| `rpc(method, params)` | 调用宿主操作；宿主写入当前实例的工作目录和项目字段，关闭后拒绝调用及返回结果 |
| `signal` | 关闭、禁用或更换页面实例时触发中止；插件可用于取消自己的请求及后台工作 |
| `visible` | 当前标签是否可见，只读 |
| `onVisibilityChange(callback)` | 订阅可见性变化，返回取消订阅函数；首次状态读取 `visible` |
| `openPage(pageId)` | 请求打开同一插件已经声明的另一个页面 |

隐藏标签保留实例。插件应通过可见性通知暂停轮询和动画，恢复可见时按需刷新。宿主不会自动取消已发出的 RPC；插件必须检查 `signal.aborted`，避免在关闭后继续更新页面。

## 清理与恢复

关闭或禁用时，宿主中止 `signal`、移除实例 DOM 并调用清理函数。异步 `mount` 在关闭后才返回清理函数时，该函数也会执行一次。插件仍须自行清理计时器、全局监听、订阅和其他资源；若初始化可能失败，应在失败前自行释放已经创建的资源。

布局只保存插件名、页面 ID 和项目上下文，恢复时从当前启用插件目录解析入口。插件被禁用、移除或连接未就绪时显示可恢复的提示，重新启用后可以恢复挂载。入口模块地址包含插件版本；更新入口时应同时更新插件版本。刷新按钮重新挂载实例，不保证清除浏览器对同版本模块的缓存。

## 文件类型接驳

<!-- user:“该修就修，不用停下”+(插件声明可打开的文件类型，文件树传入文件并保持每个标签独立)。 -->

页面声明可添加 `"fileExtensions": [".excalidraw.md", ".excalidraw"]`。宿主只接受不含路径的唯一后缀，文件树选择文件时先加载插件声明，再按最长后缀匹配；同长度存在多个处理器时不自动选择插件。页面上下文的 `filePath` 是打开时绑定的工作区文件路径；同一插件的不同文件具有独立标签，恢复布局时保留文件和项目身份。插件仍需通过宿主操作读取、保存文件，并处理关闭、外部修改与草稿恢复。

<!-- user:“该修就修，不用停下”+(原版画图链接可在同一个项目中打开文件)。 -->
`context.openFile(path)` 请求在当前页面绑定的项目中打开文件；宿主优先使用已声明的文件类型处理器，其他文件进入文本编辑器。插件页面关闭后该方法不再触发导航。插件应先在后台解析和限制目标路径，文件读取仍由各自的工作区范围约束。
