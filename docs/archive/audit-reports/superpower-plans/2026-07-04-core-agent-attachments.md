# Core Agent Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add first-version local attachments as a Core agent base capability, with Writer as the first product surface.

**Architecture:** Core owns the product-neutral attachment contract, local-resource helpers, model input modality capability shape, and shared UI pieces. Writer reuses that Core contract to upload, bind, display, and pass attachment references into the runtime without creating a parallel Writer-only protocol. Provider-native file IDs, retrieval, OCR, and automatic VLM switching stay out of this version.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Vue 3, Pinia, Vitest, Node 24.17+, npm 11.17+.

## Global Constraints

- `core/` is the complete base Agent substrate. If a generic Agent should have the capability, it belongs in Core.
- `core/src/lamtools_core/` must stay product-neutral: no Writer/Artist product names, persona routing, or product branches.
- First version uses local attachment resources and stable references. Do not paste file bodies into user text.
- Failure principle: any upload, send, validation, or runtime attachment failure terminates that action and shows a clear error. Do not silently continue with a weaker path.
- Upload failure keeps the composer text and already uploaded pending attachments. A failed pending item blocks send until retried or removed.
- Send failure before backend acceptance keeps composer text and pending attachments.
- Runtime failure after backend acceptance leaves the accepted message in history and shows the failed run.
- Running turn plus pending attachments is not queued in the current text-only queue. Show a wait-until-finished prompt and keep the composer state.
- Image attachments: explicitly unsupported model blocks before send; explicitly supported model sends; unknown capability sends by default; provider rejection stops the run and shows the provider error.
- Do not implement automatic VLM switching, OCR fallback, vector search, PDF/Word/spreadsheet parsing, provider-native cloud file IDs, or cross-session attachment reuse.
- PowerShell commands involving Chinese text must use UTF-8-safe files, JSON escaping, or script Unicode escapes, not pipe/here-string Chinese bodies.

## Mature Solution Alignment

- OpenAI Responses uses explicit content blocks such as `input_text`, `input_image`, and `input_file`; file search is a separate tool path. Verified from OpenAI official docs and OpenAPI spec on 2026-07-04:
  - https://developers.openai.com/api/docs/guides/images-vision
  - https://developers.openai.com/api/docs/api-reference/responses
- Anthropic Claude files follow the same broad shape: upload or reference files, then include file references in message content/tool paths. Verified from Anthropic official docs on 2026-07-04:
  - https://docs.anthropic.com/en/docs/build-with-claude/files

## File Structure

- Create `core/src/lamtools_core/attachments.py`: product-neutral attachment resource dataclasses, filename sanitizing, preview classification, input-item parsing, image capability gate, and runtime context formatting.
- Modify `core/src/lamtools_core/__init__.py`: export attachment helpers only if this package already exports adjacent protocol helpers; otherwise leave imports local.
- Create `core/tests/test_attachments.py`: unit tests for filename safety, preview type, input parsing, capability gates, and context formatting.
- Modify `core/ui/src/types.ts`: add `CoreAttachment`, `CoreAttachmentInputItem`, and `CoreModelInputCapabilities`; add `attachment` to `MessagePartType`.
- Create `core/ui/src/components/AttachmentTray.vue`: shared pending/message attachment tray with remove, retry, preview, and open events.
- Create `core/ui/src/composables/usePendingAttachments.ts`: shared pending attachment state machine for uploaded, failed, and removing items.
- Modify `core/ui/src/components/WorkspaceShell.vue`: emit `composer-drop` and surface drag state instead of swallowing dropped files.
- Modify `core/ui/src/components/ChatThread.vue`: render user-message attachment parts and expose preview/open events.
- Modify `core/ui/src/index.ts`: export new component, composable, and types.
- Create `core/ui/tests/attachment-tray.test.ts`: shared UI contract tests for tray state and user-message attachment rendering.
- Modify `members/writer/backend/app/services/attachment_service.py`: reuse Core helpers for sanitizing and preview classification; add exact same-session validation helpers.
- Modify `members/writer/backend/app/routers/attachment.py`: keep Writer HTTP route as first product transport, backed by Core contract fields.
- Modify `members/writer/backend/app/app_server/runtime_context.py`: parse attachment input items alongside text.
- Modify `members/writer/backend/app/app_server/queue.py`: accept turn attachment items, reject attachment queue items, persist canonical message parts, and bind attachments before runtime starts.
- Modify `members/writer/backend/app/app_server/operations.py`: pass attachment IDs into runtime start and return clear JSON-RPC validation errors.
- Modify `members/writer/backend/app/app_server/runtime.py`: pass attachment IDs to Writer runtime for context.
- Modify `members/writer/backend/app/services/writer_service.py`: build runtime attachment context through Core helper and validate current-message attachments in both app-server and legacy paths.
- Modify `members/writer/backend/app/services/transcript_service.py`: require exact attachment binding count for the accepted message.
- Create `members/writer/backend/tests/test_writer_attachment_flow.py`: backend integration tests for upload, binding, rejection, runtime context, and queue rejection.
- Modify `members/writer/frontend/src/appServer/store.ts`: send generic Core input items and keep queue text-only.
- Modify `members/writer/frontend/src/appServer/protocol.ts`: type attachment input and snapshot payload.
- Modify `members/writer/frontend/src/appServer/selectors.ts`: project user-message attachment content into Core UI parts.
- Modify `members/writer/frontend/src/api/index.ts`: keep upload/list/preview/open APIs and align returned shape to Core attachment fields.
- Modify `members/writer/frontend/src/views/CoreWorkbenchView.vue`: wire Core attachment tray, upload button, drop handling, failure policy, image capability gate, and no-attachment-queue gate.
- Modify `members/writer/frontend/tests/appServer/store.test.ts`: assert turn input can include attachment references and queue stays text-only.
- Create `members/writer/frontend/tests/appServer/attachment-selectors.test.ts`: assert user-message attachments project to Core message parts.

---

### Task 1: Core Python Attachment Contract

**Files:**
- Create: `core/src/lamtools_core/attachments.py`
- Test: `core/tests/test_attachments.py`

