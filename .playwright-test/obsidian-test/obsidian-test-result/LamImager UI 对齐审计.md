# LamImager UI 对齐审计

> 状态：✅ 有效 | 来源：lamwriter-ui-alignment-audit.md
>
> 2026-06-02 核查。LamImager 使用 LamWriter 同一套前端骨架、基础样式、页面入口和交互心智。

## 对齐结论

### 已逐行一致

| 文件 | 结论 |
|---|---|
| `main.ts` | 完全一致 |
| `App.vue` | 完全一致 |
| `router/index.ts` | 完全一致（`/` 和 `/settings`） |
| `variables.css` | 完全一致 |
| `base.css` | 完全一致 |
| `components.css` | 逐字一致（4391 行） |
| `UiSelect.vue` | 完全一致 |

### 保留差异（业务层）

| 差异 | 原因 |
|---|---|
| 会话列表 vs 项目分组 | Imager 没有 Writer 的项目根目录模型 |
| 谱系图 vs Git 图 | Artist 核心资产是图片谱系，不是代码仓库 |
| 参考图上传 vs 文件附件 | 上传对象不同 |
| 图片详情浮层 vs diff 审核 | 核心操作不同 |

### 骨架标记复核

| 标记 | LamImager | LamWriter | 结论 |
|---|---|---|---|
| `writer-shell` | 1 | 1 | ✅ |
| `writer-drawer` | 2 | 2 | ✅ |
| `writer-main` | 1 | 1 | ✅ |
| `thread-header` | 1 | 1 | ✅ |
| `floating-composer` | 1 | 1 | ✅ |

## 工程外壳

| 项目 | LamWriter | LamImager | 结论 |
|---|---|---|---|
| dev 端口 | 6174 | 5174 | 显式固定端口，地址保留 |
| API 代理 | VITE_API_TARGET | VITE_API_TARGET | 已对齐可配置 |
| build 质量门 | 类型检查 + Vite | `vue-tsc --noEmit && vite build` | 已对齐 |

## 关联

- 项目概览 → [[LamImager 项目概览]]
- 架构设计 → [[LamImager 架构设计]]
