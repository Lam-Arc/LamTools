# Video Branch Design

> 日期: 2026-05-21
> 状态: 设计完成，待实施
> 范围: Artist 可调用视频生成能力

---

## 1. 核心定位

**Video 是 Artist 的 action，不是独立 Agent。** 复用现有 PER/CON/turn 机制，在 ArtistAction 中新增视频相关 action 类型。

设计原则：
- 最小侵入：不改变 turn 模型，不引入多 turn 编排
- 渐进扩展：V1 做最小可用集，V2/V3 叠加短剧/布局能力
- 输入松、内部紧：LLM 填充 video_scenes 用 list[dict]，内部 parse 为强类型

---

## 2. 交互模型

### 2.1 核心决策：单 turn + 异步后台

视频生成是异步长时间操作（30s-5min），与图像生成的近同步特性根本不同。

**方案选择**：

| 方案 | 描述 | 结论 |
|------|------|------|
| A: 单turn长阻塞 | _execute_action 内 poll 等待 | ❌ HTTP超时、无中间反馈 |
| B: 多turn编排 | 每阶段一个turn | ❌ 过度设计，流水线硬塞对话模型 |
| **C: 单turn+异步后台** | turn立即返回，后台task轮询+SSE推送 | ✅ 采用 |

**交互流程**：

```
Turn 1: 用户请求视频
  LLM 输出 generate_video action
  → _execute_action 提交视频任务到 provider API
  → 启动后台 asyncio task: _poll_video_tasks()
  → 立即返回（无 artifact，无 cost）
  → SSE: artist_turn_submitted(phase="video_generating")
  → turn_done 延迟到视频完成

后台: 异步轮询 + SSE 推送
  → SSE: artist_clip_ready × N（逐clip完成）
  → SSE: artist_video_ready（最终视频完成）
  → 此时才发出 turn_done
  → 记录计费、创建 artifact

Turn 2: 用户迭代
  → 正常 turn，可引用已有视频
```

### 2.2 turn_done 语义

- **图像**：turn_done = 所有 action 执行完毕
- **视频**：turn_done = 视频生成完毕（延迟发出）
- 新增 `artist_turn_submitted` 事件：表示 Artist 已回复并提交任务，前端可继续聊天但显示"视频生成中"状态

### 2.3 费用确认

复用现有 `ask_clarification` + `waiting_clarification` phase，不需要新 phase。

```
用户: "做一个30秒视频"
Artist: "30秒大概6个clip||预计费用$2.40||确认吗"
  → action: ask_clarification
  → SSE: artist_cost_estimate(cost=2.40, breakdown=[...])

用户: "确认"
  → 下一 turn 输出 generate_video action
```

### 2.4 混合 action 互斥

同一 turn 内图像和视频 action 互斥。turn_parser 层面强制校验：

```python
VIDEO_ACTION_TYPES = {"generate_video", "extract_frame", "trim_video", "adjust_video"}
IMAGE_ACTION_TYPES = {"generate_anchor", "generate_pack", "refine_target", "replace_image", "style_reference"}

def _validate_action_compatibility(actions: list[ArtistAction]) -> list[ArtistAction]:
    video_actions = [a for a in actions if a.type in VIDEO_ACTION_TYPES]
    image_actions = [a for a in actions if a.type in IMAGE_ACTION_TYPES]
    if video_actions and image_actions:
        # 优先保留视频 action，丢弃图像 action
        return [a for a in actions if a.type in VIDEO_ACTION_TYPES]
    return actions
```

---

## 3. Schema 变更

### 3.1 ArtistActionType

```python
ArtistActionType = Literal[
    # 现有 8 个（图像）
    "chat_only",
    "ask_clarification",
    "generate_anchor",
    "generate_pack",
    "refine_target",
    "replace_image",
    "style_reference",
    "self_critique",
    # 新增 4 个（视频）
    "generate_video",     # T2V / I2V / V2V / 延长 / 多图→视频
    "extract_frame",      # 视频→图
    "trim_video",         # 裁剪视频（纯 FFmpeg，不调用 provider）
    "adjust_video",       # 变速/调整（纯 FFmpeg）
]
```

**1 个 action 覆盖 5 种视频模式**，通过字段区分：

| 模式 | 触发字段 |
|------|---------|
| T2V | prompt only |
| I2V | prompt + reference_images |
| V2V 风格迁移 | prompt + source_video_url |
| V2V 运动修改 | prompt + source_video_url + clip_index |
| 延长 | prompt + extend_from_url |
| 多图→视频 | prompt + reference_images（多图） |

### 3.2 ArtistAction 新增字段

```python
class ArtistAction(BaseModel):
    type: ArtistActionType
    prompt: str = ""
    # 现有图像字段（不变）
    image_count: int = 1
    image_size: str = "1024x1024"
    negative_prompt: str = ""
    target_images: list[str] = Field(default_factory=list)
    reference_images: list[str] = Field(default_factory=list)
    replace_index: int | None = None
    message: str = ""

    # V1 视频字段
    video_duration: float = 5.0
    video_aspect_ratio: str = "16:9"
    video_camera: str = ""                     # "zoom_in" / "orbit_left" / "pan_right" 等
    video_loop: bool = False
    video_scenes: list[dict] = Field(default_factory=list)  # LLM 灵活 JSON
    source_video_url: str = ""                 # V2V 源视频
    extend_from_url: str = ""                  # 延长源视频
    clip_index: int | None = None              # 替换特定 clip
    frame_time: float | None = None            # extract_frame 用：提取时间点
    trim_start: float | None = None            # 裁剪起始时间（秒）
    trim_end: float | None = None              # 裁剪结束时间（秒）
    video_speed: float | None = None           # 变速倍率（0.5=慢放, 2.0=快进）

    # V2 预留字段（V1 忽略，V2 使用）
    character_id: str = ""                     # 角色ID
    outfit_id: str = ""                        # 服装ID
    layout_id: str = ""                        # 布局ID
    camera_id: str = ""                        # 摄像机ID
    shot_type: str = ""                        # 景别
    camera_angle: str = ""                     # 机位
    dialogue: str = ""                         # 对白
```

### 3.3 ArtistRuntimePhase

```python
ArtistRuntimePhase = Literal[
    # 现有 5 个
    "idle",
    "anchor_pending",
    "pack_ready",
    "refining",
    "waiting_clarification",
    # 新增 1 个
    "video_generating",   # 视频生成中（涵盖 plan→clips→compose 全流程）
]
```

### 3.4 ArtistSessionState 新增字段