**Interfaces:**
- Produces: `AttachmentResource`, `AttachmentInputItem`, `ModelInputCapabilities`
- Produces: `sanitize_attachment_filename(filename: str) -> str`
- Produces: `attachment_preview_type(filename: str, mime_type: str) -> str`
- Produces: `extract_attachment_ids(input_items: list[dict[str, object]]) -> list[str]`
- Produces: `has_attachment_items(input_items: list[dict[str, object]]) -> bool`
- Produces: `model_image_gate(capabilities: ModelInputCapabilities | None, attachments: list[AttachmentResource]) -> Literal["allow", "block"]`
- Produces: `format_runtime_attachment_context(attachments: list[AttachmentResource], current_ids: set[str]) -> str`

- [ ] **Step 1: Write the failing Core tests**

```python
# core/tests/test_attachments.py
from lamtools_core.attachments import (
    AttachmentResource,
    ModelInputCapabilities,
    attachment_preview_type,
    extract_attachment_ids,
    format_runtime_attachment_context,
    has_attachment_items,
    model_image_gate,
    sanitize_attachment_filename,
)


def test_sanitize_attachment_filename_removes_paths_and_invalid_chars():
    assert sanitize_attachment_filename(r"..\bad:name?.txt") == "bad_name_.txt"
    assert sanitize_attachment_filename("...") == "attachment"


def test_preview_type_classifies_text_image_pdf_and_external():
    assert attachment_preview_type("note.md", "application/octet-stream") == "text"
    assert attachment_preview_type("photo.png", "image/png") == "image"
    assert attachment_preview_type("brief.pdf", "application/pdf") == "pdf"
    assert attachment_preview_type("archive.zip", "application/zip") == "external"


def test_extract_attachment_ids_accepts_attachment_items_only():
    items = [
        {"type": "text", "text": "看附件"},
        {"type": "attachment", "attachment_id": "att-1"},
        {"type": "attachment", "id": "att-2"},
        {"type": "file", "id": "ignored"},
    ]
    assert extract_attachment_ids(items) == ["att-1", "att-2"]
    assert has_attachment_items(items) is True
    assert has_attachment_items([{"type": "text", "text": "only"}]) is False


def test_model_image_gate_blocks_only_explicitly_unsupported_images():
    image = AttachmentResource(
        id="att-image",
        filename="shot.png",
        mime_type="image/png",
        size=12,
        storage_path="C:/tmp/shot.png",
        preview_type="image",
    )
    text = AttachmentResource(
        id="att-text",
        filename="note.txt",
        mime_type="text/plain",
        size=4,
        storage_path="C:/tmp/note.txt",
        preview_type="text",
    )
    assert model_image_gate(None, [image]) == "allow"
    assert model_image_gate(ModelInputCapabilities(input_modalities=None), [image]) == "allow"
    assert model_image_gate(ModelInputCapabilities(input_modalities=("text",)), [image]) == "block"
    assert model_image_gate(ModelInputCapabilities(input_modalities=("text", "image")), [image]) == "allow"
    assert model_image_gate(ModelInputCapabilities(input_modalities=("text",)), [text]) == "allow"


def test_runtime_attachment_context_marks_current_and_history():
    attachments = [
        AttachmentResource("old", "old.txt", "text/plain", 3, "C:/x/old.txt", "text"),
        AttachmentResource("new", "new.png", "image/png", 8, "C:/x/new.png", "image"),
    ]
    text = format_runtime_attachment_context(attachments, {"new"})
    assert "当前会话附件索引" in text
    assert "[历史附件] old.txt | text/plain | 3 bytes | C:/x/old.txt" in text
    assert "[本条消息附件] new.png | image/png | 8 bytes | C:/x/new.png" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.14 -m pytest core/tests/test_attachments.py -q`

Expected: FAIL because `lamtools_core.attachments` does not exist.

- [ ] **Step 3: Implement the Core attachment module**

```python
# core/src/lamtools_core/attachments.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import re

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".csv", ".tsv",
    ".log", ".xml", ".html", ".htm", ".css", ".js", ".ts", ".tsx", ".jsx",
    ".py", ".ps1", ".bat", ".sh", ".toml", ".ini", ".cfg", ".sql",
}
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {"application/json", "application/xml", "application/x-yaml", "application/yaml"}


@dataclass(frozen=True)
class AttachmentResource:
    id: str
    filename: str
    mime_type: str
    size: int
    storage_path: str
    preview_type: str
    session_id: str = ""
    message_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class AttachmentInputItem:
    attachment_id: str
    filename: str = ""
    mime_type: str = ""
    preview_type: str = ""


@dataclass(frozen=True)
class ModelInputCapabilities:
    input_modalities: tuple[str, ...] | None = None


def sanitize_attachment_filename(filename: str) -> str:
    name = Path(filename or "attachment").name.strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = name.strip(". ")
    return name or "attachment"


def attachment_preview_type(filename: str, mime_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    normalized_mime = (mime_type or "application/octet-stream").lower()
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if normalized_mime in TEXT_MIME_TYPES or any(normalized_mime.startswith(prefix) for prefix in TEXT_MIME_PREFIXES):
        return "text"
    if normalized_mime.startswith("image/"):
        return "image"
    if normalized_mime == "application/pdf":
        return "pdf"
    return "external"


def extract_attachment_ids(input_items: list[dict[str, object]]) -> list[str]:
    ids: list[str] = []
    for item in input_items:
        if not isinstance(item, dict) or item.get("type") != "attachment":
            continue
        raw_id = item.get("attachment_id") or item.get("attachmentId") or item.get("id")
        if isinstance(raw_id, str) and raw_id.strip():
            ids.append(raw_id.strip())
    return ids


def has_attachment_items(input_items: list[dict[str, object]]) -> bool:
    return bool(extract_attachment_ids(input_items))


def model_image_gate(
    capabilities: ModelInputCapabilities | None,
    attachments: list[AttachmentResource],
) -> Literal["allow", "block"]:
    if not any(item.preview_type == "image" or item.mime_type.lower().startswith("image/") for item in attachments):
        return "allow"
    if capabilities is None or capabilities.input_modalities is None:
        return "allow"
    normalized = {item.lower() for item in capabilities.input_modalities}
    return "allow" if "image" in normalized else "block"


def format_runtime_attachment_context(attachments: list[AttachmentResource], current_ids: set[str]) -> str:
    if not attachments:
        return ""
    lines = ["", "当前会话附件索引（可按文件名查找，需要查看时可读取对应路径）："]
    for attachment in attachments:
        marker = "本条消息附件" if attachment.id in current_ids else "历史附件"
        lines.append(
            f"- [{marker}] {attachment.filename} | {attachment.mime_type} | {attachment.size} bytes | {attachment.storage_path}"
        )
    return "\n".join(lines)
```

