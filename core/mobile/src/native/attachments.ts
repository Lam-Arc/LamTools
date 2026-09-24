import { invoke } from '@tauri-apps/api/core'

export const MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
const MAX_MULTIPART_OVERHEAD = 64 * 1024

export interface NativeAttachmentMetadata {
  id: string
  session_id: string
  filename: string
  mime_type: string
  size: number
  preview_type: string
}

export interface NativeAttachmentData {
  metadata: NativeAttachmentMetadata
  bytes: Uint8Array
}

export interface AttachmentClient {
  save(input: { sessionId: string; filename: string; mime: string; bytes: Uint8Array }): Promise<NativeAttachmentMetadata>
  read(id: string): Promise<NativeAttachmentData>
  list(sessionId: string): Promise<NativeAttachmentMetadata[]>
  delete(id: string): Promise<boolean>
  open(id: string): Promise<void>
}

export const nativeAttachments: AttachmentClient = {
  async save({ sessionId, filename, mime, bytes }) {
    if (bytes.length > MAX_ATTACHMENT_BYTES) throw new AttachmentRequestError(413, '附件超过 50 MiB 限制')
    return await invoke<NativeAttachmentMetadata>('sunday_attachment_save', {
      sessionId, filename, mime, bytes: Array.from(bytes),
    })
  },
  async read(id) {
    const result = await invoke<{ metadata: NativeAttachmentMetadata; bytes: number[] }>('sunday_attachment_read', { id })
    if (!Array.isArray(result.bytes) || result.bytes.length > MAX_ATTACHMENT_BYTES) {
      throw new Error('附件内容无效')
    }
    return { metadata: result.metadata, bytes: Uint8Array.from(result.bytes) }
  },
  async list(sessionId) {
    return await invoke<NativeAttachmentMetadata[]>('sunday_attachment_list', { sessionId })
  },
  async delete(id) {
    return await invoke<boolean>('sunday_attachment_delete', { id })
  },
  async open(id) {
    await invoke<void>('sunday_attachment_open', { id })
  },
}

export class AttachmentRequestError extends Error {
  constructor(readonly status: number, message: string) { super(message) }
}

export interface MultipartFile {
  filename: string
  mime: string
  bytes: Uint8Array
}

export function parseMultipartFile(body: Uint8Array | undefined, contentType: string | undefined): MultipartFile {
  if (!body?.length) throw new AttachmentRequestError(400, '附件请求缺少文件内容')
  if (body.length > MAX_ATTACHMENT_BYTES + MAX_MULTIPART_OVERHEAD) {
    throw new AttachmentRequestError(413, '附件超过 50 MiB 限制')
  }
  const boundary = /(?:^|;)\s*boundary=(?:"([A-Za-z0-9_-]{1,100})"|([A-Za-z0-9_-]{1,100}))(?:\s*;|\s*$)/i
    .exec(contentType || '')?.slice(1).find(Boolean)
  if (!/^multipart\/form-data(?:\s*;|$)/i.test(contentType || '') || !boundary) {
    throw new AttachmentRequestError(400, '附件请求缺少有效的 multipart 边界')
  }
  const encoder = new TextEncoder()
  const startMarker = encoder.encode(`--${boundary}\r\n`)
  if (!bytesEqual(body.subarray(0, startMarker.length), startMarker)) {
    throw new AttachmentRequestError(400, '附件 multipart 起始边界无效')
  }
  const headerEnd = findBytes(body, encoder.encode('\r\n\r\n'), startMarker.length, Math.min(body.length, 16 * 1024))
  if (headerEnd < 0) throw new AttachmentRequestError(400, '附件 multipart 文件头无效')
  const header = new TextDecoder('utf-8', { fatal: true }).decode(body.subarray(startMarker.length, headerEnd))
  const disposition = /^content-disposition:\s*form-data;[^\r\n]*$/im.exec(header)?.[0] || ''
  if (!/;\s*name="file"(?:;|$)/i.test(disposition)) {
    throw new AttachmentRequestError(400, '附件 multipart 缺少 file 字段')
  }
  const filename = /;\s*filename="([^"\r\n]*)"/i.exec(disposition)?.[1] || ''
  if (!filename) throw new AttachmentRequestError(400, '附件文件名为空')
  const mime = /^content-type:\s*([^\r\n]+)$/im.exec(header)?.[1]?.trim() || 'application/octet-stream'
  const dataStart = headerEnd + 4
  const endMarker = encoder.encode(`\r\n--${boundary}--`)
  const dataEnd = findBytes(body, endMarker, dataStart)
  if (dataEnd < 0) throw new AttachmentRequestError(400, '附件 multipart 结束边界无效')
  const bytes = body.slice(dataStart, dataEnd)
  if (bytes.length > MAX_ATTACHMENT_BYTES) throw new AttachmentRequestError(413, '附件超过 50 MiB 限制')
  const afterBoundary = dataEnd + endMarker.length
  const trailing = body.subarray(afterBoundary)
  if (trailing.length && !bytesEqual(trailing, encoder.encode('\r\n'))) {
    throw new AttachmentRequestError(400, '附件 multipart 存在多余内容')
  }
  return { filename, mime, bytes }
}

function bytesEqual(left: Uint8Array, right: Uint8Array): boolean {
  return left.length === right.length && left.every((byte, index) => byte === right[index])
}

function findBytes(haystack: Uint8Array, needle: Uint8Array, start: number, stop = haystack.length): number {
  for (let at = start; at + needle.length <= stop;) {
    at = haystack.indexOf(needle[0], at)
    if (at < 0 || at + needle.length > stop) break
    let match = true
    for (let offset = 1; offset < needle.length; offset++) {
      if (haystack[at + offset] !== needle[offset]) { match = false; break }
    }
    if (match) return at
    at++
  }
  return -1
}