```python
class ArtistSessionState(BaseModel):
    # 现有 14 个字段不变
    session_id: str
    phase: ArtistRuntimePhase = "idle"
    anchor_group_id: str = ""
    last_group_id: str = ""
    last_target_url: str = ""
    pending_prompt: str = ""
    pack_count: int = 6
    model_mode: str = "auto"
    anchor_first: bool = True
    head_artifact_id: str = ""
    active_branch: str = "main"
    branch_labels: dict[str, str] = Field(default_factory=dict)
    branch_counter: int = 0
    last_head_url: str = ""
    last_head_root_url: str = ""
    last_head_root_artifact_id: str = ""
    previous_head_children: list[str] = Field(default_factory=list)

    # 新增 3 个视频字段
    video_plan: VideoPlan | None = None
    video_clips: list[VideoClipRef] = Field(default_factory=list)
    video_url: str = ""

    # V2 预留
    drama_project: dict | None = None
```

### 3.5 ArtistArtifact 扩展

```python
class ArtistArtifact(BaseModel):
    # 现有字段不变
    artist_turn_id: str
    artifact_type: Literal[
        "anchor", "pack", "refine", "replacement",
        "reference", "critique",
        "video", "extracted_frame", "trimmed_video", "adjusted_video"
    ]
    url: str
    group_id: str
    index_in_group: int
    artifact_id: str = ""
    parent_artifact_id: str = ""
    root_artifact_id: str = ""
    parent_url: str = ""
    root_url: str = ""
    source_message_id: str = ""
    branch_name: str = ""
    prompt: str = ""
    artist_comment: str = ""
    status: Literal["completed", "failed", "pending"] = "completed"

    # 新增
    thumbnail_url: str = ""                   # 视频封面图（自动提取首帧）
    metadata: dict = Field(default_factory=dict)  # 生成参数/时长/分辨率/provider 等
```

### 3.6 新增 Pydantic 模型

```python
class VideoScene(BaseModel):
    """视频场景（内部强类型，从 video_scenes list[dict] parse 而来）"""
    prompt: str
    duration: float = 5.0
    camera: str = ""
    reference_image: str = ""
    # V2 预留
    character_id: str = ""
    outfit_id: str = ""
    shot_type: str = ""
    camera_angle: str = ""
    action: str = ""
    dialogue: str = ""

class VideoPlan(BaseModel):
    """视频计划"""
    scenes: list[VideoScene] = Field(default_factory=list)
    total_duration: float = 0.0
    aspect_ratio: str = "16:9"
    style: str = ""
    source_video_url: str = ""
    extend_from_url: str = ""

class VideoClipRef(BaseModel):
    """已提交的 clip 引用"""
    clip_index: int
    task_id: str = ""
    provider: str = ""
    status: Literal["pending", "processing", "completed", "failed"] = "pending"
    url: str = ""
    local_url: str = ""
    duration: float = 5.0
    error: str = ""

class VideoError(BaseModel):
    """视频错误（分级展示）"""
    user_message: str       # 用户看到的友好消息
    detail: str             # 技术细节（可展开）
    suggestion: str         # 建议操作
    retryable: bool         # 是否可重试
    error_code: str = ""    # 统一错误码
```

---

## 4. Transitions 扩展

```python
_TRANSITIONS = {
    "idle": {
        "anchor_requested": "anchor_pending",
        "clarification_needed": "waiting_clarification",
        "video_requested": "video_generating",       # 新增
        "reset": "idle",
    },
    "anchor_pending": { ... },       # 不变
    "pack_ready": { ... },           # 不变
    "refining": { ... },             # 不变
    "waiting_clarification": {
        "clarification_resolved": "idle",
        "video_requested": "video_generating",       # 新增：用户修改需求后直接进入视频生成
        "reset": "idle",
    },
    # 新增
    "video_generating": {
        "video_completed": "idle",
        "video_failed": "idle",
        "reset": "idle",
    },
}
```

---

## 5. SSE 事件

### 5.1 新增事件（5 个）

```python
# events.py 新增

def artist_turn_submitted(session_id, artist_turn_id, phase):
    """Artist 已提交任务（视频生成中），前端可继续聊天"""
    return ArtistEvent(type="artist_turn_submitted", ...)

def artist_clip_ready(session_id, artist_turn_id, clip_index, url, duration):
    """单个 clip 生成完成"""
    return ArtistEvent(type="artist_clip_ready", ...)

def artist_video_ready(session_id, artist_turn_id, video_url, artifact):
    """最终视频完成"""
    return ArtistEvent(type="artist_video_ready", ...)

def artist_cost_estimate(session_id, artist_turn_id, cost, breakdown):
    """费用预估（等待确认）"""
    return ArtistEvent(type="artist_cost_estimate", ...)

def artist_action_failed(session_id, artist_turn_id, action_type, error: VideoError):
    """action 执行失败"""
    return ArtistEvent(type="artist_action_failed", ...)
```

### 5.2 现有事件复用

| 需求 | 复用事件 | 说明 |
|------|---------|------|
| 关键帧图完成 | `artist_image_ready` | artifact_type="reference" |
| 帧提取完成 | `artist_image_ready` | artifact_type="extracted_frame" |
| 裁剪/变速完成 | `artist_video_ready` | artifact_type="trimmed_video"/"adjusted_video" |

---

## 6. Runtime 扩展

### 6.1 _execute_action 扩展

```python
async def _execute_action(self, action, session_id, artist_turn_id, state):
    # 现有分支不变
    if action.type in ("chat_only", "ask_clarification", "self_critique"):
        return [], 0.0

    # 新增：视频生成
    if action.type == "generate_video":
        return await self._execute_video_action(action, session_id, artist_turn_id, state)

    # 新增：帧提取
    if action.type == "extract_frame":
        return await self._execute_extract_frame(action, session_id, artist_turn_id, state)

    # 新增：视频裁剪
    if action.type == "trim_video":
        return await self._execute_trim_video(action, session_id, artist_turn_id, state)

    # 新增：视频变速
    if action.type == "adjust_video":
        return await self._execute_adjust_video(action, session_id, artist_turn_id, state)

    # 现有图像生成逻辑不变
    ...
```

### 6.2 per-action 错误处理

现有 Artist 的最大架构缺陷：无 per-action 错误处理。视频分支必须修复。

```python
for action in turn.actions:
    try:
        action_artifacts, action_cost = await self._execute_action(...)
        artifacts.extend(action_artifacts)
        total_cost += action_cost
    except Exception as e:
        logger.error(f"Action {action.type} failed: {e}")
        await self.deps.event_publish(artist_action_failed(
            session_id, artist_turn_id, action.type,
            VideoError(
                user_message="操作失败",
                detail=str(e),
                suggestion="请重试或修改描述",
                retryable=True,
            )
        ))
        # 继续执行后续 action，不中断 turn
```

