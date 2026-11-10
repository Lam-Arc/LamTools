"""直调执行器：文本走 Core 的 LLM 客户端，图片/视频/音频走供应商的媒体接口。

复用边界：
- 模型与供应商解析、适配档案、请求组装、错误分类全部复用
  :mod:`lamtools_core.llm.http_client` 与 :mod:`lamtools_core.cli_commands.config`；
- 图片参考图复用 generate_image 工具已经验证过的下载/上传实现；
- 这里只补“不进 Agent Loop”的一条直路，以及把媒体响应落成文件。

user:“该做的你都做一下 把它给打磨成熟”
+(文本要边生成边看见；视频这类先建任务再出结果的供应商要能等到结果；图片要能带参考图；
失败要说清楚是密钥、限流还是超时。)
"""
from __future__ import annotations

import asyncio
import base64
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from lamtools_core.config.model_store import ModelConfig, normalize_output_type
from lamtools_core.config.network import httpx_client_kwargs
from lamtools_core.llm import ChatMessage, LLMRequest
from lamtools_core.llm.http_client import CoreHttpLLMClient, LLMConfig

_TEXT_TIMEOUT = httpx.Timeout(180.0, connect=30.0)
_MEDIA_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=120.0, pool=30.0)
_DONE_STATUSES = {"completed", "succeeded", "done", "success", "finished"}
_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "expired"}

DeltaHandler = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class DirectModelTarget:
    """一次直调需要的全部连接信息。"""

    config: LLMConfig
    profile: dict[str, Any]
    output_type: str