- [ ] **Step 4: Run Core tests**

Run: `py -3.14 -m pytest core/tests/test_attachments.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add core/src/lamtools_core/attachments.py core/tests/test_attachments.py
git commit -m "feat(core): add agent attachment contract"
```

### Task 2: Core UI Attachment Types And Shared Tray

**Files:**
- Modify: `core/ui/src/types.ts`
- Create: `core/ui/src/components/AttachmentTray.vue`
- Create: `core/ui/src/composables/usePendingAttachments.ts`
- Modify: `core/ui/src/components/WorkspaceShell.vue`
- Modify: `core/ui/src/components/ChatThread.vue`
- Modify: `core/ui/src/index.ts`
- Test: `core/ui/tests/attachment-tray.test.ts`

**Interfaces:**
- Consumes: Core attachment resource fields from Task 1.
- Produces: `CoreAttachment`
- Produces: `CoreAttachmentInputItem`
- Produces: `CoreModelInputCapabilities`
- Produces: `AttachmentTray` component events: `remove`, `retry`, `preview`, `open`
- Produces: `usePendingAttachments()` state: `pendingAttachments`, `failedAttachments`, `addUploaded`, `markFailed`, `removeAttachment`, `clearAttachments`, `hasBlockingFailure`, `attachmentInputItems`

- [ ] **Step 1: Write failing UI tests**

```ts
// core/ui/tests/attachment-tray.test.ts
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AttachmentTray from '../src/components/AttachmentTray.vue'
import ChatThread from '../src/components/ChatThread.vue'
import type { CoreAttachment, CoreMessage } from '../src/types'

const uploaded: CoreAttachment = {
  id: 'att-1',
  filename: 'note.md',
  label: 'note.md',
  mime_type: 'text/markdown',
  size: 120,
  preview_type: 'text',
  status: 'uploaded',
}

describe('AttachmentTray', () => {
  it('renders uploaded and failed attachments with stable actions', async () => {
    const wrapper = mount(AttachmentTray, {
      props: {
        attachments: [
          uploaded,
          { ...uploaded, id: 'att-2', filename: 'bad.png', label: 'bad.png', preview_type: 'image', status: 'failed', error: '上传失败' },
        ],
      },
    })
    expect(wrapper.text()).toContain('note.md')
    expect(wrapper.text()).toContain('bad.png')
    expect(wrapper.text()).toContain('上传失败')
    await wrapper.get('[data-attachment-remove="att-1"]').trigger('click')
    await wrapper.get('[data-attachment-retry="att-2"]').trigger('click')
    expect(wrapper.emitted('remove')?.[0]).toEqual(['att-1'])
    expect(wrapper.emitted('retry')?.[0]).toEqual(['att-2'])
  })

  it('renders user-message attachment parts in ChatThread', () => {
    const messages: CoreMessage[] = [{
      id: 'm-1',
      role: 'user',
      content: '看附件',
      timestamp: '',
      parts: [{
        id: 'm-1:att-1',
        partType: 'attachment',
        status: 'completed',
        content: '',
        label: 'note.md',
        metadata: { attachment: uploaded },
      }],
    }]
    const wrapper = mount(ChatThread, { props: { messages } })
    expect(wrapper.text()).toContain('看附件')
    expect(wrapper.text()).toContain('note.md')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `Push-Location core/ui; npm run test:contract -- --run tests/attachment-tray.test.ts; Pop-Location`

Expected: FAIL because `AttachmentTray.vue` is missing and `MessagePartType` has no `attachment`.

- [ ] **Step 3: Extend Core UI types**

Add these types to `core/ui/src/types.ts` and include `attachment` in `MessagePartType`:

```ts
export type CoreAttachmentStatus = 'uploading' | 'uploaded' | 'failed'

export interface CoreAttachment {
  id: string
  filename: string
  label?: string
  mime_type: string
  size: number
  preview_type: 'text' | 'image' | 'pdf' | 'external' | string
  status?: CoreAttachmentStatus
  error?: string
  metadata?: Record<string, unknown>
}

export interface CoreAttachmentInputItem {
  type: 'attachment'
  attachment_id: string
  filename?: string
  mime_type?: string
  preview_type?: string
}

export type CoreInputItem = { type: 'text'; text: string } | CoreAttachmentInputItem

export interface CoreModelInputCapabilities {
  input_modalities?: string[] | null
}
```

- [ ] **Step 4: Add the shared attachment tray**

Create `core/ui/src/components/AttachmentTray.vue` with uploaded, failed, remove, retry, preview, and open states:

```vue
<template>
  <div v-if="attachments.length" class="attachment-tray" aria-label="附件">
    <div
      v-for="item in attachments"
      :key="item.id"
      class="attachment-row"
      :class="{ 'attachment-row--failed': item.status === 'failed' }"
    >
      <button
        class="attachment-main"
        type="button"
        :disabled="item.status === 'failed'"
        :data-attachment-preview="item.id"
        @click="$emit('preview', item.id)"
      >
        <span class="attachment-kind">{{ kindLabel(item) }}</span>
        <span class="attachment-name">{{ item.label || item.filename }}</span>
        <span class="attachment-meta">{{ formatSize(item.size) }}</span>
      </button>
      <span v-if="item.status === 'failed'" class="attachment-error">{{ item.error || '上传失败' }}</span>
      <button
        v-if="item.status === 'failed'"
        type="button"
        class="attachment-action"
        :data-attachment-retry="item.id"
        @click="$emit('retry', item.id)"
      >重试</button>
      <button
        v-else
        type="button"
        class="attachment-action"
        :data-attachment-open="item.id"
        @click="$emit('open', item.id)"
      >打开</button>
      <button
        type="button"
        class="attachment-remove"
        :data-attachment-remove="item.id"
        aria-label="移除附件"
        @click="$emit('remove', item.id)"
      >×</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { CoreAttachment } from '../types'

