# bili-scroll（LamTools 插件）

每天替你刷一轮 B站：按关键词搜最近几天的视频、逐条读字幕与评论判断、写一份
`data/out/<日期>.md` 日报；特别值得且显式开启自动评论时，经确认发一条评论。

## 行为复刻自

[dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll)（MIT License,
Copyright (c) 2026 c1overzz）。按 MIT 允许，本插件是对其**行为的重实现**，
未复制其代码：值班章程、能力面与红线按 LamTools 的清单/工具/操作/配置
机制重新表达，内置的 bilibili-mcp Python 服务以宿主原生工具（httpx 公开
Web API）替代。

## 使用

- 设置 → 插件 → bili-scroll：填关键词、限额；要读 AI 字幕/发评论需填
  浏览器 Cookie 里的 SESSDATA 与 bili_jct（明文存本机 data/，介意则不填）。
- 对话里说「刷一轮B站」或输入 `/bili-duty`，值班章程（技能 bili-duty）
  会接管流程。
- 日报落在插件数据目录 `data/out/<日期>.md`。

## 与原版的差异

见交付时的差异表（对话记录）；要点：无内置 Python 运行时与 Whisper 转写、
峰谷自动刷交给宿主定时任务、扫码登录未复刻（Cookie 手动填）、收藏夹与
私信互动未复刻。
