# 技术栈统一基准

更新时间：2026-06-20

## 运行时

| 范围 | 统一版本 | 判断 |
| --- | --- | --- |
| Python | 3.14.x，仓库入口使用 `.python-version` 的 `3.14` | 可靠：来自 Python 官方稳定下载页。用户提到的 `3.1.4` 不属于当前可用稳定线，按 3.14 处理。 |
| Node.js | 24.17.0 LTS | 可靠：来自 Node.js 官方首页的 Latest LTS。项目用于生产型桌面/前端构建，优先 LTS，不追 Current Release。 |
| npm | 11.17.0 | 可靠：来自 npm registry latest。 |

## 前端基准

| 依赖 | 统一版本 |
| --- | --- |
| Vue | `^3.5.38` |
| Vue Router | `^5.1.0` |
| Pinia | `^3.0.4` |
| @lucide/vue | `^1.21.0` |
| Vite | `^8.0.16` |
| @vitejs/plugin-vue | `^6.0.7` |
| TypeScript | `^6.0.3` |
| vue-tsc | `^3.3.5` |
| Playwright | `^1.61.0` |
| Electron | `^42.4.1` |
| Tauri API | `^2.11.0` |
| Tauri CLI | `^2.11.3` |

## 后端基准

后端依赖统一到 2026-06-20 通过 PyPI 查询到的稳定 latest 下限。Python 包继续使用 `>=`，因为当前仓库尚未引入统一锁文件。

## 债务

- 前端 package 分散在 root、core/ui、members/writer、members/artist、e2e 和模板中，尚未形成 npm workspace。短期已统一版本，长期建议改成 workspace 后集中升级。
- 后端依赖仍是 requirements + pyproject 混用，缺少统一锁定。短期已统一下限，长期建议引入 uv/lockfile。
- Vite 8、Vue Router 5、Pinia 3、Electron 42、Tauri 2 都是重大版本线，属于“可靠但需验证”的升级；必须以构建和桌面 smoke 为准。
- `lucide-vue-next` 已被 npm 标记废弃，已迁移到官方替代包 `@lucide/vue`。
