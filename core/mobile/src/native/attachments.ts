import { invoke } from '@tauri-apps/api/core'
import b4a from 'b4a'

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

/**
 * Bytes already read this session.
 *
 * An attachment is immutable: `save` always mints a new random id, so the bytes
 * behind an id never change and only `delete` can invalidate them. Replaying a
 * conversation reads every image in it again - the durable history carries only
 * attachment ids - so without this, a session with photos re-read all of them
 * from disk and across the IPC on every single turn.
 */
const READ_CACHE_BUDGET_BYTES = 32 * 1024 * 1024
const readCache = new Map<string, NativeAttachmentData>()
let readCacheBytes = 0

function cacheRead(data: NativeAttachmentData): void {
  const size = data.bytes.length
  if (size > READ_CACHE_BUDGET_BYTES) return
  if (readCache.has(data.metadata.id)) return
  readCache.set(data.metadata.id, data)
  readCacheBytes += size
  while (readCacheBytes > READ_CACHE_BUDGET_BYTES && readCache.size > 1) {
    const oldest = readCache.keys().next().value as string | undefined
    if (oldest == null) break
    readCacheBytes -= readCache.get(oldest)?.bytes.length || 0
    readCache.delete(oldest)
  }
}

function forgetRead(id: string): void {
  const cached = readCache.get(id)
  if (!cached) return
  readCacheBytes -= cached.bytes.length
  readCache.delete(id)
}

/** Drop every cached attachment body; used when the panel deletes a session. */
export function clearAttachmentReadCache(): void {
  readCache.clear()
  readCacheBytes = 0
}

export const nativeAttachments: AttachmentClient = {
  async save({ sessionId, filename, mime, bytes }) {
    if (bytes.length > MAX_ATTACHMENT_BYTES) throw new AttachmentRequestError(413, '附件超过 50 MiB 限制')
    const metadata = await invoke<NativeAttachmentMetadata>('sunday_attachment_save', {
      sessionId, filename, mime, dataBase64: b4a.toString(bytes, 'base64'),
    })
    // The bytes are in hand and the id is final, so the turn that uploads a photo
    // does not have to read it straight back.
    cacheRead({ metadata, bytes })
    return metadata
  },
  async read(id) {
    const cached = readCache.get(id)
    if (cached) {
      // Refresh the recency order the budget evicts by.
      readCache.delete(id)
      readCache.set(id, cached)
      return cached
    }
    const result = await invoke<{ metadata: NativeAttachmentMetadata; data_base64: string }>(
      'sunday_attachment_read', { id },
    )
    const data = { metadata: result.metadata, bytes: decodeAttachmentBytes(result.data_base64) }
    cacheRead(data)
    return data
  },
  async list(sessionId) {
    return await invoke<NativeAttachmentMetadata[]>('sunday_attachment_list', { sessionId })
  },
  async delete(id) {
    const deleted = await invoke<boolean>('sunday_attachment_delete', { id })
    forgetRead(id)
    return deleted
  },
  async open(id) {
    await invoke<void>('sunday_attachment_open', { id })
  },
}

/**
 * Whether `value` is a well-formed base64 body.
 *
 * Scanned character by character rather than matched with a regex: the
 * equivalent pattern backtracks quad by quad, and on a multi-megabyte payload
 * that blows the webview's stack (`RangeError: Maximum call stack size
 * exceeded`) instead of validating anything. Attachments reach 50 MiB.
 */
export function isBase64Body(value: string): boolean {
  const length = value.length
  if (length === 0) return true
  if (length % 4 !== 0) return false
  const padding = value.endsWith('==') ? 2 : value.endsWith('=') ? 1 : 0
  const body = length - padding
  for (let index = 0; index < body; index += 1) {
    const code = value.charCodeAt(index)
    const valid = (code >= 0x41 && code <= 0x5a) // A-Z
      || (code >= 0x61 && code <= 0x7a) // a-z
      || (code >= 0x30 && code <= 0x39) // 0-9
      || code === 0x2b // +
      || code === 0x2f // /
    if (!valid) return false
  }
  for (let index = body; index < length; index += 1) {
    if (value.charCodeAt(index) !== 0x3d) return false
  }
  return true
}

/** The byte length a base64 body decodes to, or `null` when it is malformed. */
export function decodedBase64Length(value: string): number | null {
  if (!isBase64Body(value)) return null
  const padding = value.endsWith('==') ? 2 : value.endsWith('=') ? 1 : 0
  return (value.length / 4) * 3 - padding
}

/** The 50 MiB ceiling still holds: the check moved from the JSON array to the base64 body. */
function decodeAttachmentBytes(value: unknown): Uint8Array {
  if (typeof value !== 'string' || !isBase64Body(value)) {
    throw new Error('附件内容无效')
  }
  const bytes = b4a.from(value, 'base64')
  if (bytes.length > MAX_ATTACHMENT_BYTES) throw new Error('附件内容无效')
  return bytes
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
