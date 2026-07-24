# LamImager 实施计划

> **状态: 已完成** (2026-05-06) - 所有 30 个任务已实现。参见 README.md 和 docs/ 获取当前文档。

> **For agentic workers:** 使用 executing-plans 或 subagent-driven-development 逐任务实施此计划。步骤使用复选框 (`- [x]`) 语法追踪。

**目标:** 构建一个全功能的 AI 图像生成任务管理程序，具备 LLM 驱动的任务规划、提示词优化、账单、技能/规则和参考图片管理。

**架构:** 单体 FastAPI 后端提供 Vue3 SPA 前端。SQLite 数据持久化，敏感数据使用 AES-256-GCM 加密。三层架构: Router -> Service -> Model。

**技术栈:** Python 3.14+ / FastAPI / SQLAlchemy(async) / aiosqlite / Vue3 / TypeScript / Pinia / Vue Router / Vite / Lucide Icons

---

## 阶段 1: 项目脚手架

### 任务 1: 初始化后端项目

**文件:**
- `e:\LamImager\backend\app\__init__.py`
- `e:\LamImager\backend\app\config.py`
- `e:\LamImager\backend\app\database.py`
- `e:\LamImager\backend\app\main.py`
- `e:\LamImager\backend\requirements.txt`

**步骤:**
- [ ] 创建目录结构: `backend/app/`, `backend/app/models/`, `backend/app/routers/`, `backend/app/services/`, `backend/app/schemas/`, `backend/app/utils/`
- [ ] 创建 `requirements.txt`，包含: fastapi, uvicorn, sqlalchemy[asyncio], aiosqlite, pydantic, python-multipart, aiohttp, cryptography, PyJWT, alembic
- [ ] 创建 `config.py`，使用 pydantic BaseSettings 的 Settings 类: DATA_DIR, DB_URL, ENCRYPTION_KEY 派生, CORS origins, API prefix
- [ ] 创建 `database.py`，包含异步 SQLAlchemy 引擎、async sessionmaker、Base 声明类、get_db 依赖
- [ ] 创建 `main.py`，包含 FastAPI 应用、CORS 中间件、生命周期处理器（初始化数据库表）、健康检查端点
- [ ] 创建所有 `__init__.py` 文件

**验证:**
- [ ] 在 backend 目录运行 `pip install -r requirements.txt`
- [ ] 运行 `uvicorn app.main:app --reload` 并验证健康检查返回 200

**提交:** `feat: initialize backend project structure`

### 任务 2: 初始化前端项目

**文件:**
- `e:\LamImager\frontend\package.json`
- `e:\LamImager\frontend\vite.config.ts`
- `e:\LamImager\frontend\tsconfig.json`
- `e:\LamImager\frontend\src\main.ts`
- `e:\LamImager\frontend\src\App.vue`
- `e:\LamImager\frontend\src\router\index.ts`
- `e:\LamImager\frontend\src\styles\global.css`

**步骤:**
- [ ] 在 LamImager 根目录运行 `npm create vite@latest frontend -- --template vue-ts`
- [ ] 安装依赖: `npm install vue-router@4 pinia axios lucide-vue-next`
- [ ] 配置 `vite.config.ts` 代理: `/api` -> `http://localhost:8000`
- [ ] 创建全局 CSS，包含黑白灰配色变量: --bg: #FAFAFA, --card: #FFFFFF, --border: #E5E5E5, --text: #1A1A1A, --text-secondary: #666666, --accent: #000000
- [ ] 创建 Vue Router，所有页面使用空路由占位符
- [ ] 在 main.ts 中创建 Pinia store 设置
- [ ] 创建 App.vue，包含左侧导航布局 (64px 侧边栏 + 主内容区 + 顶栏)

**验证:**
- [ ] 运行 `npm run dev` 并验证应用加载时布局可见
- [ ] 验证到后端的代理工作正常（健康检查）

**提交:** `feat: initialize frontend project structure`

---

## 阶段 2: 后端核心工具

### 任务 3: 加密工具

**文件:**
- `e:\LamImager\backend\app\utils\crypto.py`

**步骤:**
- [ ] 实现 `derive_key()` - 从机器指纹派生 AES 密钥 (MAC 地址 + 主机名 -> SHA-256)
- [ ] 实现 `encrypt(plaintext: str) -> str` - AES-256-GCM 加密，返回 Base64 编码的 nonce+ciphertext+tag
- [ ] 实现 `decrypt(ciphertext: str) -> str` - AES-256-GCM 解密，从 Base64 解码
- [ ] 实现 `mask_key(key: str) -> str` - 返回 "****" + 最后 4 个字符

**验证:**
- [ ] 编写并运行测试脚本: 加密字符串，解密，验证匹配；验证 mask_key 输出

**提交:** `feat: implement AES-256-GCM encryption utility`

### 任务 4: LLM 客户端工具

**文件:**
- `e:\LamImager\backend\app\utils\llm_client.py`

**步骤:**
- [ ] 实现 `LLMClient` 类，包含 `__init__(base_url, api_key, model_id)`
- [ ] 实现 `async chat(messages: list, temperature: float = 0.7) -> dict` - 调用兼容 OpenAI 的 chat completions API
- [ ] 实现 `async chat_stream(messages: list, temperature: float = 0.7) -> AsyncGenerator` - 流式聊天
- [ ] 实现 `async test_connection() -> bool` - 简单测试调用以验证 API 连接
- [ ] 添加正确的错误处理和自定义异常: LLMConnectionError, LLMResponseError

**验证:**
- [ ] 使用模拟服务器或真实 API 密钥进行单元测试

**提交:** `feat: implement OpenAI-compatible LLM client`

### 任务 5: 图像生成客户端工具

**文件:**
- `e:\LamImager\backend\app\utils\image_client.py`

**步骤:**
- [ ] 实现 `ImageClient` 类，包含 `__init__(base_url, api_key, model_id)`
- [ ] 实现 `async generate(prompt: str, negative_prompt: str = "", n: int = 1, size: str = "1024x1024", **kwargs) -> dict` - 调用 /v1/images/generations
- [ ] 实现 `async test_connection() -> bool` - 验证 API 连接
- [ ] 添加错误处理: ImageGenError, ImageGenConnectionError

**验证:**
- [ ] 使用模拟或手动测试进行单元测试

**提交:** `feat: implement OpenAI-compatible image generation client`

---

## 阶段 3-12: (内容已省略，详见原文档)

完整的实施计划包含 30 个任务，涵盖:
- 数据库模型
- API 提供商管理
- 任务管理核心
- LLM 任务规划
- 提示词优化
- 技能和规则系统
- 账单系统
- 参考图片和文件上传
- 仪表盘和完善
- 集成和最终完善

参见原始英文文档 `2026-05-06-lamimager-implementation.md` 获取完整任务列表。
