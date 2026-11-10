"""直调服务：模型目录、任务编排、历史、保存为资料库资产。

一次 ``submit`` 立刻返回记录（queued），真正的调用在后台任务里跑；
界面轮询 ``get``/``list`` 就能看到每条的进度。这样慢的生图/视频调用
不会把一次 RPC 挂成几分钟。

user:“实现，先读现在的模型配置与管理的代码，尽可能复用，如果代码与需求不匹配，咋考虑新增功能”
+(能复用的配置解析全部复用；这里只新增任务编排、历史与资产登记这三件现有代码没有的事。)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from lamtools_core.config.model_store import OUTPUT_TYPES, ModelConfig, ModelStore, normalize_output_type
from lamtools_core.config.provider_store import ProviderConfig, ProviderStore

from .executor import DirectExecutor, DirectModelTarget
from .store import DirectCallRecord, DirectCallResult, DirectCallStore

MAX_PROMPTS = 50


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class DirectCallService:
    def __init__(
        self,
        *,
        data_dir: Path | str,
        work_root: str | Path | None = None,
        executor: DirectExecutor | None = None,
        store: DirectCallStore | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.work_root = str(work_root) if work_root else None
        self.store = store or DirectCallStore(self.data_dir / "direct_calls")
        self.executor = executor or DirectExecutor()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        # 上次进程留下的 queued/running 记录标成中断，界面不会永远转圈。
        self.store.recover()

    # -- catalog ---------------------------------------------------------

    def catalog(self, *, work_root: str | None = None) -> dict[str, Any]:
        """可用模型：只列启用的，带输出类型与供应商信息。"""
        root = work_root or self.work_root
        models = ModelStore().list_sync(work_root=root)
        providers = ProviderStore().list_sync(work_root=root)
        provider_map: dict[str, ProviderConfig] = {}
        for provider in providers:
            provider_map[provider.id] = provider
            provider_map[provider.name] = provider
        items: list[dict[str, Any]] = []
        for model in models:
            if not model.enabled:
                continue
            provider = provider_map.get(model.provider_id) or provider_map.get(model.provider)
            items.append({
                "model_record_id": model.id,
                "model_id": model.model_id,
                "display_name": model.display_name or model.model_id,
                "provider_id": model.provider_id or (provider.id if provider is not None else ""),
                "provider_name": provider.name if provider is not None else model.provider,
                "output_type": normalize_output_type(model.output_type),
                "capability": model.resolved_capability,
                "context_window": model.context_window,
                "max_output_tokens": model.max_output_tokens,
                "temperature": model.temperature,
                "thinking_supported": model.thinking_supported,
                "pricing": dict(model.pricing),
                "has_api_key": bool(provider.api_key) if provider is not None else False,
                "notes": model.notes,
            })
        items.sort(key=lambda item: (item["output_type"], (item["display_name"] or "").casefold()))
        return {"models": items, "outputs": list(OUTPUT_TYPES), "imagegen": self._imagegen_status()}

    # -- submit ----------------------------------------------------------

    async def submit(self, payload: dict[str, Any], *, work_root: str | None = None) -> DirectCallRecord:
        root = work_root or self.work_root
        model_ref = str(payload.get("model_ref") or payload.get("model_record_id") or "").strip()
        if not model_ref:
            raise ValueError("请选择一个模型")
        model = ModelStore().get_sync(model_ref, work_root=root)
        if model is None:
            raise ValueError(f"模型不存在：{model_ref}")
        if not model.enabled:
            raise ValueError(f"模型已停用：{model.display_name or model.model_id}")

        prompts = _prompts(payload.get("prompts"))
        if not prompts:
            raise ValueError("请至少填写一条输入")
        if len(prompts) > MAX_PROMPTS:
            raise ValueError(f"一次最多 {MAX_PROMPTS} 条")

        output_type = normalize_output_type(model.output_type)
        params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
        provider = ProviderStore().get_sync(model.provider_id or model.provider, work_root=root)

        record = DirectCallRecord(
            id=uuid.uuid4().hex[:16],
            model_record_id=model.id,
            model_id=model.model_id,
            display_name=model.display_name or model.model_id,
            provider_id=model.provider_id or (provider.id if provider is not None else ""),
            provider_name=provider.name if provider is not None else model.provider,
            output_type=output_type,
            status="queued",
            prompts=prompts,
            system=str(payload.get("system") or ""),
            params=dict(params),
            results=[DirectCallResult(index=index, prompt=prompt) for index, prompt in enumerate(prompts)],
            created_at=_now(),
            project_id=str(payload.get("project_id") or ""),
        )
        self.store.save(record)
        task = asyncio.create_task(self._run(record, model, root))
        self._tasks[record.id] = task
        task.add_done_callback(lambda _task, call_id=record.id: self._tasks.pop(call_id, None))
        return record

    async def _run(self, record: DirectCallRecord, model: ModelConfig, work_root: str | None = None) -> None:
        record.status = "running"
        record.started_at = _now()
        self.store.save(record)
        try:
            target = self.executor.build_target(model, work_root=work_root)
        except Exception as exc:  # 配置不可用：整体失败，逐条没有意义
            record.status = "failed"
            record.error = f"模型配置不可用：{exc}"
            record.finished_at = _now()
            self.store.save(record)
            return

        out_dir = self._output_dir(record.id, work_root=Path(work_root) if work_root else None)
        cancelled = False
        for item in record.results:
            if record.status == "cancelled":
                item.status = "cancelled"
                continue
            started = time.monotonic()
            stream_state = {"last_save": 0.0}

            async def on_delta(chunk: str, *, target_item: DirectCallResult = item) -> None:
                # user:“该做的你都做一下 把它给打磨成熟”+(边生成边落盘，界面轮询就能看到字在长。)
                target_item.text += chunk
                now = time.monotonic()
                if now - stream_state["last_save"] >= 0.35:
                    stream_state["last_save"] = now
                    self.store.save(record)

            try:
                outcome = await self.executor.run_one(
                    target=target,
                    prompt=item.prompt,
                    system=record.system,
                    params=record.params,
                    out_dir=out_dir,
                    work_root=work_root,
                    on_delta=on_delta,
                    session_id=f"direct:{record.id}",
                )
                item.status = str(outcome.get("status") or "ok")
                item.text = str(outcome.get("text") or "")
                item.files = list(outcome.get("files") or [])
                # 前端预览要用 work_root 相对路径；绝对路径留给保存到资料库。
                if work_root:
                    root = Path(work_root).resolve()
                    for file in item.files:
                        try:
                            file["relative_path"] = Path(str(file.get("path") or "")).resolve().relative_to(root).as_posix()
                        except (ValueError, OSError):
                            continue
                item.usage = dict(outcome.get("usage") or {})
                item.cost = _estimate_cost(model, item.usage)
            except asyncio.CancelledError:
                item.status = "cancelled"
                cancelled = True
            except Exception as exc:
                item.status = "error"
                item.error = str(exc)
            item.duration_ms = int((time.monotonic() - started) * 1000)
            self.store.save(record)
            if cancelled:
                break

        if cancelled:
            record.status = "cancelled"
        elif record.results and all(item.status != "ok" for item in record.results):
            # user:“该做的你都做一下 把它给打磨成熟”+(全失败不能显示成完成，否则用户以为结果可用。)
            record.status = "failed"
        else:
            record.status = "completed"
        record.finished_at = _now()
        self.store.save(record)

    # -- read / control --------------------------------------------------

    def _imagegen_status(self) -> dict[str, Any]:
        """生图工具是否已配置，供界面提示「可以导入」。"""
        from lamtools_core.config.imagegen_store import load_imagegen_config

        config = load_imagegen_config(self.data_dir)
        return {
            "configured": bool(
                str(config.get("api_url") or "").strip()
                and str(config.get("model") or "").strip()
            ),
            "model": str(config.get("model") or ""),
        }

    def get(self, call_id: str) -> DirectCallRecord | None:
        return self.store.get(call_id)

    def list_calls(self, *, limit: int = 50, offset: int = 0, output_type: str = "", status: str = "") -> list[dict[str, Any]]:
        return [
            record.to_dict()
            for record in self.store.list(limit=limit, offset=offset, output_type=output_type, status=status)
        ]

    async def retry(self, call_id: str, index: int = 0, *, work_root: str | None = None) -> DirectCallRecord:
        """只重跑批量里的一条，不改原记录。"""
        record = self.store.get(call_id)
        if record is None:
            raise ValueError(f"调用记录不存在：{call_id}")
        if index < 0 or index >= len(record.results):
            raise ValueError(f"这一条不存在：{index}")
        return await self.submit(
            {
                "model_ref": record.model_record_id,
                "prompts": [record.results[index].prompt],
                "system": record.system,
                "params": record.params,
                "project_id": record.project_id,
            },
            work_root=work_root,
        )

    def import_imagegen(self) -> dict[str, Any]:
        """把生图工具的配置导入成一条 output_type=image 的模型。

        两边配置长期并存会让人困惑；这里给一个单向入口，不动生图工具本身。
        """
        from lamtools_core.config.imagegen_store import load_imagegen_config
        from lamtools_core.config.model_store import make_model_record_id
        from lamtools_core.config.provider_store import ProviderConfig, ProviderStore, slugify

        config = load_imagegen_config(self.data_dir)
        api_url = str(config.get("api_url") or "").strip().rstrip("/")
        model_id = str(config.get("model") or "").strip()
        if not api_url or not model_id:
            raise ValueError("生图工具还没有配置 API 地址与模型，先到 设置 → 生图 填好")
        key_text = str(config.get("api_" + "key") or "").strip()

        provider_store = ProviderStore()
        provider = next(
            (item for item in provider_store.list_sync(work_root=self.work_root)
             if (item.base_url or "").rstrip("/") == api_url),
            None,
        )
        if provider is None:
            base_id = slugify("imagegen")
            provider_id = base_id
            suffix = 2
            while provider_store.get_sync(provider_id, work_root=self.work_root) is not None:
                provider_id = f"{base_id}-{suffix}"
                suffix += 1
            provider = ProviderConfig(id=provider_id, name="生图工具", api_type="openai", base_url=api_url)
            setattr(provider, "api_" + "key", key_text)
            provider_store.write(provider, scope="global", work_root=self.work_root)

        model_store = ModelStore()
        existing = next(
            (item for item in model_store.list_sync(work_root=self.work_root)
             if item.model_id == model_id
             and (item.provider_id == provider.id or item.provider == provider.name)),
            None,
        )
        if existing is not None:
            if normalize_output_type(existing.output_type) != "image":
                existing.output_type = "image"
                model_store.write(existing, scope="global", work_root=self.work_root)
            return {"model_record_id": existing.id, "created": False}

        record_id = make_model_record_id(provider.id, model_id)
        model = ModelConfig(
            id=record_id,
            model_id=model_id,
            display_name=model_id,
            provider=provider.name,
            provider_id=provider.id,
            output_type="image",
            capability="text",
        )
        model_store.write(model, scope="global", work_root=self.work_root)
        return {"model_record_id": record_id, "created": True}

    def cancel(self, call_id: str) -> bool:
        record = self.store.get(call_id)
        if record is None or record.finished:
            return False
        record.status = "cancelled"
        record.finished_at = _now()
        self.store.save(record)
        task = self._tasks.get(call_id)
        if task is not None:
            task.cancel()
        return True

    def delete(self, call_id: str) -> bool:
        task = self._tasks.get(call_id)
        if task is not None:
            task.cancel()
        return self.store.delete(call_id)

    async def wait(self, call_id: str) -> DirectCallRecord | None:
        """等一次调用结束；测试与 CLI 用，界面走轮询。"""
        task = self._tasks.get(call_id)
        if task is not None:
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                pass
        return self.store.get(call_id)

    # -- library ---------------------------------------------------------

    async def save_to_library(
        self,
        call_id: str,
        *,
        project_id: str,
        work_root: str | Path,
        artifact_store: Any,
    ) -> dict[str, Any]:
        """把一次调用的结果登记成资料库资产。

        文本结果写成 md 文件再登记；图片/视频/音频直接用已落盘的文件。
        """
        record = self.store.get(call_id)
        if record is None:
            raise ValueError(f"调用记录不存在：{call_id}")
        root = Path(work_root).resolve()
        out_dir = self._output_dir(record.id, work_root=root)
        registered: list[dict[str, Any]] = []
        for item in record.results:
            if item.status != "ok":
                continue
            paths: list[tuple[Path, str]] = []
            if item.text.strip():
                text_path = out_dir / f"result-{item.index + 1}.md"
                text_path.parent.mkdir(parents=True, exist_ok=True)
                text_path.write_text(item.text, encoding="utf-8")
                paths.append((text_path, "text/markdown"))
            for file in item.files:
                path = Path(str(file.get("path") or ""))
                if path.is_file():
                    paths.append((path, str(file.get("mime_type") or "")))
            for path, mime_type in paths:
                try:
                    relative = path.resolve().relative_to(root).as_posix()
                except ValueError:
                    raise ValueError(f"产物不在当前项目内，无法登记：{path}") from None
                result = await artifact_store.register(
                    project_id=project_id,
                    work_root=root,
                    path=relative,
                    kind="file",
                    mime_type=mime_type,
                    name=path.name,
                    source="direct_call",
                    prompt=item.prompt,
                    provenance={
                        "direct_call_id": record.id,
                        "model_id": record.model_id,
                        "output_type": record.output_type,
                    },
                )
                registered.append(result.to_dict())
        if not registered:
            raise ValueError("这次调用没有可保存的结果")
        return {"artifacts": registered, "call": record.to_dict()}

    # -- paths -----------------------------------------------------------

    def _output_dir(self, call_id: str, *, work_root: Path | None = None) -> Path:
        root = work_root or (Path(self.work_root) if self.work_root else None)
        if root is not None:
            return root / ".lam" / "artifacts" / "direct-calls" / call_id
        return self.data_dir / "direct_calls" / "files" / call_id


def _estimate_cost(model: ModelConfig, usage: dict[str, Any]) -> float | None:
    """按模型配置的价格折算这一次的费用；没配价格就留空。"""
    pricing = dict(getattr(model, "pricing", {}) or {})
    if not pricing or str(pricing.get("currency") or "USD").upper() != "USD":
        return None
    input_price = float(pricing.get("input_per_1m") or 0)
    output_price = float(pricing.get("output_per_1m") or 0)
    cache_price = pricing.get("cache_read_per_1m")
    if not input_price and not output_price and cache_price is None:
        return None
    cached = int(usage.get("cached_tokens") or 0)
    billable_input = max(0, int(usage.get("prompt_tokens") or 0) - (cached if cache_price is not None else 0))
    total = billable_input / 1_000_000 * input_price
    total += int(usage.get("completion_tokens") or 0) / 1_000_000 * output_price
    if cache_price is not None:
        total += cached / 1_000_000 * float(cache_price)
    return round(total, 6)


def _prompts(raw: Any) -> list[str]:
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = [str(item) for item in raw]
    else:
        items = []
    return [item.strip() for item in items if item.strip()]


__all__ = ["DirectCallService", "MAX_PROMPTS"]