defineProps<{ attachments: CoreAttachment[] }>()

defineEmits<{
  remove: [id: string]
  retry: [id: string]
  preview: [id: string]
  open: [id: string]
}>()

function kindLabel(item: CoreAttachment): string {
  if (item.preview_type === 'image') return 'IMG'
  if (item.preview_type === 'pdf') return 'PDF'
  if (item.preview_type === 'text') return 'TXT'
  return 'FILE'
}

function formatSize(size: number): string {
  if (size < 1024) return `${size}B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`
  return `${(size / 1024 / 1024).toFixed(1)}MB`
}
</script>
```

- [ ] **Step 5: Add pending attachment state helper**

Create `core/ui/src/composables/usePendingAttachments.ts`:

```ts
import { computed, ref } from 'vue'
import type { CoreAttachment, CoreAttachmentInputItem } from '../types'

export function usePendingAttachments() {
  const pendingAttachments = ref<CoreAttachment[]>([])

  const failedAttachments = computed(() => pendingAttachments.value.filter(item => item.status === 'failed'))
  const hasBlockingFailure = computed(() => failedAttachments.value.length > 0)
  const attachmentInputItems = computed<CoreAttachmentInputItem[]>(() =>
    pendingAttachments.value
      .filter(item => item.status !== 'failed')
      .map(item => ({
        type: 'attachment',
        attachment_id: item.id,
        filename: item.filename,
        mime_type: item.mime_type,
        preview_type: item.preview_type,
      })),
  )

  function addUploaded(attachment: CoreAttachment) {
    pendingAttachments.value = [
      ...pendingAttachments.value.filter(item => item.id !== attachment.id),
      { ...attachment, status: 'uploaded' },
    ]
  }

  function markFailed(id: string, filename: string, error: string) {
    pendingAttachments.value = [
      ...pendingAttachments.value.filter(item => item.id !== id),
      {
        id,
        filename,
        label: filename,
        mime_type: 'application/octet-stream',
        size: 0,
        preview_type: 'external',
        status: 'failed',
        error,
      },
    ]
  }

  function removeAttachment(id: string) {
    pendingAttachments.value = pendingAttachments.value.filter(item => item.id !== id)
  }

  function clearAttachments() {
    pendingAttachments.value = []
  }

  return {
    pendingAttachments,
    failedAttachments,
    hasBlockingFailure,
    attachmentInputItems,
    addUploaded,
    markFailed,
    removeAttachment,
    clearAttachments,
  }
}
```

- [ ] **Step 6: Emit drop from the shared shell**

Modify `core/ui/src/components/WorkspaceShell.vue`:

```vue
<form
  class="floating-composer"
  @submit.prevent="$emit('composer-submit')"
  @dragover.prevent
  @drop.prevent="$emit('composer-drop', $event)"
>
```

Update `defineEmits` in the same file:

```ts
const emit = defineEmits<{
  'composer-submit': []
  'composer-drop': [event: DragEvent]
}>()
```

- [ ] **Step 7: Render user attachment parts in ChatThread**

In `core/ui/src/components/ChatThread.vue`, replace the user bubble block with:

```vue
<div v-else-if="msg.role === 'user'" class="user-row">
  <div class="user-bubble">
    <div v-if="msg.content" class="user-content">{{ msg.content }}</div>
    <AttachmentTray
      v-if="userAttachmentParts(msg).length"
      class="message-attachments"
      :attachments="userAttachmentParts(msg)"
      @preview="id => emit('attachment-preview', { messageId: msg.id, attachmentId: id })"
      @open="id => emit('attachment-open', { messageId: msg.id, attachmentId: id })"
    />
  </div>
</div>
```

Import `AttachmentTray` and add helper:

```ts
import AttachmentTray from './AttachmentTray.vue'
import type { CoreAttachment } from '../types'

function userAttachmentParts(msg: CoreMessage): CoreAttachment[] {
  return (msg.parts || [])
    .filter(part => part.partType === 'attachment')
    .map(part => part.metadata?.attachment)
    .filter((item): item is CoreAttachment => !!item && typeof item === 'object' && 'id' in item)
}
```

Add emits:

```ts
'attachment-preview': [payload: { messageId: string; attachmentId: string }]
'attachment-open': [payload: { messageId: string; attachmentId: string }]
```

- [ ] **Step 8: Export the new UI surface**

Modify `core/ui/src/index.ts`:

```ts
export { default as AttachmentTray } from './components/AttachmentTray.vue'
export { usePendingAttachments } from './composables/usePendingAttachments'
export type {
  CoreAttachment,
  CoreAttachmentStatus,
  CoreAttachmentInputItem,
  CoreInputItem,
  CoreModelInputCapabilities,
} from './types'
```

- [ ] **Step 9: Run Core UI tests**

Run: `Push-Location core/ui; npm run test:contract -- --run tests/attachment-tray.test.ts tests/chat-thread-process.test.ts; Pop-Location`

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add core/ui/src/types.ts core/ui/src/components/AttachmentTray.vue core/ui/src/composables/usePendingAttachments.ts core/ui/src/components/WorkspaceShell.vue core/ui/src/components/ChatThread.vue core/ui/src/index.ts core/ui/tests/attachment-tray.test.ts
git commit -m "feat(core-ui): add shared attachment composer surface"
```

### Task 3: Writer Backend Uses Core Attachment Contract

**Files:**
- Modify: `members/writer/backend/app/services/attachment_service.py`
- Modify: `members/writer/backend/app/routers/attachment.py`
- Modify: `members/writer/backend/app/app_server/runtime_context.py`
- Modify: `members/writer/backend/app/app_server/queue.py`
- Modify: `members/writer/backend/app/app_server/operations.py`
- Modify: `members/writer/backend/app/app_server/runtime.py`
- Modify: `members/writer/backend/app/services/writer_service.py`
- Modify: `members/writer/backend/app/services/transcript_service.py`
- Test: `members/writer/backend/tests/test_writer_attachment_flow.py`

**Interfaces:**
- Consumes: `lamtools_core.attachments.extract_attachment_ids`
- Consumes: `lamtools_core.attachments.format_runtime_attachment_context`
- Produces: app-server `input` supports `{ type: "attachment", attachment_id: string }`
- Produces: attachment IDs are bound before runtime starts
- Produces: backend rejects queue items that include attachments