class DirectExecutor:
    """按输出类型执行一次直调。

    两个工厂参数只为测试注入：生产路径使用 Core 的真实客户端。
    """

    def __init__(
        self,
        *,
        adapter_dirs: tuple[Path | str, ...] = (),
        llm_client_factory: Callable[[DirectModelTarget], Any] | None = None,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.adapter_dirs = tuple(adapter_dirs)
        self._llm_client_factory = llm_client_factory
        self._http_client_factory = http_client_factory

    # -- target ----------------------------------------------------------

    def build_target(self, model: ModelConfig, *, work_root: str | None = None) -> DirectModelTarget:
        from lamtools_core.cli_commands.config import _resolve_adapter_profile, load_llm_config

        config = load_llm_config(model_ref=model.id, work_root=work_root)
        profile = _resolve_adapter_profile(config, self.adapter_dirs)
        return DirectModelTarget(
            config=config,
            profile=profile,
            output_type=normalize_output_type(model.output_type),
        )

    # -- entry -----------------------------------------------------------

    async def run_one(
        self,
        *,
        target: DirectModelTarget,
        prompt: str,
        system: str,
        params: dict[str, Any],
        out_dir: Path,
        work_root: str | None = None,
        on_delta: DeltaHandler | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """执行一条，返回 ``DirectCallResult`` 需要的字段。

        异常直接抛给 service：由它决定这条是 error 还是整体 failed。
        """
        output_type = target.output_type
        if output_type == "text":
            return await self._run_text(
                target, prompt=prompt, system=system, params=params,
                on_delta=on_delta, session_id=session_id,
            )
        if output_type in ("image", "video"):
            return await self._run_media(
                target, prompt=prompt, params=params, out_dir=out_dir,
                work_root=work_root, kind=output_type,
            )
        if output_type == "audio":
            return await self._run_audio(target, prompt=prompt, params=params, out_dir=out_dir)
        raise ValueError(f"不支持的输出类型：{output_type}")

    # -- text ------------------------------------------------------------

    async def _run_text(
        self,
        target: DirectModelTarget,
        *,
        prompt: str,
        system: str,
        params: dict[str, Any],
        on_delta: DeltaHandler | None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        client = self._text_client(target, params)
        messages: list[ChatMessage] = []
        if system.strip():
            messages.append(ChatMessage(role="system", content=system.strip()))
        messages.append(ChatMessage(role="user", content=prompt))
        request = LLMRequest(
            messages=messages,
            model=target.config.model_id,
            temperature=_optional_float(params.get("temperature")),
            max_tokens=_optional_int(params.get("max_tokens")),
            top_p=_optional_float(params.get("top_p")),
            # user:“该做的你都做一下 把它给打磨成熟”+(OpenCode 按会话路由，直调也要有稳定会话标识，
            # 否则真实调用会被供应商直接拒绝。)
            metadata={"_runtime_session_id": session_id} if session_id else {},
        )

        # 先流式：边生成边把增量交给 service 落盘，界面就能边跑边看。
        if hasattr(client, "stream") and not params.get("non_stream"):
            text = ""
            usage = None
            try:
                async for event in client.stream(request):
                    kind = str(getattr(event, "kind", "") or "")
                    if kind == "content_delta" and getattr(event, "content", ""):
                        text += str(event.content)
                        if on_delta is not None:
                            await on_delta(str(event.content))
                    elif kind == "error":
                        raise RuntimeError(str(getattr(event, "error", "") or "流式响应出错"))
                    if getattr(event, "usage", None) is not None:
                        usage = event.usage
                return {"status": "ok", "text": text, "usage": _usage_dict(usage)}
            except Exception:
                # 已经有内容时不能悄悄重来，否则用户会看到重复或丢字。
                if text:
                    raise
                # 供应商不支持流式：回退到一次完整请求。
        response = await client.complete(request)
        return {"status": "ok", "text": str(response.content or ""), "usage": _usage_dict(response.usage)}

    def _text_client(self, target: DirectModelTarget, params: dict[str, Any]) -> Any:
        if self._llm_client_factory is not None:
            return self._llm_client_factory(target)
        config = target.config
        # 直调不偷偷开推理：只有请求里明确要求才带思考预算。
        thinking_enabled = bool(params.get("thinking", False)) and bool(config.thinking_supported)
        return CoreHttpLLMClient(
            config=config,
            adapter_profile=target.profile,
            thinking_enabled=thinking_enabled,
            thinking_budget=_optional_int(params.get("thinking_budget")) or config.thinking_budget,
            reasoning_effort=str(params.get("reasoning_effort") or ""),
            reasoning_level=str(params.get("reasoning_level") or ""),
            max_tokens=_optional_int(params.get("max_tokens")) or config.max_output_tokens,
            temperature=_optional_float(params.get("temperature")) if params.get("temperature") is not None else config.temperature,
        )

    # -- media -----------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._http_client_factory is not None:
            return self._http_client_factory()
        return httpx.AsyncClient(timeout=_MEDIA_TIMEOUT, **httpx_client_kwargs("https://localhost/"))

    @staticmethod
    def _headers(target: DirectModelTarget) -> dict[str, str]:
        api_key = target.config.api_key
        if not api_key:
            return {}
        if target.config.provider_api_type == "anthropic":
            return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        return {"Authorization": f"Bearer {api_key}"}

    @staticmethod
    def _endpoint(target: DirectModelTarget, kind: str) -> str:
        base = target.config.base_url.rstrip("/")
        if kind == "image":
            return f"{base}/images/generations"
        if kind == "video":
            return f"{base}/videos/generations"
        return f"{base}/audio/speech"

    async def _run_media(
        self,
        target: DirectModelTarget,
        *,
        prompt: str,
        params: dict[str, Any],
        out_dir: Path,
        work_root: str | None,
        kind: str,
    ) -> dict[str, Any]:
        reference_urls = _string_list(params.get("reference_urls"))
        async with self._http() as client:
            if kind == "image" and reference_urls:
                return await self._run_image_edit(
                    client, target, prompt=prompt, params=params,
                    out_dir=out_dir, work_root=work_root, reference_urls=reference_urls,
                )

            body: dict[str, Any] = {"model": target.config.model_id, "prompt": prompt}
            if kind == "image":
                body["n"] = _optional_int(params.get("n")) or 1
                if params.get("size"):
                    body["size"] = str(params["size"])
                if params.get("quality"):
                    body["quality"] = str(params["quality"])
                body.setdefault("response_format", "b64_json")
            else:
                for key in ("size", "seconds", "duration", "aspect_ratio"):
                    if params.get(key) not in (None, ""):
                        body[key] = params[key]
            extra = params.get("request_body")
            if isinstance(extra, dict):
                body.update(extra)

            response = await self._post(client, self._endpoint(target, kind), target, kind, json=body)
            items = _media_items(response)
            if not items:
                task_id = _task_id(response)
                if task_id:
                    items = await self._poll_media(client, target, kind, task_id, params)
                else:
                    raise RuntimeError(f"{kind} 接口没有返回可用结果：{response.text[:200]}")
            files = await self._save_items(client, target, items, kind, out_dir)
            if not files:
                raise RuntimeError(f"{kind} 结果里没有可保存的文件")
            return {"status": "ok", "files": files, "text": ""}

    async def _run_image_edit(
        self,
        client: httpx.AsyncClient,
        target: DirectModelTarget,
        *,
        prompt: str,
        params: dict[str, Any],
        out_dir: Path,
        work_root: str | None,
        reference_urls: list[str],
    ) -> dict[str, Any]:
        """参考图编辑：复用 generate_image 工具验证过的取图与 multipart 形状。"""
        from lamtools_core.tool.image_tools import _reference_image_bytes

        root = Path(work_root) if work_root else out_dir
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, reference in enumerate(reference_urls[:4]):
            raw, mime = await _reference_image_bytes(client, reference, root)
            ext = mimetypes.guess_extension(mime.split(";")[0]) or ".png"
            files.append(("image", (f"reference_{index}{ext}", raw, mime.split(";")[0])))
        data: dict[str, Any] = {
            "model": target.config.model_id,
            "prompt": prompt,
            "n": str(_optional_int(params.get("n")) or 1),
        }
        if params.get("size"):
            data["size"] = str(params["size"])
        endpoint = f"{target.config.base_url.rstrip('/')}/images/edits"
        try:
            response = await client.post(endpoint, files=files, data=data, headers=self._headers(target))
        except httpx.TimeoutException:
            raise RuntimeError("图片编辑请求超时") from None
        if response.status_code >= 400:
            raise _http_error("image", response)
        items = _media_items(response)
        if not items:
            raise RuntimeError(f"images/edits 没有返回可用结果：{response.text[:200]}")
        saved = await self._save_items(client, target, items, "image", out_dir)
        if not saved:
            raise RuntimeError("图片编辑结果里没有可保存的文件")
        return {"status": "ok", "files": saved, "text": ""}

    async def _post(
        self,
        client: httpx.AsyncClient,
        endpoint: str,
        target: DirectModelTarget,
        kind: str,
        *,
        json: dict[str, Any],
    ) -> httpx.Response:
        try:
            response = await client.post(endpoint, json=json, headers=self._headers(target))
        except httpx.TimeoutException:
            raise RuntimeError(f"{kind} 请求超时") from None
        if response.status_code >= 400:
            raise _http_error(kind, response)
        return response

    async def _poll_media(
        self,
        client: httpx.AsyncClient,
        target: DirectModelTarget,
        kind: str,
        task_id: str,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """等任务型供应商把结果准备好。

        轮询地址优先用 ``params.poll_url``（``{id}`` 会被替换），否则按 OpenAI 视频
        与通用任务两种常见路径依次尝试。
        """
        base = target.config.base_url.rstrip("/")
        template = str(params.get("poll_url") or "").strip()
        urls: list[str] = []
        if template:
            urls.append(template.replace("{id}", task_id))
        urls.append(f"{base}/videos/generations/{task_id}")
        urls.append(f"{base}/tasks/{task_id}")
        attempts = max(1, _optional_int(params.get("poll_attempts")) or 60)
        interval = max(0.0, _optional_float(params.get("poll_interval")) or 5.0)
        for _ in range(attempts):
            for url in urls:
                try:
                    response = await client.get(url, headers=self._headers(target))
                except httpx.TimeoutException:
                    continue
                if response.status_code == 404:
                    continue
                if response.status_code >= 400:
                    raise _http_error(kind, response)
                try:
                    data = response.json()
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                status = str(data.get("status") or "").lower()
                if status in _FAILED_STATUSES:
                    raise RuntimeError(f"{kind} 任务失败（{status}）：{str(data)[:200]}")
                items = _media_items_from_dict(data)
                if items:
                    return items
                if status in _DONE_STATUSES:
                    raise RuntimeError(f"{kind} 任务已完成但没有返回结果：{str(data)[:200]}")
                break
            await asyncio.sleep(interval)
        raise RuntimeError(f"{kind} 任务等待超时，可以稍后重试这一条")

    async def _save_items(
        self,
        client: httpx.AsyncClient,
        target: DirectModelTarget,
        items: list[dict[str, Any]],
        kind: str,
        out_dir: Path,
    ) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            raw, mime_type = await _media_bytes(client, item, kind)
            if not raw:
                continue
            files.append(_save_media(out_dir, kind, index, raw, mime_type))
        return files

    async def _run_audio(
        self,
        target: DirectModelTarget,
        *,
        prompt: str,
        params: dict[str, Any],
        out_dir: Path,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": target.config.model_id,
            "input": prompt,
            "voice": str(params.get("voice") or "alloy"),
            "response_format": str(params.get("format") or "mp3"),
        }
        extra = params.get("request_body")
        if isinstance(extra, dict):
            body.update(extra)
        endpoint = self._endpoint(target, "audio")
        async with self._http() as client:
            try:
                response = await client.post(endpoint, json=body, headers=self._headers(target))
            except httpx.TimeoutException:
                raise RuntimeError("音频请求超时") from None
        if response.status_code >= 400:
            raise _http_error("audio", response)
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            raise RuntimeError(f"音频接口返回了 JSON 而不是音频：{response.text[:200]}")
        raw = response.content
        if not raw:
            raise RuntimeError("音频接口返回了空内容")
        mime_type = content_type.split(";")[0].strip() or "audio/mpeg"
        file = _save_media(out_dir, "audio", 0, raw, mime_type)
        return {"status": "ok", "files": [file], "text": ""}


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cached_tokens": int(getattr(usage, "cached_tokens", 0) or 0),
    }


def _http_error(kind: str, response: httpx.Response) -> RuntimeError:
    status = response.status_code
    if status in (401, 403):
        hint = "鉴权失败：检查密钥与接口地址是否匹配"
    elif status == 429:
        hint = "请求被限流，稍后再试"
    elif status >= 500:
        hint = "供应商暂时不可用"
    else:
        hint = "请求被拒绝"
    return RuntimeError(f"{kind} 接口返回 {status}（{hint}）：{response.text[:300]}")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _media_items(response: httpx.Response) -> list[dict[str, Any]]:
    """从 OpenAI 兼容的媒体响应里取出可下载/解码的条目。"""
    try:
        data = response.json()
    except ValueError:
        return []
    return _media_items_from_dict(data) if isinstance(data, dict) else []


def _media_items_from_dict(data: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("data", "output", "videos", "images", "results"):
        items = data.get(key)
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    if data.get("url") or data.get("b64_json"):
        return [data]
    return []


def _task_id(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("id", "task_id", "job_id", "request_id"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _media_bytes(client: httpx.AsyncClient, item: dict[str, Any], kind: str) -> tuple[bytes, str]:
    encoded = item.get("b64_json") or item.get("b64") or item.get("base64")
    if isinstance(encoded, str) and encoded.strip():
        try:
            return base64.b64decode(encoded), _mime_for(kind, "")
        except (ValueError, TypeError):
            return b"", ""
    url = item.get("url") or item.get("video_url") or item.get("image_url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return b"", ""
    response = await client.get(url)
    if response.status_code >= 400:
        raise RuntimeError(f"下载{kind}结果失败 {response.status_code}：{url}")
    mime_type = response.headers.get("content-type", "").split(";")[0].strip()
    return response.content, mime_type or _mime_for(kind, url)


def _mime_for(kind: str, url: str) -> str:
    guessed = mimetypes.guess_type(url)[0] if url else ""
    if guessed:
        return guessed
    return {"image": "image/png", "video": "video/mp4", "audio": "audio/mpeg"}.get(kind, "application/octet-stream")


def _save_media(out_dir: Path, kind: str, index: int, raw: bytes, mime_type: str) -> dict[str, Any]:
    ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) or {
        "image": ".png", "video": ".mp4", "audio": ".mp3",
    }.get(kind, ".bin")
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{kind}-{int(time.time() * 1000)}-{index}{ext}"
    path = out_dir / name
    path.write_bytes(raw)
    return {"path": str(path), "name": name, "mime_type": mime_type or "application/octet-stream", "kind": kind}


__all__ = ["DirectExecutor", "DirectModelTarget"]
