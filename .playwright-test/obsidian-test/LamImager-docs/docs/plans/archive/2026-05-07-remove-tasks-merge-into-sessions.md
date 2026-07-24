# 移除独立任务功能，统一到会话 实施计划

> **For agentic workers:** Use executing-plans or subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移除独立的 Tasks 功能，修复 BillingRecord 数据模型 Bug，将会话作为唯一的图像生成入口。

**Architecture:** 删除 Task/SubTask 独立功能模块（后端路由/服务/Schema + 前端页面/API/Store），在 BillingRecord 中新增 session_id 字段替代被滥用的 task_id，将 Dashboard 统计改为基于 Session/Message，清理所有跨模块引用。

**Tech Stack:** Python 3.14+ / FastAPI / SQLAlchemy async / Vue3 / TypeScript / Pinia

---

## Task 1: 修复 BillingRecord 模型 — 新增 session_id，移除 Task 外键

**Files:**
- `backend/app/models/billing.py`

**Steps:**
- [ ] 在 BillingRecord 模型中新增 `session_id` 字段：`Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=True)`
- [ ] 将 `task_id` 的 ForeignKey 约束移除，改为普通字符串字段：`Mapped[str] = mapped_column(String(36), nullable=True)`（保留字段用于向后兼容旧数据）
- [ ] 将 `sub_task_id` 的 ForeignKey 约束移除，改为普通字符串字段：`Mapped[str] = mapped_column(String(36), nullable=True)`
- [ ] 新增 `session` relationship：`relationship("Session", back_populates="billing_records")`
- [ ] 移除 `task` relationship（`relationship("Task", back_populates="billing_records")`）
- [ ] 移除 `sub_task` relationship（`relationship("SubTask", back_populates="billing_records")`）

**Verification:**
- [ ] 模型文件无语法错误，ForeignKey 仅指向 sessions 和 api_providers

**Commit:** `refactor: add session_id to BillingRecord, remove Task FK constraints`

---

## Task 2: 修复 Session 模型 — 新增 billing_records 关系

**Files:**
- `backend/app/models/session.py`

**Steps:**
- [ ] 在 Session 模型中新增 `billing_records = relationship("BillingRecord", back_populates="session")`

**Verification:**
- [ ] Session 模型有 billing_records 关系

**Commit:** `refactor: add billing_records relationship to Session model`

---

## Task 3: 修复 generate_service.py — 使用 session_id 创建 BillingRecord

**Files:**
- `backend/app/services/generate_service.py`

**Steps:**
- [ ] 移除 `from app.models.task import SubTask, SubTaskStatus, Task, TaskStatus` 导入
- [ ] 移除 `from app.services.task_planner import plan_task` 导入
- [ ] 将 BillingRecord 创建处的 `task_id=session_id` 改为 `session_id=session_id`
- [ ] 移除 BillingRecord 中的 `task_id` 字段赋值

**Verification:**
- [ ] generate_service.py 中不再引用 Task/SubTask/task_planner
- [ ] BillingRecord 使用 session_id 字段

**Commit:** `refactor: use session_id in generate_service BillingRecord`

---

## Task 4: 修复 session_manager.py — 使用 session_id 查询，移除 SubTask 查询

**Files:**
- `backend/app/services/session_manager.py`

**Steps:**
- [ ] 移除 `from app.models.task import SubTask, SubTaskStatus` 导入
- [ ] 将 `BillingRecord.task_id == s.id` 查询改为 `BillingRecord.session_id == s.id`
- [ ] 移除 SubTask 进度查询（completed_result、total_result、progress 计算逻辑，约第 82-95 行）
- [ ] 在 response dict 中将 `progress` 字段设为空字符串 `""`（移除 SubTask 统计后无进度数据）

**Verification:**
- [ ] session_manager.py 中不再引用 SubTask/SubTaskStatus
- [ ] BillingRecord 查询使用 session_id