### 6.3 并发 turn 保护

```python
class ArtistRuntime:
    def __init__(self, deps):
        self.deps = deps
        self._video_tasks: dict[str, asyncio.Task] = {}
        self._session_locks: dict[str, asyncio.Lock] = {}

    async def handle_turn(self, session_id, ...):
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            await self.deps.event_publish(artist_action_failed(
                session_id, "", "concurrent_turn",
                VideoError(
                    user_message="上一个任务还在执行中",
                    detail="Concurrent turn rejected",
                    suggestion="请等待当前任务完成",
                    retryable=False,
                )
            ))
            return {"error": "concurrent_turn"}
        async with lock:
            # 正常执行 turn
            ...
```

### 6.4 _execute_video_action

```python
async def _execute_video_action(self, action, session_id, artist_turn_id, state):
    """提交视频生成任务，启动后台轮询，立即返回"""

    # 1. 校验 video_scenes
    scenes = self._validate_video_scenes(action.video_scenes)
    if not scenes and not action.prompt:
        raise VideoActionError("至少需要 prompt 或 video_scenes")

    # 2. 费用预估
    clip_count = len(scenes) or 1
    estimated_cost = clip_count * self._get_video_cost_per_clip(action)
    await self.deps.event_publish(artist_cost_estimate(
        session_id, artist_turn_id, estimated_cost,
        breakdown=[{"clip_count": clip_count, "per_clip": ..., "total": estimated_cost}]
    ))

    # 3. 构建 video plan
    plan = self._build_video_plan(action, scenes, state)
    state.video_plan = plan

    # 4. 提交 clip 任务到 provider
    tasks = []
    for i, scene in enumerate(plan.scenes):
        provider = self._select_provider(action, scene)
        task_id = await provider.submit(VideoSubmitParams(
            prompt=scene.prompt,
            reference_image=scene.reference_image or (action.reference_images[0] if action.reference_images else None),
            duration=scene.duration,
            aspect_ratio=action.video_aspect_ratio,
            camera=scene.camera or action.video_camera,
            character_reference_url=...,  # V2
        ))
        tasks.append(VideoClipRef(
            clip_index=i, task_id=task_id, provider=provider.name, status="pending", duration=scene.duration
        ))

    state.video_clips = tasks

    # 5. 启动后台轮询
    bg_task = asyncio.create_task(
        self._poll_video_tasks(session_id, artist_turn_id, state)
    )
    self._video_tasks[session_id] = bg_task

    # 6. 立即返回（无 artifact，cost 在完成时记录）
    return [], 0.0
```

### 6.5 _poll_video_tasks

```python
async def _poll_video_tasks(self, session_id, artist_turn_id, state):
    """后台轮询视频任务，SSE推送进度"""
    max_wait = 300  # 5分钟总超时
    poll_interval = 5  # 5秒轮询间隔
    elapsed = 0

    try:
        while elapsed < max_wait:
            all_done = True
            for clip in state.video_clips:
                if clip.status in ("completed", "failed"):
                    continue
                all_done = False

                try:
                    provider = self._get_provider(clip.provider)
                    result = await provider.poll(clip.task_id)

                    if result.status == "completed":
                        # 立即下载到本地（Provider URL 24-48h 过期）
                        local_path = await self._download_and_persist(result.video_url, session_id)
                        clip.url = result.video_url
                        clip.local_url = f"/static/videos/{local_path}"
                        clip.status = "completed"
                        await self.deps.event_publish(artist_clip_ready(
                            session_id, artist_turn_id, clip.clip_index, clip.local_url, clip.duration
                        ))

                    elif result.status == "failed":
                        clip.status = "failed"
                        clip.error = result.error or "generation_failed"
                        # 重试逻辑：同 provider 重试1次，换 provider 重试1次
                        await self._retry_or_degrade(clip, state)

                    # content_policy_violation
                    elif result.error_code == "content_policy_violation":
                        clip.status = "failed"
                        clip.error = "content_policy_violation"
                        await self.deps.event_publish(artist_action_failed(
                            session_id, artist_turn_id, "generate_video",
                            VideoError(
                                user_message="内容审核未通过",
                                detail="Provider rejected the prompt due to content policy",
                                suggestion="请修改描述，避免敏感内容",
                                retryable=False,
                                error_code="content_policy_violation",
                            )
                        ))

                except Exception as e:
                    logger.error(f"Poll clip {clip.clip_index} failed: {e}")

            if all_done:
                break

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # 所有 clip 完成（或失败降级）→ 合成
        completed_clips = [c for c in state.video_clips if c.status == "completed"]
        if completed_clips:
            # FFmpeg 合成
            video_url = await self._compose_clips(completed_clips, session_id, state)

            # 提取封面图
            thumbnail = await self._extract_thumbnail(video_url, session_id)

            # 创建 artifact
            artifact = ArtistArtifact(
                artifact_type="video",
                url=video_url,
                thumbnail_url=thumbnail,
                metadata={
                    "duration": sum(c.duration for c in completed_clips),
                    "clip_count": len(completed_clips),
                    "provider": completed_clips[0].provider,
                    "aspect_ratio": state.video_plan.aspect_ratio if state.video_plan else "16:9",
                },
                ...
            )

            # 记录计费
            await self._record_video_billing(completed_clips, session_id)

            # 更新 state
            state.video_url = video_url

            # SSE: 视频完成
            await self.deps.event_publish(artist_video_ready(
                session_id, artist_turn_id, video_url, artifact
            ))
        else:
            # 全部失败
            await self.deps.event_publish(artist_action_failed(
                session_id, artist_turn_id, "generate_video",
                VideoError(
                    user_message="视频生成失败",
                    detail="All clips failed",
                    suggestion="请尝试减少场景数或修改描述",
                    retryable=True,
                    error_code="all_clips_failed",
                )
            ))

    finally:
        # 清理后台 task 引用
        self._video_tasks.pop(session_id, None)
        # 确保 phase 回到 idle
        state.phase = "idle"
```

### 6.6 _execute_extract_frame

