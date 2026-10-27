# bili-scroll（刷B站）2.3.0 · LamTools

基于 [dsh-bili-scroll 2.2.2](https://github.com/c1overzz/dsh-bili-scroll/tree/4af98392ee078e02f50a7fd0bf0491033f4675ed)，固定提交 `4af98392ee078e02f50a7fd0bf0491033f4675ed`。保留原版 bilibili-mcp 服务器与 34 个工具；直接复用原版 React 前端、CSS 和组件；仅注册、API 请求、主题变量与生命周期由适配层接入宿主。Python 调度和宿主业务保留现有移植实现。

## 使用

1. 从插件页安装 ZIP，打开「刷B站」。本插件需要本次重建后的宿主，旧发行版不保证兼容。
2. 在「高级」安装主依赖，然后在页面生成二维码并用 B站手机端确认登录。
3. 在「偏好」「互动」设置关键词、限额、收件人及评论/私信开关，再运行一轮。自动评论、回复和投递由配置硬闸限制。
4. 需要无字幕视频转写时安装 ASR 依赖，选择模型；首次使用需要下载模型。

页面保留日常、偏好、互动、高级四页签，提供视频墙筛选/分页、日报、单视频笔记、停止轮次和诊断。区域、分屏页面和独立窗口共享原版设置页；额外的「刷过的视频」页面直接使用原版会话视频墙组件。

## 运行与数据

- 宿主将数据保存在独立 `plugin-data/bili-scroll/`，插件的 `data/` 指向它。凭证、日志、venv、章程、日报和判重表都在此处；升级与默认卸载保留数据。
- `mcp/mcp.json` 使用宿主通用 `{{PLUGIN_DIR}}`、`{{PLUGIN_PYTHON:./data/duty/.venv}}` 模板。安装依赖不再写入机器绝对路径；也可配置 `pythonPath`。
- 值班轮由 `bili-scroll:duty` 子代理运行档驱动，只开放 `mcp` 及指定工具；没有任意命令或文件系统工具。
- 调度、私信监听、轮后收藏、90 秒评论复核均由可取消的后台任务执行。配置修改的章程不会被升级覆盖，新章程写入 `.new`。
- 后端、操作和 MCP 可随启停/更新清理重建；涉及模块覆盖和全局脚本时按宿主提示重启应用。

## 代码

`common.py` 管数据与章程，`service.py` 管业务，`backend/` 管调度，`ops.py` / `tools.py` 提供宿主入口，`scripts/` 管依赖、扫码和 MCP 执行闸，`ui/page.mjs` 是原版前端与 React 的静态打包，`ui/src/original-adapter.mjs` 为宿主适配层。`vendor/` 保留上游服务器、ASR 和原收藏实现；当前收藏通过 `scripts/favops.py` 适配实际依赖的公开接口。旧 `server/`、`bili_core.py`、`ui/board.js` 不属于当前安装包入口。

## 验证与许可

真实登录后验证了搜索、视频信息、字幕、评论、封面和画面帧；真实语音及 B站音频转写通过。真实子代理与 MCP 进程使用受控模型完成日报/判重验收；用户追加授权后，已在原版演示视频完成公开评论、向作者发送一条验证私信、收藏到默认收藏夹，并分别回读确认。自动调度和额度分支仍以受控测试为证。详细差异见 [差异表](差异表.md)，宿主与验收报告见仓库 `agent_docs/plugin_host_rebuild*.md`。

本体 MIT（`LICENSE`，c1overzz）；内置 bilibili-mcp MIT（`vendor/bilibili-mcp/LICENSE`，AGI_Ananas）。署名见 `NOTICE.md`。


## 原版界面构建

`vendor/dsh-client.js` 与固定上游逐字节一致，保留原 CSS、开关、四页签、扫码、收藏夹选择及视频墙交互。构建时静态包装原版自注册入口，不使用 eval。适配层把原版 HTTP 请求映射到现有宿主操作，封面仍由宿主代理读取。

构建依赖只放 `.build/plugin-rebuild/ui-build/`：先执行 `npm install --prefix .build/plugin-rebuild/ui-build --no-audit --no-fund react@18.3.1 react-dom@18.3.1 esbuild@0.25.11`，再在仓库根执行 `node scripts/build-bili-scroll-ui.mjs`。安装包内已经包含产物，用户无需执行这些构建命令。