**Commit:** `refactor: use session_id in session_manager, remove SubTask queries`

---

## Task 5: 修复 billing_service.py — 更新 record_billing 和 billing_to_response

**Files:**
- `backend/app/services/billing_service.py`

**Steps:**
- [ ] `record_billing` 函数：新增 `session_id: str = None` 参数，在 BillingRecord 创建中使用 `session_id=session_id`
- [ ] `billing_to_response` 函数：新增 `"session_id": record.session_id` 字段
- [ ] `get_details` 函数：将 `query.task_id` 过滤改为 `query.session_id` 过滤（`BillingRecord.session_id == query.session_id`）
- [ ] `export_billing_csv` 函数：CSV header 中将 `"Task ID"` 改为 `"Session ID"`，输出 `r.session_id or ""` 替代 `r.task_id or ""`

**Verification:**
- [ ] billing_service.py 中 record_billing 支持 session_id
- [ ] billing_to_response 包含 session_id
- [ ] 查询和导出使用 session_id

**Commit:** `refactor: update billing_service to use session_id`

---

## Task 6: 修复 billing schemas — 替换 task_id 为 session_id

**Files:**
- `backend/app/schemas/billing.py`

**Steps:**
- [ ] `BillingRecordResponse`：将 `task_id: str | None = None` 改为 `session_id: str | None = None`，移除 `sub_task_id` 字段
- [ ] `BillingDetailQuery`：将 `task_id: str | None = None` 改为 `session_id: str | None = None`

**Verification:**
- [ ] Schema 中无 task_id/sub_task_id，有 session_id

**Commit:** `refactor: update billing schemas to use session_id`

---

## Task 7: 修复 billing router — 替换 task_id 参数为 session_id

**Files:**
- `backend/app/routers/billing.py`

**Steps:**
- [ ] `api_billing_details` 端点：将 `task_id: str = None` 参数改为 `session_id: str = None`
- [ ] BillingDetailQuery 构造中：将 `task_id=task_id` 改为 `session_id=session_id`

**Verification:**
- [ ] billing router 中无 task_id 参数

**Commit:** `refactor: update billing router to use session_id param`

---

## Task 8: 修复 dashboard — 替换 Task/SubTask 统计为 Session/Message 统计

**Files:**
- `backend/app/routers/dashboard.py`

**Steps:**
- [ ] 移除 `from app.models.task import Task, TaskStatus` 导入
- [ ] 移除 `from app.models.task import SubTask, SubTaskStatus` 导入
- [ ] 新增 `from app.models.session import Session` 和 `from app.models.message import Message, MessageType` 导入
- [ ] 将 `total_tasks` 查询改为 `total_sessions`：`select(func.count(Session.id))`
- [ ] 将 `running_tasks` 查询改为 `total_images`：统计 Message 中 `message_type == MessageType.image` 的数量
- [ ] 将 `completed_tasks` 查询改为 `total_generations`：统计 Message 中 `message_type == MessageType.image` 的去重 session 数量（即有生成记录的会话数）
- [ ] 移除 `total_images` 的 SubTask 查询（已被上面的 total_images 替代）
- [ ] 返回 dict 改为：`{"total_sessions": ..., "total_images": ..., "total_generations": ..., "monthly_cost": ...}`

**Verification:**
- [ ] dashboard router 中不再引用 Task/SubTask
- [ ] 返回的统计字段基于 Session/Message

**Commit:** `refactor: replace Task/SubTask stats with Session/Message stats in dashboard`

---

## Task 9: 移除 Task/SubTask 模型

**Files:**
- `backend/app/models/task.py`（删除整个文件）
- `backend/app/models/__init__.py`

**Steps:**
- [ ] 删除 `backend/app/models/task.py` 文件
- [ ] 在 `__init__.py` 中移除 `from app.models.task import Task, SubTask, TaskStatus, SubTaskStatus` 导入
- [ ] 在 `__init__.py` 的 `__all__` 列表中移除 `"Task", "SubTask", "TaskStatus", "SubTaskStatus"`