```python
async def _execute_extract_frame(self, action, session_id, artist_turn_id, state):
    """从视频提取帧→SessionImage"""
    source_url = action.source_video_url or state.video_url
    if not source_url:
        raise VideoActionError("需要指定源视频")

    time_seconds = action.frame_time or 0.0

    # FFmpeg 提取帧
    frame_path = await self.deps.extract_frame(source_url, time_seconds, session_id)
    frame_url = f"/static/frames/{frame_path}"

    artifact = ArtistArtifact(
        artifact_type="extracted_frame",
        url=frame_url,
        thumbnail_url=frame_url,
        metadata={"source_video": source_url, "frame_time": time_seconds},
        ...
    )

    await self.deps.event_publish(artist_image_ready(
        session_id, artist_turn_id, artifact
    ))

    return [artifact], 0.0
```

### 6.7 _execute_trim_video / _execute_adjust_video

```python
async def _execute_trim_video(self, action, session_id, artist_turn_id, state):
    """裁剪视频（纯 FFmpeg，不调用 provider）"""
    source_url = action.source_video_url or state.video_url
    if not source_url:
        raise VideoActionError("需要指定源视频")

    trimmed_path = await self.deps.trim_video(
        source_url, action.trim_start, action.trim_end, session_id
    )
    trimmed_url = f"/static/videos/{trimmed_path}"

    thumbnail = await self._extract_thumbnail(trimmed_url, session_id)

    artifact = ArtistArtifact(
        artifact_type="trimmed_video",
        url=trimmed_url,
        thumbnail_url=thumbnail,
        metadata={
            "source_video": source_url,
            "trim_start": action.trim_start,
            "trim_end": action.trim_end,
        },
        ...
    )

    await self.deps.event_publish(artist_video_ready(
        session_id, artist_turn_id, trimmed_url, artifact
    ))

    return [artifact], 0.0

async def _execute_adjust_video(self, action, session_id, artist_turn_id, state):
    """视频变速（纯 FFmpeg）"""
    source_url = action.source_video_url or state.video_url
    if not source_url or not action.video_speed:
        raise VideoActionError("需要指定源视频和变速倍率")

    adjusted_path = await self.deps.adjust_video_speed(
        source_url, action.video_speed, session_id
    )
    adjusted_url = f"/static/videos/{adjusted_path}"

    thumbnail = await self._extract_thumbnail(adjusted_url, session_id)

    artifact = ArtistArtifact(
        artifact_type="adjusted_video",
        url=adjusted_url,
        thumbnail_url=thumbnail,
        metadata={
            "source_video": source_url,
            "speed": action.video_speed,
        },
        ...
    )

    await self.deps.event_publish(artist_video_ready(
        session_id, artist_turn_id, adjusted_url, artifact
    ))

    return [artifact], 0.0
```

---

## 7. Video Provider 抽象

### 7.1 Adapter 模式

```python
class VideoProviderAdapter(ABC):
    name: str

    @abstractmethod
    async def submit(self, params: VideoSubmitParams) -> str:
        """提交视频生成任务，返回 task_id"""

    @abstractmethod
    async def poll(self, task_id: str) -> VideoTaskResult:
        """查询任务状态"""

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """取消任务"""

    @abstractmethod
    def estimate_cost(self, params: VideoSubmitParams) -> float:
        """预估费用"""

class VideoSubmitParams(BaseModel):
    prompt: str
    reference_image: str | None = None
    duration: float = 5.0
    aspect_ratio: str = "16:9"
    camera: str = ""
    character_reference_url: str | None = None   # V2: Minimax S2V
    element_binding: dict | None = None           # V2: Kling Element

class VideoTaskResult(BaseModel):
    status: Literal["pending", "processing", "completed", "failed"]
    video_url: str = ""
    error: str = ""
    error_code: str = ""       # "content_policy_violation" / "rate_limited" / "server_error"
```

### 7.2 Provider 路由

```python
class VideoProviderRouter:
    def select_provider(self, params: VideoSubmitParams, state: ArtistSessionState) -> VideoProviderAdapter:
        # 1. 用户指定 → 用指定的
        if params.provider:
            return self._adapters[params.provider]
        # 2. 能力匹配
        if params.character_reference_url:
            return self._adapters.get("minimax", self._default)
        if params.reference_image and not params.character_reference_url:
            return self._adapters.get("runway", self._default)
        # 3. 默认
        return self._default
```

### 7.3 V1 Provider 实现

| Provider | Adapter | 支持能力 | 优先级 |
|----------|---------|---------|--------|
| Runway Gen-4 | RunwayAdapter | T2V, I2V, V2V, keyframes | 默认 |
| Kling V3 | KlingAdapter | T2V, I2V, multi-shot | 备选 |
| Pika | PikaAdapter | T2V, I2V, scenes | 备选 |
| Luma | LumaAdapter | T2V, I2V, loop | 特定场景 |
| Minimax | MinimaxAdapter | I2V, S2V 角色一致性 | 角色场景 |

---

## 8. FFmpeg 合成

### 8.1 V1 能力

- **concat**：多 clip 顺序拼接
- **fade**：场景间淡入淡出
- **trim**：裁剪时间段
- **speed**：变速（setpts）
- **extract_frame**：提取指定时间帧
- **thumbnail**：提取首帧作为封面图

### 8.2 安全规范

```python
# 所有 FFmpeg 调用必须：
# 1. 使用 subprocess.run + 参数列表（不经过 shell）
# 2. 文件路径用 pathlib 验证（防路径遍历）
# 3. 文件名用 UUID 生成（不接受用户输入）
# 4. 设置 timeout（60秒）
# 5. 上传文件验证 magic bytes（不只是扩展名）

async def run_ffmpeg(self, args: list[str], timeout: int = 60) -> bytes:
    cmd = ["ffmpeg", *args]
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise FFmpegError(result.stderr.decode())
    return result.stdout
```

---

## 9. 计费

### 9.1 新增计费类型

```python
class BillingType(str, enum.Enum):
    per_call = "per_call"
    per_token = "per_token"
    per_video_call = "per_video_call"         # 新增：按次计费
    per_video_duration = "per_video_duration"  # 新增：按时长计费
```

### 9.2 Provider 费率配置

在 `ApiProvider` 中配置视频费率：

```python
# ApiProvider.metadata 新增
{
    "video_pricing": {
        "per_clip_cost": 0.40,          # USD per clip
        "per_second_cost": 0.08,        # USD per second (某些 provider)
        "credit_to_usd": 0.05,          # Runway credit → USD 换算
        "models": {
            "gen4_turbo": {"per_clip": 0.40},
            "gen4": {"per_clip": 0.60},
        }
    }
}
```

### 9.3 计费记录