- [ ] **Step 1: Write failing backend integration tests**

Create `members/writer/backend/tests/test_writer_attachment_flow.py`:

```python
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.attachment import WriterAttachment
from app.models.message import WriterMessage
from app.models.session import WriterSession
from app.app_server.queue import accept_queue_item, accept_turn_start
from app.services.attachment_service import create_attachment_from_bytes, validate_attachments_for_session


@pytest.mark.asyncio
async def test_turn_start_binds_attachment_to_accepted_user_message(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'attach.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session = WriterSession(id="session-1", title="Test", work_root=str(tmp_path))
        db.add(session)
        await db.flush()
        attachment = await create_attachment_from_bytes(
            db=db,
            session=session,
            filename="note.md",
            content=b"# hello",
            source="user_upload",
            mime_type="text/markdown",
        )

        events = await accept_turn_start(
            db,
            thread_id=session.id,
            client_message_id="client-1",
            input_items=[
                {"type": "text", "text": "看附件"},
                {"type": "attachment", "attachment_id": attachment.id, "filename": "note.md"},
            ],
            work_root=str(tmp_path),
        )
        await db.commit()

        accepted = next(event for event in events if event.method == "turn/accepted")
        user_message_id = accepted.payload["user_message_id"]
        stored = await db.get(WriterAttachment, attachment.id)
        message = await db.get(WriterMessage, user_message_id)
        assert stored.message_id == user_message_id
        assert message.parts["attachments"] == [attachment.id]
        assert message.parts["app_server_input"][1]["attachment_id"] == attachment.id


@pytest.mark.asyncio
async def test_attachment_from_another_session_is_rejected(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reject.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        session_a = WriterSession(id="session-a", title="A", work_root=str(tmp_path / "a"))
        session_b = WriterSession(id="session-b", title="B", work_root=str(tmp_path / "b"))
        db.add_all([session_a, session_b])
        await db.flush()
        attachment = await create_attachment_from_bytes(
            db=db,
            session=session_b,
            filename="other.txt",
            content=b"other",
            source="user_upload",
            mime_type="text/plain",
        )
        with pytest.raises(ValueError, match="Attachment does not belong to this session"):
            await validate_attachments_for_session(db, session_id=session_a.id, attachment_ids=[attachment.id])


@pytest.mark.asyncio
async def test_queue_rejects_attachment_input(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue.db'}", future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        db.add(WriterSession(id="session-1", title="Test", work_root=str(tmp_path)))
        await db.flush()
        with pytest.raises(ValueError, match="Attachment messages cannot be queued"):
            await accept_queue_item(
                db,
                thread_id="session-1",
                client_message_id="client-queue",
                input_items=[
                    {"type": "text", "text": "等下发"},
                    {"type": "attachment", "attachment_id": "att-1"},
                ],
            )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -3.14 -m pytest members/writer/backend/tests/test_writer_attachment_flow.py -q`

Expected: FAIL because validation and queue rejection are not implemented.

- [ ] **Step 3: Reuse Core helper functions in attachment service**

Modify imports and helper usage in `members/writer/backend/app/services/attachment_service.py`:

```python
from lamtools_core.attachments import (
    AttachmentResource,
    attachment_preview_type,
    sanitize_attachment_filename,
)
```

Replace local `safe_filename()` body with `return sanitize_attachment_filename(filename)` and replace `preview_type(...)` usage with `attachment_preview_type(...)`.

Add exact same-session validation:

```python
async def validate_attachments_for_session(
    db: AsyncSession,
    *,
    session_id: str,
    attachment_ids: list[str],
) -> list[WriterAttachment]:
    if not attachment_ids:
        return []
    result = await db.execute(
        select(WriterAttachment).where(WriterAttachment.id.in_(attachment_ids))
    )
    found = {item.id: item for item in result.scalars().all()}
    missing = [item_id for item_id in attachment_ids if item_id not in found]
    if missing:
        raise ValueError(f"Attachment not found: {', '.join(missing)}")
    wrong_session = [item_id for item_id, item in found.items() if item.session_id != session_id]
    if wrong_session:
        raise ValueError("Attachment does not belong to this session")
    return [found[item_id] for item_id in attachment_ids]


def attachment_resource(attachment: WriterAttachment) -> AttachmentResource:
    return AttachmentResource(
        id=attachment.id,
        session_id=attachment.session_id,
        message_id=attachment.message_id,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        size=attachment.size,
        storage_path=attachment.storage_path,
        preview_type=attachment.preview_type,
        metadata=attachment.metadata_ or {},
    )
```

- [ ] **Step 4: Parse app-server attachment input**

Modify `members/writer/backend/app/app_server/runtime_context.py`:

```python
from lamtools_core.attachments import extract_attachment_ids, has_attachment_items


def input_attachment_ids(input_items: list[dict[str, Any]]) -> list[str]:
    return extract_attachment_ids(input_items)
```

Update `__all__` to include `input_attachment_ids` and `has_attachment_items`.

- [ ] **Step 5: Bind attachments when accepting a turn**

Modify `members/writer/backend/app/app_server/queue.py`:

```python
from lamtools_core.attachments import extract_attachment_ids, has_attachment_items
from app.services.attachment_service import validate_attachments_for_session
```

In `accept_turn_start`, before `create_user_message_turn`:

```python
attachment_ids = extract_attachment_ids(input_items)
await validate_attachments_for_session(db, session_id=thread_id, attachment_ids=attachment_ids)
```

Call `create_user_message_turn` with:

```python
message_parts={
    "app_server_input": input_items,
    "attachments": attachment_ids,
},
attachment_ids=attachment_ids,
```

In `accept_queue_item`, before creating the event:

```python
if has_attachment_items(input_items):
    raise ValueError("Attachment messages cannot be queued")
```

- [ ] **Step 6: Convert backend validation errors to JSON-RPC errors**

In `members/writer/backend/app/app_server/operations.py`, wrap the existing `accept_turn_start` call in `handle_turn_start_operation` without changing its current arguments:

