import { computed, ref } from 'vue';
import type { CoreAttachment, CoreAttachmentInputItem } from '@/types.ts';

export function usePendingAttachments() {
  const pendingAttachments = ref<CoreAttachment[]>([]);

  const hasBlockingFailure = computed(() =>
    pendingAttachments.value.some(item => item.status === 'failed'),
  );

  const attachmentInputItems = computed<CoreAttachmentInputItem[]>(() =>
    pendingAttachments.value
      .filter(item => item.status !== 'failed')
      .map(item => ({
        type: 'attachment',
        attachment_id: item.id,
        filename: item.filename,
        mime_type: item.mime_type,
        preview_type: item.preview_type,
        size: item.size,
      })),
  );

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

  return {
    pendingAttachments,
    hasBlockingFailure,
    attachmentInputItems,
    addUploaded,
    markFailed,
    removeAttachment,
    clearAttachments,
  };
}