```python
detail = {
    "type": "video_generation",
    "clip_count": 3,
    "total_duration_seconds": 15,
    "provider": "runway",
    "model": "gen4_turbo",
    "clips": [
        {"scene_index": 1, "duration": 5, "cost": 0.40, "status": "completed"},
        {"scene_index": 2, "duration": 5, "cost": 0.40, "status": "completed"},
        {"scene_index": 3, "duration": 5, "cost": 0.40, "status": "failed", "refunded": True},
    ]
}
```

### 9.4 部分失败退款

| 失败比例 | 策略 | 退款 |
|---------|------|------|
| 1/N 失败 | 跳过失败 clip，空白过渡 | 不退失败 clip |
| >50% 失败 | 只合成成功 clip | 退还失败 clip 费用 |
| 100% 失败 | 返回错误 | 全额退款 |

---

## 10. SSE 断连恢复

### 10.1 问题

视频生成 2-5 分钟，SSE 连接可能断开。断连后：
- 后台 task 继续运行（不受 SSE 影响）
- 视频完成事件丢失（无人接收）
- 用户重连后不知道视频已完成

### 10.2 方案

1. **完成事件持久化**：后台 task 完成时，在 state 中记录完成状态
2. **turn-status 端点**：`GET /api/session/{id}/artist/turn-status`
3. **前端恢复逻辑**：重连后请求 turn-status，获取最新状态

```python
# state 中新增
class ArtistSessionState(BaseModel):
    # ...
    last_video_status: dict | None = None  # {"completed": True, "video_url": "...", "artifact": {...}}
```

```python
# API 端点
@router.get("/session/{session_id}/artist/turn-status")
async def get_turn_status(session_id: str):
    state = await state_store.load(session_id)
    if state.phase == "video_generating":
        return {"status": "generating", "clips": state.video_clips}
    if state.last_video_status:
        return {"status": "completed", **state.last_video_status}
    return {"status": "idle"}
```

### 10.3 服务重启恢复

启动时扫描 video_generating 状态的 session，重置为 idle：

```python
async def cleanup_stale_video_sessions():
    sessions = await state_store.list_by_phase("video_generating")
    for session_id in sessions:
        state = await state_store.load(session_id)
        state.phase = "idle"
        state.last_video_status = {"completed": False, "error": "service_restart"}
        await state_store.save(session_id, state)
```

---

## 11. Lineage 扩展

### 11.1 SessionImage 扩展

在现有 `SessionImage` 模型上增加 `media_type` 字段，不新建 `SessionVideo` 模型：

```python
class SessionImage(BaseModel):
    # 现有字段不变
    id: str
    session_id: str
    url: str
    prompt: str = ""
    # ...

    # 新增
    media_type: Literal["image", "video"] = "image"
    duration: float | None = None          # 视频时长（秒）
    thumbnail_url: str = ""                # 视频封面图
    video_clips: list[dict] | None = None  # clip 信息
```

### 11.2 Lineage 关系

视频与图像共享同一 lineage 树：

```
img-001 (anchor: 赛博朋克城市)
  └── img-002 (refine: 色调调整)
      └── vid-001 (video: img-002 → I2V 5秒视频, parent=img-002, root=img-001)
          ├── vid-002 (video: 风格迁移→暗调, parent=vid-001, root=img-001)
          ├── vid-003 (video: 延长到15秒, parent=vid-001, root=img-001)
          └── vid-004 (video: clip 1替换, parent=vid-001, root=img-001)

vid-001 → frm-001 (extracted_frame: 3秒处, parent=vid-001, root=img-001)
  └── img-003 (refine: 帧精修, parent=frm-001, root=img-001)
      └── vid-005 (video: 用精修帧重新生成clip, parent=img-003, root=img-001)
```

回退 = 切换 HEAD 到任意节点（与图像 lineage 完全同构）。

---

## 12. 前端变更

### 12.1 新增组件

| 组件 | 职责 | 版本 |
|------|------|------|
| `VideoPlayer.vue` | 视频播放器：播放/暂停/进度/下载 | V1 |
| `VideoProgressPanel.vue` | 视频生成进度面板：clip进度/预计时间/取消 | V1 |
| `VideoCoverCard.vue` | 聊天中视频展示：封面图+播放按钮+时长标签 | V1 |

### 12.2 修改组件

| 组件 | 修改内容 |
|------|---------|
| `ArtistImageMessageCard.vue` | 扩展为媒体感知：视频用 VideoCoverCard 渲染 |
| `Lightbox.vue` | 扩展视频播放模式：`<video>` + 播放控制 |
| `LineageNode.vue` | 增加 media_type + thumbnail_url，视频节点显示 ▶ 图标 + 时长 |
| `ComposerControls.vue` | accept 扩展支持视频文件拖拽 |
| `useDownload.ts` | 扩展 .mp4/.webm/.mov 文件名映射 |
| `session.ts` | ArtistStreamState 增加 generating 状态，处理新 SSE 事件 |

### 12.3 视频在聊天中的展示

聊天中视频显示为**封面图 + 播放按钮覆盖 + 时长标签**：

```
┌──────────────────────────┐
│                          │
│    [封面图/首帧]          │
│                          │
│         ▶ 播放           │
│                          │
│    0:05 · 1080p          │
└──────────────────────────┘
```

点击后展开为内联播放器，或打开 Lightbox 全屏播放。

### 12.4 视频与图像的视觉区分

- LineageNode：视频节点 → ▶ 图标覆盖 + "0:05" 时长标签
- 聊天卡片：视频卡片 → ▶ 图标 + 时长标签
- 统一视觉语言：视频 = 图像 + ▶ 图标 + 时长

---

## 13. 安全

### 13.1 视频文件上传安全

- 上传时验证文件头（magic bytes），不只是扩展名
- 限制上传大小（100MB）
- FFmpeg 操作在沙箱/容器中执行（V2）
- 上传后先 probe 视频信息（时长/分辨率/编码），不符合要求的拒绝

### 13.2 FFmpeg 命令注入防护

- 使用 `subprocess.run` + 参数列表（不经过 shell）
- 文件路径用 pathlib 验证
- 文件名用 UUID 生成（不接受用户输入）
- 设置 timeout

### 13.3 Prompt 注入防护

- 错误信息中不回显用户原始 prompt
- video_scenes 的每个字段做 sanitize
- 前端渲染视频元数据时做 HTML 转义

### 13.4 路径遍历防护

```python
filename = f"{uuid4().hex}.mp4"
path = BASE_DIR / session_id / filename
assert path.resolve().parent == (BASE_DIR / session_id).resolve()
```

---

## 14. 存储管理

### 14.1 Provider URL 临时性