```python
try:
    events = await accept_turn_start(
        db,
        thread_id=thread_id,
        client_message_id=client_message_id,
        input_items=input_items,
        work_root=params.get("work_root") or params.get("workRoot"),
    )
except ValueError as exc:
    await db.rollback()
    return WriterOperationOutcome(
        response=rpc_error(request_id, code=INVALID_REQUEST, message=str(exc))
    )
```

Add the same `ValueError` handling around the existing `accept_queue_item` call in `handle_queue_create_operation`, preserving `thread_id`, `client_message_id`, `input_items`, and `mode=str(params.get("mode") or "next_turn")`.

Add attachment IDs to `runtime_start`:

```python
"attachment_ids": input_attachment_ids(input_items),
```

- [ ] **Step 7: Pass attachment IDs into runtime execution**

Modify `members/writer/backend/app/app_server/runtime.py` so `start(...)` and `_run(...)` accept `attachment_ids: list[str] | None = None`, then call:

```python
await service["run_turn"](
    db=db,
    session_id=thread_id,
    user_message=text,
    thinking_enabled=thinking_enabled,
    thinking_budget=thinking_budget,
    model_id=model_id,
    user_message_id=user_message_id,
    transcript_turn_id=turn_id,
    attachment_ids=attachment_ids or [],
)
```

- [ ] **Step 8: Use Core context formatting in Writer runtime**

Modify `members/writer/backend/app/services/writer_service.py`:

```python
from app.services.attachment_service import attachment_resource, validate_attachments_for_session
from lamtools_core.attachments import format_runtime_attachment_context
```

In `run_turn`, before `attachment_context`:

```python
current_attachment_ids = attachment_ids or []
await validate_attachments_for_session(db, session_id=session_id, attachment_ids=current_attachment_ids)
```

Replace `_session_attachment_context` body so it converts DB rows to `AttachmentResource` and calls `format_runtime_attachment_context(resources, set(current_ids))`.

- [ ] **Step 9: Make transcript binding exact**

Modify `members/writer/backend/app/services/transcript_service.py` inside `create_user_message_turn`:

```python
if attachment_ids:
    result = await db.execute(
        select(WriterAttachment).where(
            WriterAttachment.session_id == session_id,
            WriterAttachment.id.in_(attachment_ids),
        )
    )
    found = {attachment.id: attachment for attachment in result.scalars().all()}
    if len(found) != len(set(attachment_ids)):
        missing = [item_id for item_id in attachment_ids if item_id not in found]
        raise ValueError(f"Attachment not found for this session: {', '.join(missing)}")
    for attachment_id in attachment_ids:
        found[attachment_id].message_id = user_message.id
```

- [ ] **Step 10: Run backend tests**

Run: `py -3.14 -m pytest core/tests/test_attachments.py members/writer/backend/tests/test_writer_attachment_flow.py -q`

Expected: PASS.

- [ ] **Step 11: Commit**

```powershell
git add members/writer/backend/app/services/attachment_service.py members/writer/backend/app/routers/attachment.py members/writer/backend/app/app_server/runtime_context.py members/writer/backend/app/app_server/queue.py members/writer/backend/app/app_server/operations.py members/writer/backend/app/app_server/runtime.py members/writer/backend/app/services/writer_service.py members/writer/backend/app/services/transcript_service.py members/writer/backend/tests/test_writer_attachment_flow.py
git commit -m "feat(writer): bind core attachment input through app server"
```

### Task 4: Writer Frontend Composer And History Integration

**Files:**
- Modify: `members/writer/frontend/src/appServer/store.ts`
- Modify: `members/writer/frontend/src/appServer/protocol.ts`
- Modify: `members/writer/frontend/src/appServer/selectors.ts`
- Modify: `members/writer/frontend/src/api/index.ts`
- Modify: `members/writer/frontend/src/views/CoreWorkbenchView.vue`
- Modify: `members/writer/frontend/tests/appServer/store.test.ts`
- Create: `members/writer/frontend/tests/appServer/attachment-selectors.test.ts`

**Interfaces:**
- Consumes: Core UI `AttachmentTray`, `usePendingAttachments`, `CoreInputItem`, `CoreAttachment`
- Consumes: Writer backend app-server attachment input from Task 3
- Produces: upload/select/drop pending attachment flow
- Produces: no queue for attachment-bearing messages
- Produces: successful backend acceptance is the only point that clears text and pending attachments

- [ ] **Step 1: Add failing frontend tests**

Append to `members/writer/frontend/tests/appServer/store.test.ts`:

```ts
test('startTurn sends text plus attachment input items', async () => {
  setActivePinia(createPinia())
  const store = useWriterAppServerStore()
  const calls: Array<{ method: string; params: Record<string, unknown> }> = []
  store.client = {
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params })
      return { snapshot: snapshot(1, 'running') }
    },
  } as never

  await store.startTurn('thread-1', [
    { type: 'text', text: '看附件' },
    { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
  ])

  assert.equal(calls[0].method, 'turn/start')
  assert.deepEqual(calls[0].params.input, [
    { type: 'text', text: '看附件' },
    { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
  ])
})
```

Create `members/writer/frontend/tests/appServer/attachment-selectors.test.ts`:

```ts
import assert from 'node:assert/strict'
import test from 'node:test'
import { selectChatMessages } from '../../src/appServer/selectors.ts'
import type { WriterAppSnapshot } from '../../src/appServer/protocol.ts'

test('user message attachment input projects into message metadata', () => {
  const state: WriterAppSnapshot = {
    thread_id: 'thread-1',
    snapshot_seq: 1,
    status: 'idle',
    seen_event_ids: [],
    item_order: ['msg-1'],
    items: {
      'msg-1': {
        item_id: 'msg-1',
        type: 'userMessage',
        status: 'completed',
        content: [
          { type: 'text', text: '看附件' },
          { type: 'attachment', attachment_id: 'att-1', filename: 'note.md', mime_type: 'text/markdown', preview_type: 'text' },
        ],
      },
    },
    turns: {},
    queue: [],
    requests: {},
    artifacts: {},
  }

  const [message] = selectChatMessages(state)
  assert.equal(message.content, '看附件')
  assert.equal(message.attachments?.[0].id, 'att-1')
  assert.equal(message.attachments?.[0].filename, 'note.md')
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `Push-Location members/writer/frontend; npm test -- tests/appServer/store.test.ts tests/appServer/attachment-selectors.test.ts; Pop-Location`

Expected: FAIL because the store only accepts text and selectors do not project attachments.

- [ ] **Step 3: Type app-server input**

Modify `members/writer/frontend/src/appServer/protocol.ts`:

```ts
export interface WriterAttachmentInputItem {
  type: 'attachment'
  attachment_id: string
  filename?: string
  mime_type?: string
  preview_type?: string
}

