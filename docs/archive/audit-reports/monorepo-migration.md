# Monorepo 迁移记录

> 来源审计文档：`E:\LamTools\core\docs\plans\2026-06-04-monorepo-migration-audit.md`

## 现状摘要

三个独立仓库各自维护，共享依赖靠手动同步，无统一版本管理：

| 旧仓库名 | 提交数 | 远程（历史） |
|----------|--------|-------------|
| LamToolsCore | 33 | 无 |
| LamWriter | 82 | 无 |
| lamartist | 102 | github.com/Laaaaaaaam/lamartist |

> **注意：** 以下旧仓库路径仅为迁移历史记录，不再作为工作目录使用。所有开发在 `E:\LamTools` 进行。

## 迁移策略

采用 **壳仓 + git subtree** 方案：

1. 新建空壳仓 `E:\LamTools` 作为 monorepo 根（当前阶段已完成）
2. 用 `git subtree add` 将三个源仓库依次迁入，保留完整历史：
   - `LamToolsCore` → `core/`
   - `LamWriter` → `members/writer/`
   - `lamartist` → `members/artist/`
3. 迁入后对路径引用做全局修正（import 路径、tsconfig paths、构建输出等）
4. 验证构建通过

## 选择 subtree 的理由

- 保留完整提交历史，支持 bisect / blame
- 代码直接在仓内，无嵌套 `.git`，无指针漂移问题
- 无需 `--recursive` clone，CI 无额外复杂度

## 迁移进度

| 组件 | 目标路径 | 状态 | 提交哈希 | 迁移时间 |
|------|----------|------|----------|----------|
| LamToolsCore | `core/` | done | `d2874a0` | 2026-06-04 |
| LamWriter | `members/writer/` | done | `7c32b22` | 2026-06-04 |
| lamartist | `members/artist/` | done | `ab6ebb2` | 2026-06-04 |

## 当前状态

已完成：
- subtree 迁入（三个组件完整历史保留）
- 路径引用全局修正（import 路径、tsconfig paths、构建输出等）
- 构建验收通过
- 根目录脚本入口（`scripts/dev.ps1`、`scripts/build.ps1`、`scripts/test.ps1`）
- 新成员脚手架（`scripts/scaffold-member.ps1` + `core/templates/member/`）

剩余可选（不阻塞 final shape）：
- 远程备份（源仓库已迁入，旧仓库不再使用）
- CI 配置
- 是否引入 npm workspace

## 前置条件（迁入前需确认 — 历史记录）

- [done] 三个源仓库工作区干净（`git status` 无未提交更改）
- [pending] 源仓库已备份（迁入后旧仓库不再使用）
- [pending] 本地磁盘空间充足（subtree 重写历史，临时空间需求大）
- [pending] LamWriter / lamartist 已添加远程并推送备份（core 已迁入，无需）

## 风险

| 风险 | 缓解 |
|------|------|
| subtree add 历史冲突 | 先在备份目录试跑；降级使用 `--squash` |
| 路径修正遗漏 | 全局搜索 + 构建验证 |
| 大仓库性能 | .gitignore 排除 node_modules 等 |
| Windows 长路径限制 | 启用长路径支持 |