Provider 返回的视频 URL 24-48 小时过期。**必须在视频完成时立即下载到本地存储**：

```python
async def _download_and_persist(self, url: str, session_id: str) -> str:
    filename = f"{uuid4().hex}.mp4"
    path = VIDEO_DIR / session_id / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        path.write_bytes(resp.content)
    return f"{session_id}/{filename}"
```

### 14.2 视频存储 TTL

- 30天未访问的视频自动清理（V1 手动，V2 自动）
- 清理时保留 artifact 记录（thumbnail_url），只删除视频文件
- 用户点击时提示"视频已过期，是否重新生成"

---

## 15. 功能场景清单

### 15.1 V1 支持的场景

| # | 场景 | Action | 说明 |
|---|------|--------|------|
| 1 | T2V 文生视频 | generate_video | prompt only |
| 2 | I2V 图生视频 | generate_video | prompt + reference_images |
| 3 | V2V 风格迁移 | generate_video | prompt + source_video_url |
| 4 | V2V 运动修改 | generate_video | prompt + source_video_url + clip_index |
| 5 | 视频延长 | generate_video | prompt + extend_from_url |
| 6 | 多场景分镜视频 | generate_video | video_scenes × N |
| 7 | 局部 clip 重生成 | generate_video | clip_index |
| 8 | 多图→视频 | generate_video | reference_images（多图） |
| 9 | 角色一致性 | generate_video | reference_images（角色参考图） |
| 10 | 帧提取→精修→重生成 | extract_frame → refine → generate_video | 双向创作循环 |
| 11 | 视频裁剪 | trim_video | trim_start / trim_end |
| 12 | 视频变速 | adjust_video | video_speed |
| 13 | 费用预估+确认 | ask_clarification | 复用现有 phase |
| 14 | 部分失败降级 | 自动处理 | 跳过失败 clip / 退款 |
| 15 | 视频下载 | 前端按钮 | download API |

### 15.2 降级与异常场景

| 场景 | 处理方式 | 用户感知 |
|------|---------|---------|
| 1/N clip 失败 | 跳过失败 clip，空白过渡 | 视频有短暂空白 |
| >50% clip 失败 | 只合成成功 clip | 视频明显缩短，失败 clip 退款 |
| 全部失败 | 返回错误信息 | 无视频，全额退款 |
| 内容审核拒绝 | 友好提示 + 建议修改 | "内容审核未通过，请修改描述" |
| Provider 限流 429 | 指数退避 + 抖动重试 | 延迟增加 |
| SSE 断连 | turn-status 端点恢复 | 重连后可获取最新状态 |
| 服务重启 | 启动时清理 video_generating | 提示"视频生成中断" |
| 并发 turn | per-session Lock 拒绝 | "上一个任务还在执行中" |

---

## 16. 文件变更清单

### 16.1 新增文件（5 个后端 + 3 个前端）

| 文件 | 职责 |
|------|------|
| `backend/app/utils/video_client.py` | VideoClient：submit/poll/cancel/extract_frame，Provider Adapter 实现 |
| `backend/app/services/video_composer.py` | FFmpeg 合成：concat + fade + trim + speed + extract_frame + thumbnail |
| `backend/app/services/video_provider_router.py` | Provider 路由策略 |
| `backend/app/core/artist/video_errors.py` | VideoError / VideoActionError 统一错误定义 |
| `backend/app/routers/video.py` | turn-status 端点 + 视频下载 API |
| `frontend/src/components/session/VideoPlayer.vue` | 视频播放器组件 |
| `frontend/src/components/session/VideoProgressPanel.vue` | 视频生成进度面板 |
| `frontend/src/components/session/VideoCoverCard.vue` | 聊天中视频封面卡片 |

### 16.2 修改文件（10 个后端 + 8 个前端）

**后端**：

| 文件 | 修改内容 |
|------|---------|
| `schemas.py` | ArtistActionType +4, ArtistAction +12 字段, ArtistSessionState +3 字段, ArtistArtifact +2 字段 |
| `runtime.py` | _execute_video_action, _execute_extract_frame, _execute_trim_video, _execute_adjust_video, _poll_video_tasks, per-action try/except, per-session Lock |
| `transitions.py` | idle→video_generating, waiting_clarification→video_generating, video_generating→idle |
| `events.py` | +5 事件构造函数 |
| `turn_parser.py` | action 互斥校验 |
| `state_store.py` | cleanup_stale_video_sessions |
| `models/billing.py` | BillingType +2, ProviderType +1 |
| `models/session.py` | SessionImage +media_type/duration/thumbnail_url/video_clips |
| `services/generate_service.py` | _run_artist_orchestrate 传入 video deps |
| `routers/session.py` | turn-status 端点 |

**前端**：

| 文件 | 修改内容 |
|------|---------|
| `ArtistImageMessageCard.vue` | 媒体感知：视频用 VideoCoverCard |
| `Lightbox.vue` | 视频播放模式 |
| `LineageNode.vue` | media_type + thumbnail + ▶ 图标 |
| `ComposerControls.vue` | accept 扩展视频文件 |
| `useDownload.ts` | .mp4/.webm/.mov 映射 |
| `session.ts` | ArtistStreamState generating 状态，新 SSE 事件处理 |
| `SSE handler` | artist_turn_submitted / artist_clip_ready / artist_video_ready / artist_cost_estimate / artist_action_failed |
| `api-client.ts` | turn-status API + 视频下载 API |

---

## 17. V1 设计增量汇总

| 维度 | 现有 | V1 新增 | 总计 |
|------|------|---------|------|
| Action 类型 | 8 | +4 | 12 |
| Phase | 5 | +1 | 6 |
| SSE 事件 | 6 | +5 | 11 |
| Artifact 类型 | 6 | +4 | 10 |
| 新后端文件 | — | +5 | 5 |
| 新前端文件 | — | +3 | 3 |
| 修改后端文件 | — | +10 | 10 |
| 修改前端文件 | — | +8 | 8 |
| ArtistAction 字段 | 7 | +12 | 19 |
| ArtistArtifact 字段 | 11 | +2 | 13 |
| ArtistSessionState 字段 | 14 | +3 | 17 |
| 新增 Pydantic 模型 | — | +4 | 4 |
| 新增 ABC | — | +1 | 1 |

**总新增代码量估算**：~2500 行后端 + ~800 行前端

---

## 18. 版本路线图

### V1 — 视频生成基础