export type WriterInputItem = { type: 'text'; text: string } | WriterAttachmentInputItem
```

Use `WriterInputItem[]` for turn and queue input fields where currently `unknown` is too loose.

- [ ] **Step 4: Make `startTurn` accept Core input items**

Modify `members/writer/frontend/src/appServer/store.ts`:

```ts
async startTurn(
  threadId: string,
  input: WriterInputItem[] | string,
  workRoot?: string,
  options: { thinking_enabled?: boolean; thinking_budget?: number } = {},
) {
  await this.ensureClient()
  const inputItems = typeof input === 'string' ? [{ type: 'text' as const, text: input }] : input
  const response = await this.client!.request('turn/start', {
    thread_id: threadId,
    client_message_id: crypto.randomUUID(),
    input: inputItems,
    work_root: workRoot,
    ...options,
  })
  this.applyResponse(response)
}
```

Leave `queueInput(threadId, text)` text-only.

- [ ] **Step 5: Project attachment content into chat messages**

Modify `members/writer/frontend/src/appServer/selectors.ts`:

```ts
export interface AppServerChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  parts: WriterAppItem[]
  attachments?: Array<{
    id: string
    filename: string
    label: string
    mime_type: string
    size: number
    preview_type: string
    status: 'uploaded'
  }>
  metadata?: Record<string, unknown>
}
```

For user messages:

```ts
if (item.type === 'userMessage') {
  messages.push({
    id: item.item_id,
    role: 'user',
    content: inputToText(item.content),
    parts: [],
    attachments: inputAttachments(item.content),
  })
  continue
}
```

Add helper:

```ts
function inputAttachments(value: unknown): AppServerChatMessage['attachments'] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const record = item as Record<string, unknown>
    if (record.type !== 'attachment') return []
    const id = String(record.attachment_id || record.attachmentId || record.id || '')
    if (!id) return []
    const filename = String(record.filename || record.label || 'attachment')
    return [{
      id,
      filename,
      label: filename,
      mime_type: String(record.mime_type || record.mimeType || 'application/octet-stream'),
      size: Number(record.size || 0),
      preview_type: String(record.preview_type || record.previewType || 'external'),
      status: 'uploaded' as const,
    }]
  })
}
```

- [ ] **Step 6: Map projected attachments into Core message parts**

Modify `appServerMessages()` in `members/writer/frontend/src/views/CoreWorkbenchView.vue`:

```ts
parts: [
  ...message.parts.map(appServerItemToPart),
  ...(message.attachments || []).map((attachment) => ({
    id: `${message.id}:attachment:${attachment.id}`,
    partType: 'attachment' as const,
    status: 'completed' as const,
    content: '',
    label: attachment.label || attachment.filename,
    metadata: { attachment },
  })),
],
```

- [ ] **Step 7: Wire pending attachment state into the composer**

In `CoreWorkbenchView.vue`, import:

```ts
import { AttachmentTray, usePendingAttachments, type CoreAttachment, type CoreInputItem } from '@lamtools/ui'
import { uploadAttachment, openAttachment, previewAttachment } from '@/api'
```

Create state:

```ts
const {
  pendingAttachments,
  hasBlockingFailure,
  attachmentInputItems,
  addUploaded,
  markFailed,
  removeAttachment,
  clearAttachments,
} = usePendingAttachments()

