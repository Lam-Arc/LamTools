import { computed, ref, watch } from 'vue';
import type { CoreAttachment, CoreAttachmentInputItem } from '@/types.ts';

// user:“输入信息包含文本草稿+待发附件，按会话保存且重启恢复”
// +(托盘是独立的未发送列表，不是草稿文本的一部分；按 thread 存 localStorage，
// 只恢复已上传成功的项，上传中/失败的不跨重启保留)。
export const CORE_COMPOSER_ATTACHMENTS_PREFIX = 'lamtools-core.composer.attachments.';

function attachmentsStorageKey(sessionId: string): string {
  return `${CORE_COMPOSER_ATTACHMENTS_PREFIX}${sessionId}`;
}

function storageOrNull(): Storage | null {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null;
  } catch {
    return null;
  }
}

function readStoredAttachments(sessionId: string): CoreAttachment[] {
  const storage = storageOrNull();
  if (!storage || !sessionId) return [];
  try {
    const raw = storage.getItem(attachmentsStorageKey(sessionId));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is CoreAttachment =>
        Boolean(item)
        && typeof item === 'object'
        && typeof (item as CoreAttachment).id === 'string'
        // Path references live in the draft text, not in the sendable tray;
        // restoring them here would make the tray/workbench mirror clear them.
        && !(item as CoreAttachment).id.startsWith('path:')
        && (item as CoreAttachment).status === 'uploaded')
      .map(item => ({ ...item, status: 'uploaded' as const }));
  } catch {
    return [];
  }
}

function writeStoredAttachments(sessionId: string, items: CoreAttachment[]): void {
  const storage = storageOrNull();
  if (!storage || !sessionId) return;
  try {
    const key = attachmentsStorageKey(sessionId);
    const uploaded = items.filter(item => item.status === 'uploaded' && item.id);
    if (uploaded.length === 0) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(uploaded));
  } catch {
    // Restricted storage must never break composing.
  }
}

export function usePendingAttachments() {
  const pendingAttachments = ref<CoreAttachment[]>([]);
  let currentSessionId = '';

  /** Park the outgoing session's tray and restore the incoming one. */
  function setSession(sessionId: string | null | undefined): void {
    const nextId = String(sessionId || '');
    if (currentSessionId && currentSessionId !== nextId) {
      writeStoredAttachments(currentSessionId, pendingAttachments.value);
    }
    currentSessionId = nextId;
    pendingAttachments.value = nextId ? readStoredAttachments(nextId) : [];
  }

  /** Persist the current tray (the watcher below calls this on every change). */
  function persistCurrent(): void {
    if (currentSessionId) writeStoredAttachments(currentSessionId, pendingAttachments.value);
  }

  watch(pendingAttachments, () => persistCurrent())

  const hasBlockingFailure = computed(() =>
    pendingAttachments.value.some(item => item.status === 'failed' || item.status === 'uploading'),
  );

  const attachmentInputItems = computed<CoreAttachmentInputItem[]>(() =>
    pendingAttachments.value
      .filter(item => item.status === 'uploaded' && !item.id.startsWith('path:'))
      .map(item => ({
        type: 'attachment',
        attachment_id: item.id,
        path: item.path,
        filename: item.filename,
        mime_type: item.mime_type,
        preview_type: item.preview_type,
        size: item.size,
      })),
  );

  // user:“添加附件，处理显示图标”+(处理状态立即进入输入框并阻止提前发送)。
  function addProcessing(id: string, filename: string, path: string) {
    pendingAttachments.value = [...pendingAttachments.value, { id, filename, path, mime_type: 'application/octet-stream', size: 0, preview_type: 'external', status: 'uploading' }]
  }
  function addUploaded(attachment: CoreAttachment) {
    const uploaded: CoreAttachment = { ...attachment, status: 'uploaded' };
    pendingAttachments.value = [
      ...pendingAttachments.value.filter(item => item.id !== uploaded.id),
      uploaded,
    ];
  }

  function markFailed(id: string, filename: string, error: string) {
    const failed: CoreAttachment = {
      id,
      filename,
      label: filename,
      mime_type: 'application/octet-stream',
      size: 0,
      preview_type: 'external',
      status: 'failed',
      error,
      path: pendingAttachments.value.find(item => item.id === id)?.path,
    };
    pendingAttachments.value = [
      ...pendingAttachments.value.filter(item => item.id !== id),
      failed,
    ];
  }

  function removeAttachment(id: string) {
    pendingAttachments.value = pendingAttachments.value.filter(item => item.id !== id);
  }

  function clearAttachments() {
    pendingAttachments.value = [];
  }

  // user:“做吧”+(迟到的发送结果只能移除原聊天里已提交的附件，保留新增文件)。
  function removeSubmittedAttachments(sessionId: string, submitted: import('@/types.ts').CoreInputItem[]): void {
    const ids = new Set(submitted.filter(item => item.type === 'attachment').map(item => item.attachment_id))
    if (!ids.size) return
    if (currentSessionId === sessionId) {
      pendingAttachments.value = pendingAttachments.value.filter(item => !ids.has(item.id))
    } else {
      writeStoredAttachments(sessionId, readStoredAttachments(sessionId).filter(item => !ids.has(item.id)))
    }
  }

  return {
    pendingAttachments,
    hasBlockingFailure,
    attachmentInputItems,
    addUploaded,
    addProcessing,
    markFailed,
    removeAttachment,
    clearAttachments,
    removeSubmittedAttachments,
    setSession,
    persistCurrent,
  };
}
