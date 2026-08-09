"""generate_image tool: text-to-image and reference-image edit.

双模式：
- 无 ``reference_urls`` → 文生图（POST {api_url}/images/generations）
- 带 ``reference_urls`` → 参考图编辑（POST {api_url}/images/edits，multipart
  上传参考图，支持 http(s) URL / 本地文件路径 / data: URL）

产物统一保存到 ``{work_root}/.lam/artifacts/images/``，artifact 的 uri 为相对
work_root 的 posix 路径（前端经 ``/api/core/projects/{id}/files/raw`` 预览）。

生图 API 返回较慢（1-3 分钟），这里使用独立 httpx client 并放宽超时，
不能复用 web_tools._http_session() 的 30s 单例。
"""

from __future__ import annotations

import base64
import mimetypes
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx

from lamtools_core.tool import ToolArtifact, ToolCall, ToolResult

_IMAGE_TIMEOUT = httpx.Timeout(
    connect=30.0,
    read=240.0,
    write=60.0,
    pool=30.0,
)
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_GENERATE_ENDPOINT = "images/generations"
_EDIT_ENDPOINT = "images/edits"


def make_generate_image_handler(
    imagegen_config: dict | None,
    work_root: str,
    artifact_registry: Any | None = None,
) -> Callable[[ToolCall], Awaitable[ToolResult]]:
    """Build the generate_image handler.

    ``artifact_registry`` is an optional hook for Phase 2 (artifact system):
    when provided, each generated image is registered with its prompt and
    reference parents before the ToolResult is returned.
    """
    config = dict(imagegen_config or {})
    api_url = str(config.get("api_url") or "").strip().rstrip("/")
    api_key = str(config.get("api_key") or "").strip()
    model = str(config.get("model") or "").strip()
    work_root_path = Path(work_root)

    async def generate_image(call: ToolCall) -> ToolResult:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        prompt = str(args.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="Missing 'prompt' argument",
            )
        if not api_url:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error="生图未配置：请在设置 → 生图中配置 API 地址并启用",
                metadata={"error": "missing_image_provider"},
            )
        try:
            count = int(args.get("count", 1) or 1)
        except (TypeError, ValueError):
            count = 1
        count = max(1, min(count, 4))
        size = str(args.get("size") or "1024x1024").strip()
        raw_refs = args.get("reference_urls")
        reference_urls = (
            [str(item).strip() for item in raw_refs if str(item).strip()]
            if isinstance(raw_refs, list)
            else []
        )

        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        try:
            async with httpx.AsyncClient(timeout=_IMAGE_TIMEOUT, headers=headers) as client:
                if reference_urls:
                    saved = await _run_edit(
                        client, api_url, model, prompt, reference_urls, work_root_path
                    )
                else:
                    saved = await _run_generate(
                        client, api_url, model, prompt, count, size, work_root_path
                    )
        except httpx.TimeoutException as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"生图 API 超时（生成较慢可稍后重试）: {exc}",
            )
        except httpx.HTTPError as exc:
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"生图 API 请求失败: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 — tool handlers must never raise
            return ToolResult(
                call_id=call.id,
                name=call.name,
                status="failed",
                error=f"生图失败: {exc}",
            )

        lines = [f"- {rel}" for _, _, rel in saved]
        content = f"[generate_image] 已生成 {len(saved)} 张图片（保存于 .lam/artifacts/images/）:\n" + "\n".join(lines)
        artifacts = [
            ToolArtifact(
                kind="image",
                uri=rel,
                metadata={
                    "mime_type": mime,
                    "size_bytes": size_bytes,
                    "prompt": prompt,
                },
            )
            for mime, size_bytes, rel in saved
        ]
        # Phase 2 hook: register generated images into the artifact system.
        if artifact_registry is not None and saved:
            try:
                parent_ids = _resolve_parent_ids(artifact_registry, reference_urls, work_root_path)
                registered = artifact_registry.register_generated_images(
                    prompt=prompt,
                    files=saved,
                    parent_ids=parent_ids,
                )
                for artifact, artifact_id in zip(artifacts, registered):
                    artifact.metadata["artifact_id"] = artifact_id
            except Exception:  # noqa: BLE001 — registration must never fail the tool call
                pass
        return ToolResult(
            call_id=call.id,
            name=call.name,
            status="ok",
            content=content,
            metadata={"paths": [rel for _, _, rel in saved], "prompt": prompt},
            artifacts=artifacts,
        )

    return generate_image


async def _run_generate(
    client: httpx.AsyncClient,
    api_url: str,
    model: str,
    prompt: str,
    count: int,
    size: str,
    work_root: Path,
) -> list[tuple[str, int, str]]:
    """Text-to-image via {api_url}/images/generations. Returns (mime, bytes, rel_path)."""
    payload: dict[str, Any] = {"prompt": prompt, "n": count, "size": size}
    if model:
        payload["model"] = model
    resp = await client.post(f"{api_url}/{_GENERATE_ENDPOINT}", json=payload)
    resp.raise_for_status()
    body = resp.json()
    items = body.get("data") or []
    if not items:
        raise RuntimeError(f"images/generations 响应缺少 data: {str(body)[:200]}")
    saved: list[tuple[str, int, str]] = []
    ts = _timestamp()
    for i, item in enumerate(items[:count]):
        raw = await _image_bytes(client, item, resp)
        if raw is None:
            continue
        mime, ext = _detect_image_type(raw, item)
        rel = f".lam/artifacts/images/{ts}_{i}{ext}"
        _save_image(work_root, rel, raw)
        saved.append((mime, len(raw), rel))
    if not saved:
        raise RuntimeError("未能从生图响应中解析出任何图片")
    return saved


