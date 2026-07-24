# LamImager - AI 图像生成任务管理器

> **状态: 已实现** (2026-05-06) - 参见 README.md, AGENTS.md 和 docs/ 获取当前文档。

## 目标
构建一个综合性的 AI 图像生成任务管理程序，具备智能任务规划、提示词优化、账单管理和极简黑白灰 UI。

## 技术栈
- **后端**: Python 3.14+ / FastAPI / SQLAlchemy (async) / aiosqlite
- **前端**: Vue3 + TypeScript + Pinia + Vue Router + Vite
- **数据库**: SQLite (单文件，敏感数据加密)
- **UI**: Lucide 图标，极简黑白灰配色，无 emoji
- **LLM 集成**: 兼容 OpenAI 的 API
- **图像生成**: 兼容 OpenAI 的 API (/v1/images/generations)

## 架构: 单体应用
- FastAPI 同时提供 API 和 Vue3 静态文件
- 开发环境: Vite 开发服务器代理到 FastAPI
- 生产环境: FastAPI 托管构建后的 Vue3 dist

## 数据模型

### api_providers
- id (UUID PK), nickname, base_url, model_id, api_key_enc (AES-256-GCM)
- provider_type (image_gen / llm), billing_type (per_call / per_token)
- unit_price, currency, is_active, created_at, updated_at

### tasks
- id (UUID PK), title, description, status (planning/running/completed/failed/cancelled)
- provider_id (FK), llm_provider_id (FK), skill_id (FK nullable)
- image_count, reference_ids (JSON), created_at, updated_at

### sub_tasks
- id (UUID PK), task_id (FK), prompt, negative_prompt
- status (pending/running/completed/failed)
- result_urls (JSON), token_usage (JSON), cost, started_at, completed_at

### skills
- id (UUID PK), name, description, prompt_template, parameters (JSON)
- is_builtin, created_at

### rules
- id (UUID PK), name, rule_type (default_params/filter/workflow)
- config (JSON), is_active, priority, created_at

### billing_records
- id (UUID PK), task_id (FK), sub_task_id (FK), provider_id (FK)
- billing_type, tokens_in, tokens_out, cost, currency, detail (JSON), created_at

### reference_images
- id (UUID PK), name, file_path, file_type, file_size, thumbnail
- is_global, strength (0-1), crop_config (JSON), created_at

## UI 设计
- **配色方案**: 背景 #FAFAFA, 卡片 #FFFFFF, 边框 #E5E5E5, 文字 #1A1A1A/#666666, 强调 #000000
- **布局**: 左侧导航 (64px 图标+文字) + 主内容区 + 顶栏
- **账单**: 顶栏右侧，单行显示"本月 ¥xxx"，点击展开详情抽屉
- **无 emoji**，仅使用 Lucide 线性 SVG 图标
- **无卡片堆叠**，数据用表格，内联编辑，侧边抽屉表单
- **暂无深色主题**

## 核心工作流 (均为可选步骤)

### 任务创建
1. 用户输入图像生成需求
2. **可选**: 启用 LLM 任务规划 → 分解为子任务 + 自动生成提示词
3. **可选**: 启用提示词优化 → 选择方向 (细节/风格/构图) → LLM 优化 → 对比
4. 设置图片数量 + 参考图片 (可选)
5. 并行执行生成 → 实时进度 → 结果展示
6. 自动记录账单

### 提示词优化方向
- 细节增强
- 风格统一
- 构图优化

### API 密钥加密
- AES-256-GCM 对称加密
- 密钥从机器指纹派生 (MAC + 主机名 SHA-256)
- Base64 存储在 SQLite 中
- API 响应只显示最后 4 个字符

## 关键决策
- 单体架构以简化部署
- SQLite 用于单机部署
- 兼容 OpenAI 的 API 用于 LLM 和图像生成
- 可选的任务规划和提示词优化
- 顶栏极简账单显示
