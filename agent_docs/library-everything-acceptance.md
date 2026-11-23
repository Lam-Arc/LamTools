# Library × Everything 验收记录（2026-11-22）

对应方案：`方案/Library-全盘文件与统一资产.md`
对应 PRD：用户提供的《Sunday Library × Everything · 全盘文件搜索与统一资产管理 PRD · V1》

## 已落地范围

| 能力 | 落点 | 状态 |
|---|---|---|
| 本机 Everything 索引接入 | `core/src/lamtools_core/library/everything.py` | 可用：探测/查询/计数/分页/排序/错误分类；复用 Everything，不建第二套索引 |
| 文件身份 | `core/src/lamtools_core/library/identity.py` | 可用：卷序列号 + 文件 ID；取不到时退回路径指纹并标记 |
| 资产层 | `core/src/lamtools_core/library/store.py` + `core_file_assets` 等三张表 | 可用：收藏、评分、标签、显示名、备注、离线标记、按身份跟随移动 |
| 搜索/浏览/预览/集合服务 | `core/src/lamtools_core/library/service.py` | 可用：搜索合并资产、目录浏览、图片/视频/音频/PDF/文本/Office/文件夹预览、缩略图、集合求值 |
| 文件操作 | `core/src/lamtools_core/library/file_ops.py` | 可用：新建、重命名、复制、移动、回收站、永久删除（需确认）；冲突策略 rename/skip/overwrite；逐项结果 |
| live RPC | `core/src/lamtools_core/library/operations.py` + `http_agent_app.py` | 可用：22 个 `libraryfs.*` 操作；预览取流 `/api/core/library/raw`（inline，支持 Range） |
| Agent 工具 | `core/src/lamtools_core/library/tools.py` | 可用：`library_files` 搜索/属性/资产筛选/收藏入集合/定位/打开；不提供文件写操作 |
| 界面 | `core/ui/src/components/LocalFilesView.vue` + `LibraryHomeView.vue` | 可用：搜索、类型/范围/排序、列表/网格/瀑布、预览、资产编辑、批量操作、集合、窄窗抽屉、故障状态条 |

## 实测证据

### 1. 本机 Everything

- 安装：`C:\Program Files\Everything\Everything.exe`，版本 `1.4.1.1032`（进程运行中）。
- CLI：`ES 1.1.0.26`（开发放在 `.tools/everything/es.exe`）。
- 状态：`ready`，索引条目约 `7,833,970`。
- 查询：
  - `Everything.exe`：9 条命中，首批 5 条；计数与列表并发后热查询 61–101ms。
  - `kinds=image scope=E:\LamTools sort=size desc`：8,413 条命中，首批 60 条，热查询 116–117ms（首次冷启动约 924ms）。
  - 计数：`*.png` 27 万条，单次 20–67ms。
- 修复记录：首次实现把已编译查询再次拼接 `ext:`，导致同类条件互相 AND、计数为 0；已改为只编译一次，并由单测锁定。

### 2. 资产与文件身份

用临时图片验证：

1. 给图片打 `海报/测试` 标签、五星、收藏。
2. 在磁盘上重命名该文件。
3. 用新路径查询资产：`asset_id` 不变，标签、评分、收藏保留。
4. 复制出的第二份文件得到新的 `asset_id`，不会误认为同一资产。

### 3. live RPC（隔离后端 127.0.0.1:5291 + 隔离库）

用 WebSocket 走真实 `app-server`：

- `initialize` → `libraryfs.status` → `ready`
- `libraryfs.search` → 9 条，返回名称/路径
- `libraryfs.asset.update` → 标签 `['海报','验收']`、五星
- `libraryfs.preview` → `image`，161 字节
- `libraryfs.thumbs` → `image/jpeg`，904 字符 base64
- `libraryfs.collection.create/add/items` → 1 条，评分 5
- `libraryfs.file.operate` 复制 → 1 项成功
- `libraryfs.file.operate delete` 未确认 → 1 项失败，文件仍在
- `libraryfs.asset.forget` → 删除记录，文件仍在

### 4. 启动与建表

- 隔离后端真实启动成功；`core_file_assets`、`core_file_collections`、`core_file_collection_items` 三张表随 `create_all` 建出。
- `/api/core/library/raw`：200，`content-type: image/png`，`accept-ranges: bytes`，`content-disposition: inline`；不存在文件 404。

### 5. 测试与构建

- `pytest tests/test_library_fs_everything.py tests/test_library_fs_assets.py tests/test_library_fs_tool.py` → **20 passed**。
- `npx vite build` → 成功。
- `npx vue-tsc --noEmit`：新组件与 LibraryHomeView 无报错（仓库仍有其他既有类型错误）。

## 已知边界 / 未做

1. **重复文件管理（P1-03）**：未实现同名/同大小/内容校验分组。
2. **目录变化追踪（P1-02）**：搜索每次走 Everything 的实时索引；资产路径在打开资产列表时核对并标记离线。没有额外的文件系统 watcher，因此非 NTFS/网络盘不承诺 5 秒内同步。
3. **Bento / Dashboard 视图**：未做；当前提供列表、网格、瀑布三种。
4. **安装包分发 ES**：当前支持探测环境变量、应用数据目录、仓库 `.tools`、Program Files、PATH；尚未在安装器里打包或下载 ES。发布前需要补安装引导。
5. **操作进度/取消**：文件操作逐项返回结果并支持失败重试入口（重新执行），没有长任务的进度条与取消按钮。
6. **多设备来源（P2）**：未做。
7. **资产层为整机全局**：未按项目隔离；如果后续要求项目内独立资产，需要加 `project_id` 维度。

## 复现方式

```bash
# 后端测试（隔离库，勿指向正在使用的 core.db）
cd core
export LAMTOOLS_CORE_DB='E:\LamTools\.lam\tmp\library-test.db'
python -m pytest tests/test_library_fs_everything.py tests/test_library_fs_assets.py tests/test_library_fs_tool.py -q --allow-dirty

# 前端构建
cd core/ui
npx vite build
```

界面入口：Library → 本机文件（桌面端；手机端不显示该分区）。