- T2V / I2V / V2V / 延长 / 多图→视频
- 多场景分镜 + 局部 clip 重生成
- 帧提取 → 精修 → 重生成（双向创作循环）
- 视频裁剪 / 变速
- 费用预估 + 确认
- 部分失败降级 + 重试
- SSE 断连恢复
- 视频下载
- Provider Adapter（Runway + Kling）

### V2 — 短剧基础 + 3D 布局

- DramaProject 数据模型
- 角色管理（多角色 + 服装）
- 分镜脚本生成（Storyboard 结构化输出）
- **3D 空间布局编辑器**（2.5D 等轴测画布 + 高度标注 + 摄像机放置 + Layout3DPromptTranslator）
- 场景模板库
- 字幕叠加（FFmpeg ASS）
- TTS 对白
- 背景音乐
- 循环视频
- 角色一致性（Minimax S2V / Kling Element）
- Webhook handler（Kling/Pika/Luma/Minimax）
- DramaProjectPanel.vue（前端项目管理）

### V3 — 短剧专业

- 非线性剪辑（Timeline 多轨道）
- 平行剪辑 / 闪回 / 蒙太奇
- 口型同步
- 3D 布局增强（区域/楼层/楼梯 + 摄像机运动路径）
- 视频对比 UI
- GIF 导出
- 中途干预修改
- 多版本视频（video_count）
- API 端点暴露

### 永远不做

- 实时 3D 渲染引擎
- 协作编辑
- 游戏引擎级 3D 场景

---

## 19. 3D 空间布局编辑器（V2 详细设计）

### 19.1 核心定位

3D 布局编辑器不是 3D 渲染引擎，而是**能标注高度信息的空间布局工具**。用户在 2.5D 等轴测画布上摆放元素、标注朝向和高度，Artist 读取布局信息生成视频。

### 19.2 数据模型

```python
class LayoutElement3D(BaseModel):
    """3D 空间中的元素"""
    id: str
    name: str
    type: Literal["character", "object", "marker", "camera"]

    # 3D 坐标（归一化 0-1）
    x: float = 0.5                    # 左右
    y: float = 0.5                    # 前后（深度）
    z: float = 0.0                    # 高度（0=地面, 1=天花板）

    # 朝向
    rotation: float = 0.0             # 水平朝向 (0-360°)
    pitch: float = 0.0               # 俯仰角 (-90=低头, 0=平视, 90=仰头)

    # 尺寸（归一化）
    width: float = 0.05
    depth: float = 0.05
    height: float = 0.15             # 角色约 1.7m/层高 3m ≈ 0.15

    # 关联
    character_id: str | None = None
    outfit_id: str | None = None

class LayoutCamera3D(BaseModel):
    """3D 空间中的摄像机"""
    id: str
    name: str
    x: float = 0.5
    y: float = 0.5
    z: float = 0.08                  # 人眼高度 ≈ 1.6m/3m
    rotation: float = 0.0
    pitch: float = 0.0
    fov: str = "medium"              # "wide"/"medium"/"narrow"
    shot_type: str = "medium"

class LayoutZone(BaseModel):
    """空间区域（楼梯/夹层/吧台区）"""
    id: str
    name: str
    x: float
    y: float
    z: float                         # 区域基准高度
    width: float
    depth: float
    height: float
    zone_type: str = ""              # "stairs"/"platform"/"loft"/"counter"

class SceneLayout3D(BaseModel):
    """3D 场景布局"""
    id: str
    name: str
    room_width: float = 8.0          # 米
    room_depth: float = 10.0
    room_height: float = 3.0
    elements: list[LayoutElement3D] = []
    cameras: list[LayoutCamera3D] = []
    zones: list[LayoutZone] = []
    background_prompt: str = ""
```

### 19.3 前端实现

- **技术栈**：SVG + CSS transform（等轴测投影），不需要 Three.js
- **三种视图**：俯视（快速布局 x/y）、透视（2.5D 看高度关系）、侧视（精确调整 z）
- **交互**：拖拽放置、旋转朝向、命名标注、关联角色、摄像机放置
- **实现量**：~600 行前端

```typescript
// 等轴测投影：3D 坐标 → 2D 屏幕坐标
function isoProject(x: number, y: number, z: number): { sx: number; sy: number } {
    const sx = (x - y) * Math.cos(Math.PI / 6) * SCALE
    const sy = (x + y) * Math.sin(Math.PI / 6) * SCALE - z * SCALE
    return { sx, sy }
}
```

### 19.4 Layout3DPromptTranslator

将 3D 布局信息翻译成视频生成 prompt：

```python
class Layout3DPromptTranslator:
    def translate_shot(self, layout: SceneLayout3D, camera: LayoutCamera3D) -> dict:
        # 1. 计算摄像机视野内的元素
        visible = self._get_visible_elements(layout, camera)
        # 2. 确定景别和摄像机角度
        shot_type = self._infer_shot_type(camera, visible)
        camera_angle = self._infer_camera_angle(camera)
        # 3. 生成 3D 空间关系描述
        spatial_parts = [self._spatial_relation_3d(e, camera, layout) for e in visible]
        # 4. 组合 prompt
        prompt = f"{layout.background_prompt}, {', '.join(spatial_parts)}"
        return {
            "prompt": prompt,
            "camera_movement": self._camera_description(camera),
            "shot_type": shot_type,
            "camera_angle": camera_angle,
            "character_references": self._collect_references(visible),
        }
```

翻译示例：

```
布局: 咖啡厅 8m×10m×3m
  小明: x=0.3, y=0.4, z=0.0, rotation=90°(朝右)
  咖啡师: x=0.6, y=0.3, z=0.0, rotation=270°(朝左)
  摄像机"全景": x=0.1, y=0.1, z=0.08

翻译结果:
  prompt: "Coffee shop interior, warm lighting,
           Xiaoming in the center-right facing right,
           barista behind the counter in the right facing left"
  shot_type: "wide"
  camera_angle: "eye_level"
```

### 19.5 与短剧的集成

```
1. 用户创建 3D 场景布局
2. 分镜脚本引用布局中的摄像机
3. Layout3DPromptTranslator 翻译每个镜头
4. 逐镜头生成视频（带精确空间描述 + 角色参考图）
5. 合成成片
```

---

## 20. AI 短剧编排（V2 详细设计）

### 20.1 核心洞察

AI 短剧不是"一次性生成"，而是**分阶段渐进式创作**。每个阶段是一个独立的 Artist turn，用户在每个阶段都可以干预和修改。

### 20.2 创作阶段

