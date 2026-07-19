# Monorepo 迁移审计方案

> 日期：2026-06-04
> 状态：草案
> 作者：opencode

---

## 1. 现状

| 仓库 | 本地路径 | 默认分支 | 提交数 | 远程 |
|------|----------|----------|--------|------|
| LamToolsCore | `E:\LamToolsCore` | master | 33 | 无 |
| LamWriter | `E:\LamWriter` | writer/main | 82 | 无 |
| lamartist | `E:\lamartist` | main | 102 | `github.com/Laaaaaaaam/lamartist` |

三个仓库各自独立，共享依赖靠手动同步，无统一版本管理。

## 2. 目标结构

```
LamTools/                          ← monorepo 根
├── core/                          ← 原 LamToolsCore
├── members/
│   ├── writer/                    ← 原 LamWriter
│   └── Artist/                    ← 原 lamartist
├── package.json / …
└── .gitignore
```

- `core/` 保持核心库与共享 UI
- `members/writer/`、`members/artist/` 各自保留独立 package.json，可独立构建
- 根目录放 workspace 配置，统一依赖版本（workspace package manager 后续可选，当前不作为必需验收项）

## 3. 迁移策略：壳仓 + git subtree

### 3.1 为什么选 subtree

| 方案 | 保留历史 | 单仓体验 | 后续维护 | 结论 |
|------|----------|----------|----------|------|
| **git subtree** | yes 完整保留 | yes 代码就在仓内 | yes 无额外概念 | **推荐** |
| 直接复制文件 | no 丢失历史 | yes | yes | 不推荐 |
| git submodule | yes | no 嵌套 .git，需同步引用 | no 指针漂移、CI 复杂 | 不推荐作为最终形态 |

> **不建议直接复制**：丢失全部 commit 历史，无法 bisect、blame。
> **不建议 submodule 作为最终形态**：submodule 是指针引用，clone 需 `--recursive`，分支切换易脱节，CI 额外复杂度。可作为过渡手段，但最终应合入。

### 3.2 核心思路

1. 新建空壳仓 `E:\LamTools` 作为 monorepo 根
2. 用 `git subtree add` 将 LamToolsCore、LamWriter、lamartist 依次以子目录方式迁入，保留各自完整历史
3. 迁入后对路径引用做全局修正

## 4. 前置条件

- [ ] 三个仓库工作区干净（`git status` 无未提交更改）
- [ ] 三个仓库所有分支已推送到远程备份
- [ ] LamToolsCore 已添加远程（当前无 remote，需先 `git remote add origin <url>`）
- [ ] LamWriter 已添加远程（当前无 remote）
- [ ] `E:\LamTools` 路径不存在或为空（壳仓将在此新建）
- [ ] 本地磁盘空间 ≥ 3× 当前总大小（subtree 会重写历史，临时空间需求大）
- [ ] 确认所有协作者已同步并知晓迁移窗口
- [ ] 创建迁移专用分支 `migrate/monorepo`，不直接在默认分支操作

## 5. 迁移步骤

### Step 0：备份

```powershell
# 整目录复制一份，作为回滚锚点
Copy-Item -Recurse "E:\LamToolsCore" "E:\_backup\LamToolsCore"
Copy-Item -Recurse "E:\LamWriter"     "E:\_backup\LamWriter"
Copy-Item -Recurse "E:\lamartist"     "E:\_backup\lamartist"
```

### Step 1：新建壳仓

```powershell
# 在 E:\LamTools 新建空仓库作为 monorepo 根
New-Item -ItemType Directory -Path "E:\LamTools" -Force
cd E:\LamTools

git init
git commit --allow-empty -m "init: monorepo shell"

# 创建迁移分支
git checkout -b migrate/monorepo

# 创建目标目录结构
New-Item -ItemType Directory -Path "members" -Force
```

### Step 2：添加 LamToolsCore 为 remote 并 subtree add

```powershell
git remote add lamtoolscore E:\LamToolsCore
git fetch lamtoolscore

git subtree add --prefix=core lamtoolscore/master --squash=false
# --squash=false 保留完整历史
```

> subtree add 会将 LamToolsCore 的全部历史作为 `core/` 子目录迁入，无需手动 `git mv`，历史完整保留。

### Step 3：添加 LamWriter 为 remote 并 subtree add

