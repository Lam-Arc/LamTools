import JSZip from 'jszip'
import type { CoreAppSnapshot, TransportHttpResponse } from '@lamtools/ui'
import type { LocalRepository } from '../storage'
import { nativeAttachments, type AttachmentClient, type NativeAttachmentMetadata } from '../native/attachments'

const encoder = new TextEncoder()

export async function exportStandaloneSession(
  repository: LocalRepository,
  threadId: string,
  request: Record<string, unknown>,
  attachmentStore: Pick<AttachmentClient, 'list' | 'read'> = nativeAttachments,
): Promise<TransportHttpResponse> {
  const session = (await repository.listSessions()).find(item => item.id === threadId)
  if (!session) return reply('会话不存在', 404)
  const snapshot = await repository.loadThreadSnapshot(threadId) as CoreAppSnapshot | null
  const mode = String(request.mode || 'transcript')
  const format = String(request.format || 'markdown')
  const entries = transcript(snapshot)
  const exportedAt = new Date().toISOString()
  if (mode === 'transcript') {
    let output: string
    let type: string
    if (format === 'markdown') {
      output = entries.map(entry => `## ${entry.role} · ${entry.timestamp}\n\n${entry.text}`).join('\n\n') + (entries.length ? '\n' : '')
      type = 'text/markdown; charset=utf-8'
    } else if (format === 'txt') {
      output = entries.map(entry => entry.text).join('\n\n') + (entries.length ? '\n' : '')
      type = 'text/plain; charset=utf-8'
    } else if (format === 'jsonl') {
      output = entries.map(entry => JSON.stringify(entry)).join('\n') + (entries.length ? '\n' : '')
      type = 'application/x-ndjson; charset=utf-8'
    } else return reply('不支持的导出格式', 400)
    return { status: 200, headers: { 'content-type': type }, body: encoder.encode(output) }
  }
  const handoff = {
    schema: 'lamtools.handoff.v1',
    context: entries.map(entry => ({ role: entry.role.toLowerCase(), content: entry.text })),
  }
  if (mode === 'handoff' && format === 'json') {
    return { status: 200, headers: { 'content-type': 'application/json' }, body: encoder.encode(`${JSON.stringify(handoff, null, 2)}\n`) }
  }
  if (mode === 'full' && format === 'zip') {
    const zip = new JSZip()
    const files: Array<{ path: string; size: number }> = []
    const attachments: Array<NativeAttachmentMetadata & { archive_path: string; file_present: true }> = []
    for (const record of await attachmentStore.list(threadId)) {
      if (!/^[0-9a-f]{32}$/.test(record.id)) throw new Error('附件 ID 无效，导出已停止')
      const { metadata, bytes } = await attachmentStore.read(record.id)
      if (metadata.id !== record.id || metadata.session_id !== threadId || metadata.size !== bytes.length) {
        throw new Error('附件内容与元数据不一致，导出已停止')
      }
      const path = `attachments/${record.id}/content.bin`
      zip.file(path, bytes)
      attachments.push({ ...metadata, archive_path: path, file_present: true })
      files.push({ path, size: bytes.length })
    }
    zip.file('manifest.json', JSON.stringify({ schema: 'lamtools.mobile.full', version: 1, exported_at: exportedAt, thread_id: threadId, files }, null, 2))
    zip.file('session.json', JSON.stringify(session, null, 2))
    zip.file('snapshot.json', JSON.stringify(snapshot || {}, null, 2))
    zip.file('transcript.jsonl', entries.map(entry => JSON.stringify(entry)).join('\n') + (entries.length ? '\n' : ''))
    zip.file('handoff.json', JSON.stringify(handoff, null, 2))
    zip.file('attachments.jsonl', attachments.map(record => JSON.stringify(record)).join('\n') + (attachments.length ? '\n' : ''))
    const body = await zip.generateAsync({ type: 'uint8array', compression: 'DEFLATE' })
    return { status: 200, headers: { 'content-type': 'application/zip' }, body }
  }
  return reply('不支持的导出模式', 400)
}

function transcript(snapshot: CoreAppSnapshot | null): Array<{ timestamp: string; role: string; text: string }> {
  if (!snapshot?.core) return []
  const core = snapshot.core
  const rows: Array<{ timestamp: string; role: string; text: string }> = []
  for (const id of core.item_order || []) {
    const item = core.items?.[id]
    if (!item || (item.type !== 'userMessage' && item.type !== 'agentMessage')) continue
    const payload = item.payload as Record<string, unknown> | undefined
    const content = payload?.content ?? item.content
    const text = typeof content === 'string' ? content : Array.isArray(content)
      ? content.map(part => typeof part === 'object' && part && 'text' in part ? String(part.text) : '').filter(Boolean).join('\n') : ''
    if (!text) continue
    const turn = core.turns?.[String(item.turn_id || '')]
    rows.push({ timestamp: String(turn?.created_at || ''), role: item.type === 'userMessage' ? 'user' : 'assistant', text })
  }
  return rows
}

function reply(message: string, status: number): TransportHttpResponse {
  return { status, headers: { 'content-type': 'text/plain; charset=utf-8' }, body: encoder.encode(message) }
}