**Verification:**
- [ ] models/task.py 已删除
- [ ] __init__.py 中无 Task/SubTask 引用

**Commit:** `refactor: remove Task/SubTask models`

---

## Task 10: 清理 ApiProvider 和 Skill 模型中的 Task 关系

**Files:**
- `backend/app/models/api_provider.py`
- `backend/app/models/skill.py`

**Steps:**
- [ ] `api_provider.py`：移除 `tasks = relationship("Task", back_populates="provider", foreign_keys="Task.provider_id")`
- [ ] `api_provider.py`：移除 `llm_tasks = relationship("Task", back_populates="llm_provider", foreign_keys="Task.llm_provider_id")`
- [ ] `skill.py`：移除 `tasks = relationship("Task", back_populates="skill")`

**Verification:**
- [ ] ApiProvider 和 Skill 模型中无 Task 关系

**Commit:** `refactor: remove Task relationships from ApiProvider and Skill`

---

## Task 11: 删除 Task 后端路由、服务和 Schema

**Files:**
- `backend/app/routers/task.py`（删除）
- `backend/app/services/task_executor.py`（删除）
- `backend/app/services/task_planner.py`（删除）
- `backend/app/schemas/task.py`（删除）
- `backend/app/main.py`

**Steps:**
- [ ] 删除 `backend/app/routers/task.py`
- [ ] 删除 `backend/app/services/task_executor.py`
- [ ] 删除 `backend/app/services/task_planner.py`
- [ ] 删除 `backend/app/schemas/task.py`
- [ ] 在 `main.py` 中移除 `from app.routers import ... task ...` 中的 `task`
- [ ] 在 `main.py` 中移除 `app.include_router(task.router)`

**Verification:**
- [ ] 4 个文件已删除
- [ ] main.py 中无 task 路由注册

**Commit:** `refactor: remove Task router, services, and schemas`

---

## Task 12: 数据库迁移处理

**Files:**
- `backend/app/database.py`

**Steps:**
- [ ] 在 `init_db()` 函数中，在 `Base.metadata.create_all` 之后添加迁移逻辑：
  - 检查 `billing_records` 表是否有 `session_id` 列
  - 如果没有，执行 `ALTER TABLE billing_records ADD COLUMN session_id VARCHAR(36)`
  - 将已有的 `task_id` 值迁移到 `session_id`（仅当 session_id 为空且 task_id 对应的值存在于 sessions 表中时）
  - 删除旧的 `tasks` 和 `sub_tasks` 表（`DROP TABLE IF EXISTS sub_tasks; DROP TABLE IF EXISTS tasks;`）

**Verification:**
- [ ] 数据库初始化时自动添加 session_id 列
- [ ] 旧数据被迁移
- [ ] tasks 和 sub_tasks 表被清理

**Commit:** `refactor: add DB migration for session_id column and cleanup`

---

## Task 13: 删除前端 Task 相关文件

**Files:**
- `frontend/src/views/TaskList.vue`（删除）
- `frontend/src/views/TaskDetail.vue`（删除）
- `frontend/src/api/task.ts`（删除）
- `frontend/src/stores/task.ts`（删除）

**Steps:**
- [ ] 删除 `frontend/src/views/TaskList.vue`
- [ ] 删除 `frontend/src/views/TaskDetail.vue`
- [ ] 删除 `frontend/src/api/task.ts`
- [ ] 删除 `frontend/src/stores/task.ts`

**Verification:**
- [ ] 4 个文件已删除

**Commit:** `refactor: remove Task frontend files`

---

## Task 14: 清理前端类型定义

**Files:**
- `frontend/src/types/index.ts`

**Steps:**
- [ ] 移除 `SubTask` 接口（第 40-51 行）
- [ ] 移除 `Task` 接口（第 53-66 行）
- [ ] 移除 `TaskCreate` 接口（第 68-77 行）
- [ ] 在 `BillingRecord` 接口中：将 `task_id: string | null` 改为 `session_id: string | null`，移除 `sub_task_id` 字段