async def _run_edit(
    client: httpx.AsyncClient,
    api_url: str,
    model: str,
    prompt: str,
    reference_urls: list[str],
    work_root: Path,
) -> list[tuple[str, int, str]]:
    """Reference-image edit via {api_url}/images/edits (OpenAI multipart).

    参考图支持 http(s) URL（下载后上传）、本地路径与 data: URL。
    """
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    for i, ref in enumerate(reference_urls):
        raw, mime = await _reference_image_bytes(client, ref, work_root)
        ext = mimetypes.guess_extension(mime.split(";")[0]) or ".png"
        files.append(("image", (f"reference_{i}{ext}", raw, mime.split(";")[0])))
    data: dict[str, Any] = {"prompt": prompt, "n": 1}
    if model:
        data["model"] = model
    resp = await client.post(f"{api_url}/{_EDIT_ENDPOINT}", files=files, data=data)
    resp.raise_for_status()
    body = resp.json()
    items = body.get("data") or []
    if not items:
        raise RuntimeError(f"images/edits 响应缺少 data: {str(body)[:200]}")
    saved: list[tuple[str, int, str]] = []
    ts = _timestamp()
    for i, item in enumerate(items):
        raw = await _image_bytes(client, item, resp)
        if raw is None:
            continue
        mime, ext = _detect_image_type(raw, item)
        rel = f".lam/artifacts/images/{ts}_0{ext}"
        _save_image(work_root, rel, raw)
        saved.append((mime, len(raw), rel))
    if not saved:
        raise RuntimeError("未能从编辑响应中解析出任何图片")
    return saved


async def _reference_image_bytes(
    client: httpx.AsyncClient,
    ref: str,
    work_root: Path,
) -> tuple[bytes, str]:
    """Resolve a reference (http(s) URL / local path / data: URL) to (bytes, mime)."""
    if ref.startswith("data:"):
        match = re.match(r"data:([^;,]*)?(;base64)?,(.*)", ref, re.DOTALL)
        if match is None:
            raise RuntimeError("无法解析 data: 参考图 URL")
        mime = match.group(1) or "image/png"
        raw = base64.b64decode(match.group(3)) if match.group(2) else match.group(3).encode("utf-8")
        return raw, mime
    if _is_http_url(ref):
        resp = await client.get(ref)
        resp.raise_for_status()
        mime = resp.headers.get("content-type", "").split(";")[0] or "image/png"
        return resp.content, mime
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = work_root / candidate
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise RuntimeError(f"参考图文件不存在: {ref}")
    mime = mimetypes.guess_type(str(candidate))[0] or "image/png"
    return candidate.read_bytes(), mime


async def _image_bytes(client: httpx.AsyncClient, item: dict[str, Any], resp: httpx.Response) -> bytes | None:
    url = item.get("url")
    b64 = item.get("b64_json")
    if isinstance(b64, str) and b64:
        try:
            return base64.b64decode(b64)
        except (ValueError, TypeError):
            pass
    if isinstance(url, str) and url:
        return await _image_bytes_from_url(client, url)
    # Fallback: raw response bytes (some providers return image bytes directly).
    if resp.headers.get("content-type", "").startswith("image/"):
        return resp.content
    return None


async def _image_bytes_from_url(client: httpx.AsyncClient, url: str) -> bytes | None:
    img_resp = await client.get(url)
    img_resp.raise_for_status()
    if not img_resp.headers.get("content-type", "").startswith("image/"):
        # Some providers serve images without a proper content-type; accept by extension.
        parsed = urlparse(url)
        if not parsed.path.lower().endswith(_IMAGE_EXTENSIONS):
            return None
    return img_resp.content


def _detect_image_type(raw: bytes, hint: dict[str, Any]) -> tuple[str, str]:
    mime = "image/png"
    ext = ".png"
    url = str(hint.get("url") or "") if isinstance(hint, dict) else ""
    lower_url = urlparse(url).path.lower() if url else ""
    for e in _IMAGE_EXTENSIONS:
        if lower_url.endswith(e):
            mime = mimetypes.guess_type("x" + e)[0] or mime
            ext = e
            break
    if ext == ".jpg":
        ext = ".jpeg"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return mime, ext


def _save_image(work_root: Path, rel: str, raw: bytes) -> None:
    target = work_root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _is_http_url(value: str) -> bool:
    try:
        return urlparse(value).scheme in ("http", "https")
    except ValueError:
        return False


def _resolve_parent_ids(artifact_registry: Any, reference_urls: list[str], work_root: Path) -> list[str]:
    """Map reference URLs to registered artifact ids (best-effort)."""
    ids: list[str] = []
    lookup = getattr(artifact_registry, "resolve_artifact_id", None)
    if lookup is None:
        return ids
    for ref in reference_urls:
        artifact_id = lookup(ref, work_root=work_root)
        if artifact_id:
            ids.append(artifact_id)
    return ids


__all__ = ["make_generate_image_handler"]