```powershell
git remote add lamwriter E:\LamWriter
git fetch lamwriter

git subtree add --prefix=members/writer lamwriter/writer/main --squash=false
```

### Step 4：添加 lamartist 为 remote 并 subtree add

```powershell
git remote add lamartist E:\lamartist
git fetch lamartist

git subtree add --prefix=members/artist lamartist/main --squash=false
```

### Step 5：清理临时 remote

```powershell
git remote remove lamtoolscore
git remote remove lamwriter
git remote remove lamartist
```

### Step 6：路径修正

迁入后，writer/Artist 内部的 import 路径需要从指向独立仓库根改为指向 monorepo 内的相对位置。主要修正点：

| 修正类型 | 示例 |
|----------|------|
| 包引用路径 | `@lamtools/core` 改为 workspace 协议或相对路径 |
| tsconfig paths | `../../core/src` 等相对路径调整 |
| 构建输出目录 | 如有硬编码 `dist/` 路径需确认 |
| CI/CD 配置 | 工作目录从 `.` 改为 `members/writer` 等 |
| .gitignore | 根目录统一，子目录可保留局部补充 |

```powershell
# 全局搜索需要修正的路径引用
rg -l "from ['\"].*lamtools" members/
rg -l "workspace:" .
rg -l "tsconfig" members/
```

### Step 7：验证构建

```powershell
# Core
cd E:\LamTools\core\ui
npm run typecheck
npm run build

# Writer
cd E:\LamTools\members\writer\frontend
npm run build

# Artist
cd E:\LamTools\members\\artist\\frontend
npm run build
```

## 6. 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| subtree add 时历史冲突 | 操作失败 | 先在备份目录试跑；使用 `--squash` 作为降级方案 |
| 路径修正遗漏 | 运行时 import 错误 | 全局 rg 搜索 + 构建验证 + 运行时测试 |
| 大仓库 subtree 性能 | git 操作变慢 | monorepo 根目录 `.gitignore` 排除 node_modules 等 |
| 协作者本地仓库失效 | push/pull 冲突 | 迁移后通知所有人重新 clone |
| LamWriter/lamartist 无远程 | 无法远程备份 | 迁移前先为两者添加 remote 并 push |
| Windows 路径长度限制 | 文件操作失败 | 启用长路径支持或缩短目录名 |

## 7. 验收命令

迁移完成后，依次执行以下命令，全部通过即验收通过：

```powershell
# 1. 目录结构正确
Test-Path "E:\LamTools\core"
Test-Path "E:\LamTools\members\writer"
Test-Path "E:\LamTools\members\Artist"

# 2. 历史保留：能看到 core/writer/Artist 的历史提交
git log --oneline --all -- core/ | Select-Object -First 5
git log --oneline --all -- members/writer/ | Select-Object -First 5
git log --oneline --all -- members/artist/ | Select-Object -First 5

# 3. 工作区干净
git status --porcelain   # 应无输出

# 4. 构建通过
# Core
cd E:\LamTools\core\ui; npm run typecheck; npm run build
# Writer
cd E:\LamTools\members\writer\frontend; npm run build
# Artist
cd E:\LamTools\members\\artist\\frontend; npm run build

# 5. 无残留 remote
git remote -v   # 应只剩 origin（或为空，视是否已配置远程）
```

## 8. 回滚方案

若迁移过程中出现不可恢复问题：

```powershell
# 方案 A：迁移分支未合并，直接切回主分支并删除迁移分支
cd E:\LamTools
git checkout master   # 或 main
git branch -D migrate/monorepo

# 方案 B：壳仓整体作废，直接删除（源仓库未受影响）
Remove-Item -Recurse -Force "E:\LamTools"

# 方案 C：远程已推送错误提交
git push origin --force master   # 谨慎使用
```

> 回滚前提：Step 0 的备份必须存在且完整。三个源仓库（LamToolsCore / LamWriter / lamartist）在整个迁移过程中只读，不受影响，最差情况就是删除 `E:\LamTools` 重新来过。

## 9. 下一条 opencode 提示词

迁移方案确认后，将以下提示词交给 opencode 执行：

```
按照 docs/plans/2026-06-04-monorepo-migration-audit.md 的迁移步骤，从 Step 0 开始逐步执行。每完成一步后暂停，报告结果并等待确认再继续下一步。遇到失败立即停止并报告，不要自行回滚。
```
