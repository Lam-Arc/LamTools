import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import time
from datetime import datetime, timezone
from uuid import uuid4
from urllib.parse import urlparse
from typing import Any

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.artist.core_kernel_adapter import run_core_kernel, kernel_result_to_service_dict, visual_context_from_image_map
from app.core.artist.runtime import ARTIST_RUNTIME_SYSTEM, ArtistRuntime, ArtistRuntimeDeps
from app.core.artist.state_store import ArtistStateStore
from app.core.events import LamEvent
from app.services.api_manager import resolve_provider_vendor
from app.utils.llm_client import LLMClient

logger = logging.getLogger(__name__)

ARTIST_ROUND_SYSTEM = ARTIST_RUNTIME_SYSTEM

_shared_state_store: ArtistStateStore | None = None

def _is_external_url(url: str) -> bool:
    """Check if URL can be used as visual input after local normalization."""
    if not url:
        return False
    if url.startswith("data:"):
        return True
    if not url.startswith("http"):
        return False
    return True


def _to_llm_vision_url(url: str) -> str:
    """Convert local generated URLs to inline data URLs for remote VLMs."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or not parsed.path.startswith("/generated/"):
            return url
        filename = parsed.path.rsplit("/", 1)[-1]
        if not filename:
            return url
        import base64
        import mimetypes
        from app.config import settings as _settings

        path = (_settings.UPLOAD_DIR / filename).resolve()
        upload_dir = _settings.UPLOAD_DIR.resolve()
        if upload_dir not in path.parents or not path.exists():
            return url
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    except Exception:
        return url


async def _ensure_local_vision_url(url: str) -> str:
    """Cache remote image URLs locally so later VLM calls do not depend on provider-side downloads."""
    if not url or url.startswith("data:"):
        return url
    parsed = urlparse(url)
    if parsed.hostname in {"127.0.0.1", "localhost"} and parsed.path.startswith("/generated/"):
        return url
    if parsed.scheme not in {"http", "https"}:
        return url
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    return url
                body = await resp.read()
                mime = resp.headers.get("Content-Type", "").split(";", 1)[0].strip()
    except Exception:
        logger.warning("artist_orchestrate: failed to cache remote image for VLM: %s", url[:160], exc_info=True)
        return url
    if not mime.startswith("image/"):
        mime = mimetypes.guess_type(parsed.path)[0] or "image/png"
    ext = mimetypes.guess_extension(mime) or os.path.splitext(parsed.path)[1] or ".png"
    if ext == ".jpe":
        ext = ".jpg"
    digest = hashlib.sha256(url.encode("utf-8") + body[:4096]).hexdigest()[:16]
    filename = f"vision_cache_{digest}{ext}"
    from app.config import settings as _settings

    output_path = _settings.UPLOAD_DIR / filename
    if not output_path.exists():
        output_path.write_bytes(body)
    return f"http://127.0.0.1:{_settings.SERVER_PORT}/generated/{filename}"


def _get_state_store() -> ArtistStateStore:
    global _shared_state_store
    if _shared_state_store is None:
        _shared_state_store = ArtistStateStore()
    return _shared_state_store


def _split_blocks(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    if "||" in cleaned:
        return [part.strip() for part in cleaned.split("||") if part.strip()]
    parts = [part.strip() for part in re.split(r"(?<=[。！？!?])", cleaned) if part.strip()]
    return parts or [cleaned]


_MATERIAL_TERMS = (
    "海报", "杯子", "杯身", "咖啡杯", "豆袋", "包装袋", "会员卡", "豆卡", "社媒图", "社媒", "招牌", "logo", "Logo"
)


def _extract_prompt_terms(text: str) -> set[str]:
    return {term for term in _MATERIAL_TERMS if term and term in text}


def _material_term_matches(term: str, haystack: str) -> bool:
    if term == "杯子":
        return any(alias in haystack for alias in ("杯子", "杯身", "咖啡杯"))
    if term == "海报":
        return any(alias in haystack for alias in ("海报", "主视觉海报"))
    if term == "豆袋":
        return any(alias in haystack for alias in ("豆袋", "咖啡豆袋", "包装袋"))
    if term == "社媒":
        return any(alias in haystack for alias in ("社媒", "社媒图", "方图"))
    return term in haystack


def _extract_requested_indices(text: str) -> set[int]:
    cn_nums = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    indices: set[int] = set()
    for raw in re.findall(r"(?:第|图)\s*([一二三四五六七八九十\d]+)\s*张?", text):
        if raw.isdigit():
            indices.add(int(raw))
        elif raw in cn_nums:
            indices.add(cn_nums[raw])
    return indices


def _is_whole_set_intent(text: str) -> bool:
    return any(marker in text for marker in ("整套", "这套", "全部", "6 个", "六个", "统一", "一致", "像不像一套"))


def _classify_turn_context_mode(text: str) -> str:
    text = str(text or "")
    wants_research = any(marker in text for marker in ("查", "调研", "趋势", "流行", "当下", "资料", "参考资料"))
    references_project = any(marker in text for marker in ("这套", "当前", "现在这套", "我们这套", "结合", "对照", "看看", "检查", "审查", "评价", "统一", "一致"))
    asks_edit = any(marker in text for marker in ("改", "修改", "换", "加", "去掉", "减少", "增强", "简化"))
    blocks_generation = any(marker in text for marker in ("别画", "先别画", "不要画", "不画", "不生成", "不用出图"))
    asks_generation = (
        any(marker in text for marker in ("画", "生成", "出图", "做图", "做一张", "来一张"))
        and not blocks_generation
    )
    asks_review = any(marker in text for marker in ("看看", "检查", "审查", "评价", "统一", "一致", "像不像一套"))

    if asks_edit:
        return "local_edit"
    if asks_generation:
        return "generation"
    if wants_research and references_project:
        return "project_research"
    if wants_research:
        return "research_only"
    if asks_review or references_project:
        return "visual_review"
    return "conversation"


def _is_single_current_reference_intent(text: str) -> bool:
    return any(marker in text for marker in ("这张", "这版", "就按这张", "就按它", "按这张")) and not any(
        marker in text for marker in ("这些", "全部参考", "所有参考", "多张参考")
    )


def _select_session_images_for_turn(prompt: str, session_images: list | None) -> tuple[list, list[dict[str, Any]]]:
    if not session_images:
        return [], []
    text = str(prompt or "")
    context_mode = _classify_turn_context_mode(text)
    if context_mode == "research_only":
        diagnostics = []
        for order, img in enumerate(session_images):
            diagnostics.append({
                "selected": False,
                "score": 0,
                "order": order,
                "artifact_id": str(getattr(img, "artifact_id", "") or ""),
                "artifact_type": str(getattr(img, "artifact_type", "") or ""),
                "url": str(getattr(img, "url", "") or ""),
                "prompt": str(getattr(img, "prompt", "") or ""),
                "material_name": str(getattr(img, "material_name", "") or ""),
                "matched_terms": [],
                "reasons": [f"context_mode={context_mode}", "image_context=disabled"],
            })
        return [], diagnostics
    terms = _extract_prompt_terms(text)
    requested_indices = _extract_requested_indices(text)
    whole_set = _is_whole_set_intent(text)
    single_current_reference = _is_single_current_reference_intent(text)
    limit = 1 if single_current_reference else (6 if whole_set else 3)

    if whole_set:
        current_by_material: dict[str, Any] = {}
        for img in session_images:
            artifact_id = str(getattr(img, "artifact_id", "") or "")
            material_name = str(getattr(img, "material_name", "") or "")
            if not artifact_id or not material_name or not bool(getattr(img, "is_current_material", False)):
                continue
            current_by_material.setdefault(material_name, img)
        if current_by_material:
            selected = list(current_by_material.values())[:8]
            selected_ids = {id(img) for img in selected}
            diagnostics = []
            for order, img in enumerate(session_images):
                artifact_id = str(getattr(img, "artifact_id", "") or "")
                material_name = str(getattr(img, "material_name", "") or "")
                diagnostics.append({
                    "selected": id(img) in selected_ids,
                    "score": 1000 if id(img) in selected_ids else 0,
                    "order": order,
                    "artifact_id": artifact_id,
                    "artifact_type": str(getattr(img, "artifact_type", "") or ""),
                    "url": str(getattr(img, "url", "") or ""),
                    "prompt": str(getattr(img, "prompt", "") or ""),
                    "material_name": material_name,
                    "matched_terms": [material_name] if id(img) in selected_ids and material_name else [],
                    "reasons": ["current_series_head=1000"] if id(img) in selected_ids else ["not_current_series_head"],
                })
            return selected, diagnostics

    scored: list[tuple[int, int, Any, dict[str, Any]]] = []
    for order, img in enumerate(session_images):
        url = getattr(img, "url", "") or ""
        if not url:
            continue
        prompt_text = str(getattr(img, "prompt", "") or "")
        artifact_id = str(getattr(img, "artifact_id", "") or "")
        artifact_type = str(getattr(img, "artifact_type", "") or "")
        material_name = str(getattr(img, "material_name", "") or "")
        haystack = f"{artifact_id}\n{artifact_type}\n{material_name}\n{prompt_text}"
        reasons: list[str] = []
        score = max(0, 20 - order)
        reasons.append(f"recent={max(0, 20 - order)}")
        if artifact_id and artifact_id in text:
            score += 100
            reasons.append("artifact_id_exact=100")
        if any(f"图{idx}" in text for idx in requested_indices):
            score += 10
            reasons.append("requested_graph_index=10")
        for idx in requested_indices:
            if str(idx) in artifact_id:
                score += 10
                reasons.append(f"artifact_id_contains_{idx}=10")
        matched_terms = [term for term in terms if _material_term_matches(term, haystack)]
        score += len(matched_terms) * 80
        if matched_terms:
            reasons.append(f"matched_terms={','.join(matched_terms)}:{len(matched_terms) * 80}")
        if "改" in text or "只改" in text or "修改" in text:
            score += len(matched_terms) * 40
            if matched_terms:
                reasons.append(f"edit_intent_bonus={len(matched_terms) * 40}")
        if whole_set and any(term in haystack for term in _MATERIAL_TERMS):
            score += 30
            reasons.append("whole_set_bonus=30")
        if any(marker in text for marker in ("这张", "这版", "刚才", "继续", "就按它", "按这张")) and order == 0:
            score += 70
            reasons.append("latest_reference=70")
        scored.append((score, -order, img, {
            "selected": False,
            "score": score,
            "order": order,
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "url": url,
            "prompt": prompt_text,
            "material_name": material_name,
            "matched_terms": matched_terms,
            "reasons": reasons,
        }))

    ranked = sorted(scored, reverse=True)
    if terms and not whole_set:
        matching_ranked = [
            item for item in ranked
            if item[3].get("matched_terms")
        ]
        selected = [img for score, _, img, _ in matching_ranked if score > 0][:max(1, min(limit, len(matching_ranked)))]
    else:
        selected = [img for score, _, img, _ in ranked if score > 0][:limit]
    if not selected and session_images:
        selected = list(session_images[:1])
    selected_ids = {id(img) for img in selected}
    diagnostics: list[dict[str, Any]] = []
    for _, _, img, item in ranked:
        item["selected"] = id(img) in selected_ids
        diagnostics.append(item)
    return selected, diagnostics


async def artist_orchestrate(
    db: AsyncSession,
    session_id: str,
    prompt: str,
    persona_name: str,
    llm_provider_id: str,
    image_provider_id: str | None = None,
    reference_images: list[str] | None = None,
    source_image_urls: list[str] | None = None,
    session_images: list | None = None,
    context_images: list[str] | None = None,
    history_messages: list[dict] | None = None,
    task_manager=None,
    negative_prompt: str = "",
    image_size: str = "1024x1024",
    image_quality: str = "auto",
    image_count: int = 1,
    artist_pack_count: int = 6,
    artist_model_mode: str = "auto",
    artist_anchor_first: bool = True,
    response_format_mode: str = "auto",
    refine_mode: bool = False,
    selected_image_url: str = "",
    lineage_context: str = "",
    max_loop_steps: int | None = None,
) -> dict:
    messages: list[dict] = []
    runtime_notes = {
        "image_size": image_size,
        "image_quality": image_quality,
        "image_count": image_count,
    }
    if negative_prompt:
        runtime_notes["negative_prompt"] = negative_prompt
    messages.append({"role": "system", "content": json.dumps({"runtime_defaults": runtime_notes}, ensure_ascii=False)})

    # Inject lineage context as a separate system message so LLM understands
    # which image is the edit target and which branches are unrelated.
    if lineage_context:
        messages.append({"role": "system", "content": lineage_context})

    if history_messages:
        dialog_buffer = ""
        for msg in history_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            meta = msg.get("metadata") or {}
            is_artist_dialog = meta.get("persona") == "artist" and meta.get("dialog")

            if is_artist_dialog and role == "assistant":
                dialog_buffer += content
                continue

            if dialog_buffer:
                messages.append({"role": "assistant", "content": dialog_buffer})
                dialog_buffer = ""

            if role in ("user", "assistant") and content.strip():
                # Inject reference_images from metadata as vision blocks for user messages
                if role == "user":
                    ref_imgs = meta.get("reference_images") or []
                    vision_refs = [r for r in ref_imgs if isinstance(r, str) and _is_external_url(r)]
                    if vision_refs:
                        messages.append({"role": role, "content": content})
                    else:
                        messages.append({"role": role, "content": content})
                else:
                    messages.append({"role": role, "content": content})

        if dialog_buffer:
            messages.append({"role": "assistant", "content": dialog_buffer})

        messages = _smart_truncate(messages, max_tokens=4000)

    user_content_parts: list[dict] = [{"type": "text", "text": prompt}]

    # Explicit UI selection: expose the selected image as a candidate target.
    if refine_mode:
        refine_hint = "[系统信息：用户显式选择了一张候选编辑目标。如果本轮需要改图，请在 reference_images 中引用对应图号或 artifact_id；如果不需要改图，不要强行引用。]\n"
        user_content_parts[0] = {"type": "text", "text": refine_hint + prompt}

    # Collect available images as VLM candidates.
    # Priority: explicit target/reference/context first, then session history.
    # Build image_map so LLM can reference images by label in actions
    all_vision_urls: list[str] = []
    image_map: dict[str, str] = {}  # "图0" / artifact_id -> url
    artifact_context_map: dict[str, dict[str, str]] = {}
    url_context_map: dict[str, dict[str, str]] = {}
    image_labels: dict[str, str] = {}
    seen: set[str] = set()
    turn_started_at = time.perf_counter()

    async def _publish_debug(kind: str, payload: dict[str, Any]) -> None:
        if not task_manager:
            return
        await task_manager.publish(LamEvent(
            event_type="task_progress",
            correlation_id=f"agent-{session_id}",
            payload={
                "type": "debug",
                "session_id": session_id,
                "kind": kind,
                **payload,
            },
        ))

    async def _publish_timing(stage: str, started_at: float, extra: dict[str, Any] | None = None) -> None:
        await _publish_debug("timing", {
            "stage": stage,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
            **(extra or {}),
        })

    def _remember_image(
        img_url: str,
        label_text: str = "",
        artifact_id: str = "",
        root_artifact_id: str = "",
        root_url: str = "",
        material_name: str = "",
        is_current_material: bool = False,
    ) -> None:
        if artifact_id:
            context = {
                "url": img_url,
                "artifact_id": artifact_id,
                "root_artifact_id": root_artifact_id or artifact_id,
                "root_url": root_url or img_url,
                "material_name": material_name,
                "is_current_material": is_current_material,
            }
            image_map[artifact_id] = img_url
            artifact_context_map[artifact_id] = context
            url_context_map[img_url] = context
        if label_text and img_url not in image_labels:
            image_labels[img_url] = label_text

    async def _add_vision_image(
        img_url: str,
        label_text: str = "",
        artifact_id: str = "",
        root_artifact_id: str = "",
        root_url: str = "",
        material_name: str = "",
        is_current_material: bool = False,
    ) -> None:
        if not img_url or not _is_external_url(img_url):
            return
        cache_started_at = time.perf_counter()
        local_url = await _ensure_local_vision_url(img_url)
        await _publish_debug("image_cache", {
            "source_url": img_url,
            "local_url": local_url,
            "changed": local_url != img_url,
            "elapsed_ms": int((time.perf_counter() - cache_started_at) * 1000),
        })
        if local_url not in seen:
            all_vision_urls.append(local_url)
            seen.add(local_url)
        _remember_image(
            local_url,
            label_text,
            artifact_id,
            root_artifact_id,
            await _ensure_local_vision_url(root_url) if root_url and root_url != img_url else local_url,
            material_name,
            is_current_material,
        )

    # 0. Refine target image — always first (图0) so LLM can reference it
    if refine_mode and selected_image_url and _is_external_url(selected_image_url):
        await _add_vision_image(selected_image_url, "当前编辑目标")

    # 1. User-pinned context images (explicitly selected or workspace candidates)
    if context_images:
        for img_url in context_images:
            await _add_vision_image(img_url, "当前上下文图片")

    # 2. User-uploaded reference images
    if reference_images:
        for ref in reference_images:
            await _add_vision_image(ref, "用户参考图")

    # 3. Session images (all generated + uploaded, most recent first)
    if session_images:
        selected_session_images, selection_diagnostics = _select_session_images_for_turn(prompt, session_images)
        await _publish_debug("candidate_selection", {
            "prompt": prompt,
            "selected_count": len(selected_session_images),
            "total_count": len(session_images),
            "items": selection_diagnostics,
        })
        if task_manager:
            selected_labels = []
            for img in selected_session_images:
                artifact_id = str(getattr(img, "artifact_id", "") or "")
                prompt_text = str(getattr(img, "prompt", "") or "").replace("\n", " ")
                url = str(getattr(img, "url", "") or "")
                if len(prompt_text) > 28:
                    prompt_text = prompt_text[:28] + "..."
                selected_labels.append(f"{artifact_id or 'no-id'}:{prompt_text}:{url}")
            await task_manager.publish(LamEvent(
                event_type="task_progress",
                correlation_id=f"agent-{session_id}",
                payload={
                    "type": "task_progress",
                    "session_id": session_id,
                    "message": (
                        f"本轮候选图 {len(selected_session_images)}/{len(session_images)}"
                        + (f" [{' | '.join(selected_labels)}]" if selected_labels else "")
                    ),
                },
            ))
        for img in selected_session_images:
            url = getattr(img, 'url', '')
            artifact_id = getattr(img, 'artifact_id', '') or ''
            root_artifact_id = getattr(img, 'root_artifact_id', '') or ''
            root_url = getattr(img, 'root_url', '') or ''
            prompt_text = getattr(img, 'prompt', '') or ''
            artifact_type = getattr(img, 'artifact_type', '') or ''
            material_name = getattr(img, 'material_name', '') or ''
            is_current_material = bool(getattr(img, 'is_current_material', False))
            label_bits = []
            if artifact_id:
                label_bits.append(f"id={artifact_id}")
            if artifact_type:
                label_bits.append(f"type={artifact_type}")
            if material_name:
                label_bits.append(f"material={material_name}")
            if is_current_material:
                label_bits.append("current_material=true")
            if prompt_text:
                label_bits.append(f"prompt={prompt_text[:120]}")
            source_urls = getattr(img, 'source_image_urls', []) or []
            if source_urls:
                label_bits.append(f"refs={len(source_urls)}")
            label_text = "；".join(label_bits)
            if url and _is_external_url(url):
                await _add_vision_image(url, label_text, artifact_id, root_artifact_id, root_url, material_name, is_current_material)

    await _publish_timing("context_image_selection", turn_started_at, {
        "vision_candidates": len(all_vision_urls),
        "image_map_keys": list(image_map.keys()),
    })

    # Inject as vision blocks with labels (limit to 8 to avoid token explosion)
    for idx, img_url in enumerate(all_vision_urls[:8]):
        label = f"图{idx}"
        image_map[label] = img_url
        if img_url in url_context_map:
            artifact_context_map[label] = url_context_map[img_url]
        # Add text label before each image so LLM can reference by name
        detail = image_labels.get(img_url, "")
        label_text = f"[{label}"
        if detail:
            label_text += f"；{detail}"
        label_text += "]"
        user_content_parts.append({"type": "text", "text": label_text})

    messages.append({"role": "user", "content": user_content_parts if len(user_content_parts) > 1 else prompt})

    from app.models.api_provider import ApiProvider
    result = await db.execute(select(ApiProvider).where(ApiProvider.id == llm_provider_id))
    provider = result.scalar_one_or_none()
    if not provider:
        logger.warning(f"artist_orchestrate: LLM provider not found: {llm_provider_id}")
        return {"message": "LLM 未配置。", "artifacts": [], "blocks": ["LLM 未配置。"]}

    try:
        base_url, api_key = await resolve_provider_vendor(db, provider)
    except Exception as e:
        logger.warning(f"artist_orchestrate: LLM key decrypt failed: {e}")
        return {"message": "LLM 密钥解密失败。", "artifacts": [], "blocks": ["LLM 密钥解密失败。"]}

    client = LLMClient(base_url=base_url, api_key=api_key, model_id=provider.model_id)

    artist_turn_id = str(uuid4())[:12]

    async def _llm_call(msgs, **kwargs):
        full_text = ""
        usage_data = None
        call_started_at = time.perf_counter()
        # Extract API-level kwargs (filter out internal ones like system_prompt, messages)
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ("system_prompt", "messages", "response_format_mode", "silent")}
        silent = bool(kwargs.get("silent"))
        # response_format_mode: "json" → force JSON | "text" → force text | "auto" → let LLM decide
        response_format_mode = kwargs.get("response_format_mode", "auto")
        if response_format_mode == "json":
            api_kwargs["response_format"] = {"type": "json_object"}
        has_image = any(
            isinstance(message, dict)
            and isinstance(message.get("content"), list)
            and any(isinstance(part, dict) and part.get("type") == "image_url" for part in message.get("content", []))
            for message in msgs
        )
        if has_image:
            api_kwargs.pop("response_format", None)
        # "auto" and "text": no response_format constraint — LLM decides based on system prompt
        stream_kwargs = {"temperature": 0.8, **api_kwargs}
        await _publish_debug("llm_request", {
            "model": provider.model_id,
            "base_url": base_url,
            "silent": silent,
            "has_image": has_image,
            "response_format_mode": response_format_mode,
            "kwargs": stream_kwargs,
            "messages": msgs,
        })
        if silent and has_image and response_format_mode == "json":
            try:
                response = await asyncio.wait_for(client.chat(msgs, **stream_kwargs), timeout=120)
            except TypeError:
                stream_kwargs.pop("response_format", None)
                response = await asyncio.wait_for(client.chat(msgs, **stream_kwargs), timeout=120)
            except asyncio.TimeoutError as exc:
                raise TimeoutError("Artist 多模态决策超时") from exc
            except Exception:
                if "response_format" not in stream_kwargs:
                    raise
                stream_kwargs.pop("response_format", None)
                response = await asyncio.wait_for(client.chat(msgs, **stream_kwargs), timeout=120)
            content = LLMClient.extract_content(response)
            usage = response.get("usage", {})
            await _publish_debug("llm_response", {
                "elapsed_ms": int((time.perf_counter() - call_started_at) * 1000),
                "content": content,
                "usage": usage,
                "raw_response": response,
            })
            return content, usage
        try:
            stream = client.chat_stream(msgs, **stream_kwargs)
        except TypeError:
            stream_kwargs.pop("response_format", None)
            stream = client.chat_stream(msgs, **stream_kwargs)
        try:
            async for event in stream:
                if len(event) == 3:
                    delta, usage, _ = event
                else:
                    delta, usage = event
                full_text += delta
                if task_manager and not silent:
                    await task_manager.publish(LamEvent(
                        event_type="task_progress",
                        correlation_id=f"agent-{session_id}",
                        payload={"type": "artist_token", "session_id": session_id, "content": delta},
                    ))
                if usage:
                    usage_data = usage
        except TypeError:
            stream_kwargs.pop("response_format", None)
            async for event in client.chat_stream(msgs, **stream_kwargs):
                if len(event) == 3:
                    delta, usage, _ = event
                else:
                    delta, usage = event
                full_text += delta
                if usage:
                    usage_data = usage
        await _publish_debug("llm_response", {
            "elapsed_ms": int((time.perf_counter() - call_started_at) * 1000),
            "content": full_text,
            "usage": usage_data or {},
            "raw_response": {"stream_accumulated_text": full_text, "usage": usage_data or {}},
        })
        if silent and not full_text.strip() and os.environ.get("LAMIMAGER_DEBUG_LLM"):
            print(
                "debug_llm_empty:",
                {
                    "messages": len(msgs),
                    "has_image": has_image,
                    "response_format_mode": response_format_mode,
                    "kwargs": sorted(stream_kwargs.keys()),
                },
            )
            for idx, msg in enumerate(msgs[-6:]):
                content = msg.get("content") if isinstance(msg, dict) else msg
                if isinstance(content, list):
                    preview = [part.get("type") if isinstance(part, dict) else type(part).__name__ for part in content]
                else:
                    preview = str(content or "")[:300].replace("\n", " ")
                print(f"debug_llm_msg[-{6 - idx}]: role={msg.get('role') if isinstance(msg, dict) else '?'} content={preview}")
        return full_text, usage_data

    async def _execution_engine_run(plan, context, db_session, task_mgr):
        from app.services.executors.engine import ExecutionEngine
        from app.services.task_manager import TaskManager

        async def _multimodal_call(messages, **kwargs):
            """Multimodal LLM call for grid detection."""
            response = await client.chat(messages, **kwargs)
            return LLMClient.extract_content(response)

        engine = ExecutionEngine(plan, context, llm_call=_multimodal_call)
        return await engine.run_all(db_session, task_mgr or TaskManager())

    async def _image_generate(**kwargs):
        from app.services import generate_service

        kwargs.setdefault("image_quality", image_quality)
        image_started_at = time.perf_counter()
        await _publish_debug("image_request", {
            "provider_id": image_provider_id,
            "payload": kwargs,
        })
        result_tuple = await generate_service.generate_images_core(
            db=db,
            provider_id=image_provider_id,
            session_id=session_id,
            **kwargs,
        )
        await _publish_debug("image_response", {
            "elapsed_ms": int((time.perf_counter() - image_started_at) * 1000),
            "urls": result_tuple[0],
            "tokens_in": result_tuple[1],
            "tokens_out": result_tuple[2],
            "cache_map": dict(getattr(generate_service, "_LAST_GENERATED_IMAGE_CACHE", {})),
        })
        return result_tuple

    async def _event_publish(payload):
        if task_manager:
            event_type = "task_progress"
            correlation_id = f"agent-{session_id}"
            if payload.get("type") in (
                "artist_turn_started", "artist_reply_delta", "artist_action_started",
                "artist_image_ready", "artist_turn_done",
                "long_task_created", "long_task_step_started", "long_task_step_completed",
                "long_task_step_failed", "long_task_progress", "long_task_paused",
                "long_task_resumed", "long_task_completed", "long_task_cancelled",
                "long_task_checkpoint",
            ):
                await task_manager.publish(LamEvent(event_type=event_type, correlation_id=correlation_id, payload=payload))
            elif payload.get("type") == "artist_done":
                await task_manager.publish(LamEvent(event_type=event_type, correlation_id=correlation_id, payload=payload))

    state_store = _get_state_store()

    async def _runtime_llm_call(msgs, kwargs):
        return await _llm_call(
            msgs,
            response_format_mode="json",
            silent=True,
            **kwargs,
        )

    deps = ArtistRuntimeDeps(
        state_store=state_store,
        llm_call=_runtime_llm_call,
        vlm_call=_runtime_llm_call,
        execution_engine_run=_execution_engine_run,
        event_publish=_event_publish,
        image_generate=_image_generate,
        delegate_agent=None,
    )

    rt = ArtistRuntime(deps=deps)
    visual_context = visual_context_from_image_map(
        image_map=image_map,
        artifact_context_map=artifact_context_map,
        reference_images=reference_images,
        source_image_urls=source_image_urls,
    )
    kernel_result = await run_core_kernel(
        rt,
        prompt,
        session_id=session_id,
        max_steps=max_loop_steps or 4,
        visual_context=visual_context,
    )
    runtime_result = kernel_result_to_service_dict(kernel_result, artist_turn_id=artist_turn_id)

    t_in = runtime_result.get("tokens_in", 0)
    t_out = runtime_result.get("tokens_out", 0)

    from app.core.agent.llm_call_logger import LLMCallRecord, log_and_bill
    await log_and_bill(db, LLMCallRecord(
        node="artist_runtime",
        model_id=provider.model_id,
        provider_id=llm_provider_id,
        session_id=session_id,
        tokens_in=t_in,
        tokens_out=t_out,
        billing_type="agent",
        system_prompt="Artist CoreKernel loop",
        user_content=prompt,
        response_text=runtime_result.get("message", ""),
    ))

    user_message = runtime_result.get("message", "")
    reply_lines = runtime_result.get("reply_lines", [])
    artifacts = runtime_result.get("artifacts", [])
    total_cost = runtime_result.get("cost", 0.0)

    for art in artifacts:
        art_meta = art.get("metadata") or {}
        try:
            from app.services import generate_service as _generate_service
            art_url = art.get("url", "")
            original_url = _generate_service._GENERATED_IMAGE_CACHE_HISTORY.get(art_url, "")
        except Exception:
            original_url = ""
        if original_url and original_url != art.get("url", ""):
            art_meta["cached_from_url"] = original_url
            art_meta["cached_local_url"] = art.get("url", "")

    if artifacts:
        if all((art.get("metadata") or {}).get("artist_runtime") for art in artifacts):
            vision_summaries = [None] * len(artifacts)
        else:
            vision_summaries = await _vision_review(db, llm_provider_id, artifacts, session_id)

    blocks = runtime_result.get("blocks", _split_blocks(user_message))

    if task_manager:
        await task_manager.publish(LamEvent(
            event_type="task_progress",
            correlation_id=f"agent-{session_id}",
            payload={"type": "artist_done", "session_id": session_id},
        ))

    return {
        "message": user_message,
        "reply_lines": reply_lines if isinstance(reply_lines, list) else _split_blocks(str(user_message or "")),
        "artifacts": artifacts,
        "blocks": blocks,
        "phase": runtime_result.get("phase", "idle"),
        "tokens_in": t_in,
        "tokens_out": t_out,
        "cost": total_cost,
        "artist_turn_id": artist_turn_id,
        "tool_calls": runtime_result.get("tool_calls", []),
        "tool_results": runtime_result.get("tool_results", []),
        "artist_runtime": runtime_result.get("artist_runtime"),
        "delegated_agent": runtime_result.get("delegated_agent", False),
    }


async def _vision_review(
    db: AsyncSession,
    llm_provider_id: str,
    artifacts: list[dict],
    session_id: str,
) -> list[dict | None]:
    from app.models.api_provider import ApiProvider, ProviderType

    if not llm_provider_id or not artifacts:
        return [None] * len(artifacts)

    result = await db.execute(select(ApiProvider).where(ApiProvider.id == llm_provider_id))
    provider = result.scalar_one_or_none()
    if not provider or provider.provider_type != ProviderType.llm:
        return [None] * len(artifacts)

    try:
        base_url, api_key = await resolve_provider_vendor(db, provider)
    except Exception as e:
        logger.warning(f"_vision_review: LLM key decrypt failed: {e}")
        return [None] * len(artifacts)

    client = LLMClient(base_url=base_url, api_key=api_key, model_id=provider.model_id)

    summaries: list[dict | None] = []
    for art in artifacts:
        url = art.get("url", "")
        if not url:
            summaries.append(None)
            continue

        try:
            vision_url = url
            if url.startswith("data:"):
                vision_url = None
            if not vision_url:
                summaries.append(None)
                continue

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Describe this image briefly. Focus on subject, style, color, composition. Note any obvious issues. Reply in 1-2 short sentences.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": vision_url, "detail": "low"},
                        },
                    ],
                }
            ]
            response = await client.chat(messages, temperature=0.3, max_tokens=200)
            description = LLMClient.extract_content(response)

            style_tags = []
            for tag in ("anime", "realistic", "oil painting", "watercolor", "digital art", "photorealistic", "sketch", "3d render"):
                if tag in description.lower():
                    style_tags.append(tag)

            summaries.append({
                "visual_summary": description[:200] if description else None,
                "style_tags": style_tags,
                "issues": [],
            })
        except Exception as e:
            logger.warning(f"_vision_review: failed for {url[:50]}: {e}")
            summaries.append(None)

    return summaries


def _estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate: text ~ 1 token per 3 chars, vision ~ 85 per image."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += max(1, len(content) // 3)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "text":
                        total += max(1, len(part.get("text", "")) // 3)
                    elif part.get("type") == "image_url":
                        total += 85
    return total


def _smart_truncate(messages: list[dict], max_tokens: int = 4000) -> list[dict]:
    """Token-aware history truncation: keep most recent messages within token budget."""
    if _estimate_tokens(messages) <= max_tokens:
        return messages
    system_msgs = [m for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    budget = max_tokens - _estimate_tokens(system_msgs)
    # Important: keep messages about anchor/pack decisions
    anchor_keywords = ["anchor", "锚点", "pack", "套图", "方向", "确认", "对，就"]
    important = [m for m in non_system if any(
        kw in (m.get("content", "") if isinstance(m.get("content", ""), str) else "")
        for kw in anchor_keywords
    )]
    rest = [m for m in non_system if m not in important]
    # Keep important msgs first, then fill with recent rest
    selected = list(important)
    remaining_budget = budget - _estimate_tokens(selected)
    for m in reversed(rest):
        if remaining_budget <= 0:
            break
        est = _estimate_tokens([m])
        if est <= remaining_budget:
            selected.insert(len(important), m)
            remaining_budget -= est
    return system_msgs + selected[-20:]  # max 20 messages regardless