**Verification:**
- [ ] types/index.ts 中无 Task/SubTask/TaskCreate 接口
- [ ] BillingRecord 使用 session_id

**Commit:** `refactor: remove Task types, update BillingRecord to use session_id`

---

## Task 15: 清理 App.vue — 移除任务导航项

**Files:**
- `frontend/src/App.vue`

**Steps:**
- [ ] 移除"任务"导航链接（`<router-link to="/tasks">` 整块，约第 10-13 行）
- [ ] 移除 `ImagePlus` 图标的 import（从 lucide-vue-next 导入列表中删除）
- [ ] 在 `pageTitles` 中移除 `tasks: '任务'` 和 `'task-detail': '任务详情'`

**Verification:**
- [ ] App.vue 中无任务导航项
- [ ] 无 ImagePlus 导入

**Commit:** `refactor: remove Task nav item from App.vue`

---

## Task 16: 清理前端路由 — 移除任务路由

**Files:**
- `frontend/src/router/index.ts`

**Steps:**
- [ ] 移除 `/tasks` 路由定义（约第 17-19 行）
- [ ] 移除 `/tasks/:id` 路由定义（约第 21-24 行）

**Verification:**
- [ ] router/index.ts 中无 /tasks 路由

**Commit:** `refactor: remove Task routes from router`

---

## Task 17: 清理 Sessions.vue — 移除 taskApi 导入

**Files:**
- `frontend/src/views/Sessions.vue`

**Steps:**
- [ ] 移除 `import { taskApi } from '../api/task'` 行（第 396 行）

**Verification:**
- [ ] Sessions.vue 中无 taskApi 引用

**Commit:** `refactor: remove unused taskApi import from Sessions.vue`

---

## Task 18: 修复 Dashboard.vue — 更新统计展示

**Files:**
- `frontend/src/views/Dashboard.vue`

**Steps:**
- [ ] 将 stats ref 初始值改为：`{ total_sessions: 0, total_images: 0, total_generations: 0, monthly_cost: 0 }`
- [ ] 模板中：将 `stats.total_tasks` 改为 `stats.total_sessions`，标签改为"总会话数"
- [ ] 模板中：将 `stats.running_tasks` 改为 `stats.total_images`，标签改为"生成图片数"
- [ ] 模板中：将 `stats.completed_tasks` 改为 `stats.total_generations`，标签改为"生成次数"
- [ ] 保留 `stats.total_images`（原第4个stat）改为显示月度费用或移除（避免与新的 total_images 重复）

**Verification:**
- [ ] Dashboard 展示基于 Session/Message 的统计

**Commit:** `refactor: update Dashboard to show Session/Message stats`

---

## Task 19: 修复 dashboard API 类型

**Files:**
- `frontend/src/api/dashboard.ts`

**Steps:**
- [ ] 将返回类型改为：`{ total_sessions: number; total_images: number; total_generations: number; monthly_cost: number }`

**Verification:**
- [ ] dashboard API 类型与后端一致

**Commit:** `refactor: update dashboard API types`

---

## Task 20: 验证 — 启动后端和前端，确认无报错

**Steps:**
- [ ] 删除旧数据库文件 `data/lamimager.db`（如果存在）
- [ ] 启动后端 `cd backend && uvicorn app.main:app --reload --port 8000`，确认无启动错误
- [ ] 启动前端 `cd frontend && npm run dev`，确认无编译错误
- [ ] 访问前端页面，确认导航栏无"任务"入口
- [ ] 测试会话生成功能，确认 BillingRecord 正确记录 session_id

**Verification:**
- [ ] 后端启动无报错
- [ ] 前端编译无报错
- [ ] 会话生成功能正常

**Commit:** （无需提交，验证步骤）