const attachmentFileInput = ref<HTMLInputElement | null>(null)
```

Add upload handler:

```ts
async function uploadFiles(files: FileList | File[]) {
  const sessionId = await ensureActiveSession('附件消息')
  if (!sessionId) {
    runtimeStatusText.value = '请先新建项目并选择一个会话'
    return
  }
  for (const file of Array.from(files)) {
    const localId = `failed:${file.name}:${Date.now()}`
    try {
      const uploaded = await uploadAttachment(sessionId, file)
      addUploaded(uploaded as CoreAttachment)
    } catch (err) {
      markFailed(localId, file.name, err instanceof Error ? err.message : '上传失败')
      runtimeStatusText.value = `附件上传失败：${file.name}`
      return
    }
  }
}
```

Add model image gate:

```ts
function modelAllowsPendingImages(): boolean {
  if (!pendingAttachments.value.some(item => item.preview_type === 'image' || item.mime_type.startsWith('image/'))) return true
  const modalities = activeExecutionModel.value?.extra?.input_modalities
  if (!Array.isArray(modalities)) return true
  return modalities.map(String).map(item => item.toLowerCase()).includes('image')
}
```

- [ ] **Step 8: Enforce failure and no-attachment-queue policy on send**

Change `submitWriterText` signature:

```ts
async function submitWriterText(text: string, options: { clearComposer?: boolean; attachments?: CoreInputItem[] } = {}) {
```

Before queuing/running:

```ts
const attachments = options.attachments || []
if (hasBlockingFailure.value) {
  runtimeStatusText.value = '附件上传失败，请重试或移除失败附件后再发送'
  composerText.value = cleaned
  return
}
if (attachments.length > 0 && !modelAllowsPendingImages()) {
  runtimeStatusText.value = '当前模型明确不支持图片输入，请切换支持图片的模型后再发送'
  composerText.value = cleaned
  return
}
if ((status === 'running' || status === 'waiting') && attachments.length > 0) {
  runtimeStatusText.value = '当前正在运行，带附件的消息请等本轮结束后再发送'
  composerText.value = cleaned
  return
}
```

When running:

```ts
const inputItems: CoreInputItem[] = [
  { type: 'text', text: cleaned },
  ...attachments,
]
const runOk = await runWriterTask(sessionId, inputItems)
if (runOk) {
  if (options.clearComposer) clearComposerAfterPersisted(cleaned)
  clearAttachments()
} else if (options.clearComposer) {
  composerText.value = cleaned
}
```

Do not clear pending attachments when `runOk` is false.

- [ ] **Step 9: Update `sendWriterTask` and `runWriterTask`**

Use attachment input items only at send time:

```ts
await submitWriterText(text, {
  clearComposer: true,
  attachments: attachmentInputItems.value,
})
```

Change `runWriterTask`:

```ts
async function runWriterTask(sessionId: string, inputItems: CoreInputItem[]) {
  try {
    if (!isAppServerActive.value) {
      await appServerStore.connect(api.API_BASE, sessionId)
    }
    await appServerStore.startTurn(sessionId, inputItems, currentSessionWorkRoot(), currentThinkingOptions())
    runtimeStatusText.value = '已发送'
    void listCoreSessions().then((refreshed) => {
      sessions.value = refreshed
    })
    return true
  } catch (err) {
    console.error('Failed to run Writer task:', err)
    runtimeStatusText.value = err instanceof Error ? err.message : '发送失败'
    return false
  }
}
```

- [ ] **Step 10: Render the pending tray and upload controls**

In the `composer-textarea` slot, before `<textarea>`:

```vue
<AttachmentTray
  :attachments="pendingAttachments"
  @remove="removeAttachment"
  @retry="retryPendingAttachment"
  @preview="previewPendingAttachment"
  @open="openPendingAttachment"
/>
<input
  ref="attachmentFileInput"
  class="sr-only"
  type="file"
  multiple
  @change="event => uploadFiles((event.target as HTMLInputElement).files || [])"
/>
```

In `composer-tools`, before model controls:

```vue
<button class="composer-attachment-button" type="button" title="添加附件" aria-label="添加附件" @click="attachmentFileInput?.click()">
  +
</button>
```

On `WorkspaceShell`, add:

```vue
@composer-drop="event => uploadFiles(event.dataTransfer?.files || [])"
```

Implement action handlers:

```ts
async function retryPendingAttachment(id: string) {
  removeAttachment(id)
  runtimeStatusText.value = '请重新选择该附件'
  attachmentFileInput.value?.click()
}

async function previewPendingAttachment(id: string) {
  try {
    await previewAttachment(id)
  } catch (err) {
    runtimeStatusText.value = err instanceof Error ? err.message : '预览失败'
  }
}

async function openPendingAttachment(id: string) {
  try {
    await openAttachment(id)
  } catch (err) {
    runtimeStatusText.value = err instanceof Error ? err.message : '打开附件失败'
  }
}
```

- [ ] **Step 11: Run frontend tests**

Run: `Push-Location members/writer/frontend; npm test; Pop-Location`

Expected: PASS.

- [ ] **Step 12: Commit**

```powershell
git add members/writer/frontend/src/appServer/store.ts members/writer/frontend/src/appServer/protocol.ts members/writer/frontend/src/appServer/selectors.ts members/writer/frontend/src/api/index.ts members/writer/frontend/src/views/CoreWorkbenchView.vue members/writer/frontend/tests/appServer/store.test.ts members/writer/frontend/tests/appServer/attachment-selectors.test.ts
git commit -m "feat(writer): wire core attachments into composer"
```

### Task 5: End-To-End Verification And Documentation Sync

**Files:**
- Modify: `docs/superpowers/specs/2026-07-04-writer-attachment-upload-design.md`
- Modify: `AGENTS.md` only if implementation reveals a missing architecture rule; do not duplicate the rule already added.

**Interfaces:**
- Consumes: tasks 1-4.
- Produces: verified local attachment MVP.

- [ ] **Step 1: Run focused Python gates**

Run:

```powershell
py -3.14 -m pytest core/tests/test_attachments.py -q
py -3.14 -m pytest members/writer/backend/tests/test_writer_attachment_flow.py members/writer/backend/tests/test_writer_transcript_service.py -q
```

Expected: both commands PASS.

- [ ] **Step 2: Run focused frontend gates**

Run:

```powershell
Push-Location core/ui; npm run test:contract; Pop-Location
Push-Location members/writer/frontend; npm test; Pop-Location
```

Expected: both commands PASS.

- [ ] **Step 3: Build the affected UI packages**

Run:

```powershell
Push-Location core/ui; npm run build; Pop-Location
Push-Location members/writer/frontend; npm run build; Pop-Location
```

Expected: both commands PASS.

- [ ] **Step 4: Manual Writer verification**

Run:

```powershell
.\scripts\dev.ps1 writer all
```

Manual checks:

- Select a `.txt` or `.md` file from the composer.
- Confirm it appears in the pending tray.
- Send a message with text plus the attachment.
- Confirm the composer clears only after backend acceptance.
- Confirm the user message shows the attachment in history.
- Confirm the runtime receives the stored local path in attachment context.
- Drop an image while model capability is unknown and confirm sending is allowed.
- Set a model `extra.input_modalities` to `["text"]`, attach an image, and confirm sending is blocked before runtime.
- Simulate upload failure, confirm text remains, failed item is visible, and send is blocked until retry/remove.
- Simulate send failure before backend acceptance, confirm text and pending attachments remain.
- Start a running turn, attach a file, attempt send, and confirm the message is not queued.

- [ ] **Step 5: Diff and whitespace checks**

Run:

```powershell
git diff -- AGENTS.md docs/superpowers/specs/2026-07-04-writer-attachment-upload-design.md docs/superpowers/plans/2026-07-04-core-agent-attachments.md
git diff --check
```

Expected: only intentional doc/code changes; no whitespace errors. A Windows LF-to-CRLF warning is acceptable if no actual whitespace errors are reported.

- [ ] **Step 6: Commit docs if changed during execution**

```powershell
git add AGENTS.md docs/superpowers/specs/2026-07-04-writer-attachment-upload-design.md docs/superpowers/plans/2026-07-04-core-agent-attachments.md
git commit -m "docs: align attachments as core agent capability"
```

## Self-Review

- Spec coverage: upload, pending tray, remove, send binding, history display, preview/open, runtime local path, failure termination, no attachment queue, image capability unknown-by-default, no automatic VLM/OCR, and Core ownership all have tasks.
- Placeholder scan: this plan contains no unresolved placeholder markers.
- Type consistency: attachment input is consistently `{ type: "attachment", attachment_id: string }`; UI metadata uses `CoreAttachment`; backend parsing accepts `attachment_id`, `attachmentId`, or `id` but emits canonical `attachment_id`.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-core-agent-attachments.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints.