```
阶段 1: 故事构思（纯对话）
  → Artist 输出故事大纲 + 角色设定 + 场景列表

阶段 2: 角色设计（图像生成）
  → generate_anchor × N → 角色参考图

阶段 3: 场景布局（3D 布局编辑器）
  → 用户在编辑器中摆放元素和摄像机

阶段 4: 分镜脚本（结构化输出）
  → Artist 输出 Storyboard JSON → 用户确认/修改

阶段 5: 镜头生成（视频生成）
  → 逐镜头 generate_video → 每个镜头带角色参考图 + 布局信息

阶段 6: 剪辑编排（合成）
  → compose_video with transitions

阶段 7: 后期（音频/字幕）
  → TTS + FFmpeg 字幕叠加
```

### 20.3 数据模型

```python
class DramaProject(BaseModel):
    """短剧项目 — 跨 turn 持久化"""
    id: str
    title: str
    synopsis: str = ""
    characters: list[Character] = []
    scenes: list[StoryScene] = []
    storyboard: Storyboard | None = None
    shots: list[ShotResult] = []
    timeline: Timeline | None = None
    status: Literal[
        "concept", "casting", "layout", "storyboarding",
        "shooting", "editing", "post", "done"
    ] = "concept"

class Character(BaseModel):
    id: str
    name: str
    description: str
    reference_images: list[str] = []
    outfits: list[Outfit] = []

class Outfit(BaseModel):
    id: str
    name: str
    description: str
    reference_images: list[str] = []

class Shot(BaseModel):
    id: str
    shot_type: str                   # "wide"/"medium"/"close_up"/"extreme_close_up"
    camera_angle: str                # "eye_level"/"high"/"low"/"over_shoulder"
    camera_movement: str             # "static"/"pan_left"/"dolly_in"/"tracking"
    character_id: str | None = None
    outfit_id: str | None = None
    action: str = ""
    dialogue: str | None = None
    duration: float = 3.0
    prompt: str = ""
    layout_camera_id: str | None = None  # 引用 3D 布局中的摄像机

class StoryScene(BaseModel):
    id: str
    location: str                    # "INT. 咖啡厅 - 日"
    layout_id: str | None = None     # 引用 3D 布局
    shots: list[Shot] = []
    ambient: str | None = None

class Storyboard(BaseModel):
    title: str
    scenes: list[StoryScene]
    characters: list[Character]
    total_duration: float

class ShotResult(BaseModel):
    shot_id: str
    video_url: str = ""
    status: Literal["pending", "generating", "completed", "failed"] = "pending"
    character_id: str | None = None
    outfit_id: str | None = None
```

### 20.4 短剧交互流程示例

```
Turn 1: 故事构思
  用户: "做一个30秒的咖啡厅邂逅短剧"
  Artist: "30秒邂逅||大概5-6个镜头||先定角色"
  → DramaProject.status="concept"

Turn 2: 角色设计
  用户: "设计两个角色，一个穿正装的商务人士，一个穿休闲装的咖啡师"
  Artist: generate_pack(2张角色参考图)
  → DramaProject.status="casting", characters=[...]

Turn 3: 场景布局（V2: 3D 编辑器）
  用户: "布局一下咖啡厅"
  → 打开 SceneLayoutEditor3D
  → 用户摆放角色、吧台、摄像机
  → DramaProject.status="layout"

Turn 4: 分镜脚本
  用户: "生成分镜脚本"
  Artist: 输出 Storyboard JSON（6个镜头，引用布局中的摄像机）
  → DramaProject.status="storyboarding"

Turn 5: 镜头生成
  用户: "开始生成"
  Artist: generate_video with video_scenes=[...6个镜头...]
  → 逐镜头异步生成，每个带角色参考图
  → SSE: artist_clip_ready × 6
  → SSE: artist_video_ready
  → DramaProject.status="shooting"

Turn 6: 迭代修改
  用户: "第三个镜头不好，咖啡师表情要更热情"
  Artist: generate_video(clip_index=2, character_id="barista")
  → 重新生成镜头3 → 重新合成
```

---

## 附录 A: 已识别的不足与修订记录

### 6 轮深度分析 + 5 轮批判性审查

| 轮次 | 维度 | 发现数 | 关键修订 |
|------|------|--------|---------|
| R1 | 视频能力定位 | — | Video 是 Artist action，不是独立 Agent |
| R2 | 全链路设计 | — | plan→keyframes→clips→compose→iterate |
| R3 | 用户场景模拟 | 6 个 | 4 个完全可行，2 个部分可行 |
| R4 | 文件/代码映射 | 14+6 | 精确到文件级别的变更清单 |
| R5 | 风险分析 | — | V1 范围裁剪 |
| R6 | 能力图+分支策略 | — | 设计原则确立 |
| R7 | 补充设计 | 5 个 | V2V/局部重生成/计费/降级/帧提取 |
| R8 | 交互模型 | 4 个 | 单turn+异步后台、turn_submitted、混合action互斥、费用确认竞态 |
| R9 | 数据模型 | 5 个 | VideoClipRef/VideoScene/VideoPlan强类型、thumbnail必填、lineage兼容 |
| R10 | 安全性 | 5 个 | FFmpeg注入防护、文件上传安全、prompt注入、路径遍历 |
| R11 | 可扩展性 | 5 个 | Provider Adapter、video_scenes校验、FFmpeg Pipeline、前端分层 |
| R12 | 用户体验 | 5 个 | 进度面板、聊天视频展示、视觉区分、编辑入口、失败引导 |
| R13 | AI短剧 | — | DramaProject模型、分阶段创作、角色/服装/分镜 |
| R14 | 3D布局 | — | 2.5D等轴测画布、Layout3DPromptTranslator、高度标注 |

### 关键架构决策记录

| # | 决策 | 理由 |
|---|------|------|
| 1 | 单 turn + 异步后台 | 不阻塞、有进度反馈、架构改动小 |
| 2 | 1 个 action 覆盖 5 种模式 | 通过字段区分，避免 action 膨胀 |
| 3 | 0 新 phase（video_generating 除外） | 复用现有 phase 机制 |
| 4 | video_scenes: list[dict] | LLM 输出不可控，松输入紧内部 |
| 5 | per-action try/except | 修复现有架构缺陷 |
| 6 | per-session asyncio.Lock | 防止并发 turn 导致 state 混乱 |
| 7 | download-on-success | Provider URL 24-48h 过期 |
| 8 | SessionImage + media_type | 不新建 SessionVideo，复用 lineage 逻辑 |
| 9 | 3D 布局用 SVG + CSS transform | 不需要 Three.js，2.5D 等轴测足够 |
| 10 | 短剧分阶段渐进式创作 | 每个 turn 一个阶段，用户可干预 |
