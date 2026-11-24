/**
 * 未确认送达的写操作，跨重启保留。
 *
 * user:“断线后恢复未确认的消息与任务状态”“不确定送达时先查询状态，不盲目重发”+
 * (界面原来的「未知」只活在内存里：应用一重开，用户就再也分不清那条消息是没发出去、
 * 还是发出去了但没收到回执。这里只在本地留一份有 TTL 的账本，重发仍然复用同一个
 * `client_message_id`，由 Core 去重)。
 */

import type { CoreAppEvent } from '@/appServer/protocol.ts'

const STORAGE_KEY = 'sunday.pendingWrites.v1'

// user:“全修”+(发送、编辑、恢复、排队、引导共用持久接收凭据的判定)。
const receiptMethods = {
  'turn/start': ['turn/accepted'],
  'turn/replace': ['turn/accepted'],
  'turn/resume': ['turn/started'],
  'turn/steer': ['turn/steered', 'queue/itemAccepted', 'turn/accepted'],
  'queue/create': ['queue/itemAccepted'],
} as const

export type PendingWriteMethod = keyof typeof receiptMethods

export function isPendingWriteMethod(method: unknown): method is PendingWriteMethod {
  return typeof method === 'string' && Object.hasOwn(receiptMethods, method)
}

export function matchesWriteReceipt(method: PendingWriteMethod, event: CoreAppEvent): boolean {
  return (receiptMethods[method] as readonly string[]).includes(event.method)
}

export function readWriteReceipt(
  response: Record<string, unknown>, method: PendingWriteMethod, threadId: string, messageId: string,
): CoreAppEvent | undefined {
  if (!Array.isArray(response.events)) return undefined
  return (response.events as CoreAppEvent[]).find(event => event?.thread_id === threadId
    && event.client_message_id === messageId && matchesWriteReceipt(method, event))
}

export function writeReceiptResponse(method: PendingWriteMethod, event: CoreAppEvent): Record<string, unknown> {
  if (method === 'queue/create') return { accepted: true, replayed: true, events: [event] }
  if (method === 'turn/steer') return {
    applied: event.method === 'turn/steered', queued: event.method === 'queue/itemAccepted',
    submitted: event.method === 'turn/accepted', turn_id: event.turn_id, events: [event],
  }
  return { events: [event], ...(method === 'turn/resume' ? { turn_id: event.turn_id } : {}) }
}

/** 超过一天还没 settles 的写不再保留：会话早就翻页了，重发只会制造旧消息。 */
export const PENDING_WRITE_TTL_MS = 24 * 60 * 60 * 1000

export interface PendingWrite {
  /** `threadId::clientMessageId`，作为去重键。 */
  key: string
  threadId: string
  clientMessageId: string
  method: PendingWriteMethod
  createdAt: number
  expiresAt: number
}

interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

function isPendingWrite(value: unknown): value is PendingWrite {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<PendingWrite>
  return (
    typeof item.key === 'string'
    && typeof item.threadId === 'string'
    && typeof item.clientMessageId === 'string'
    // user:“全做”+(编辑断线时也保留可以查回执的提交身份)。
    && isPendingWriteMethod(item.method)
    && typeof item.createdAt === 'number'
    && typeof item.expiresAt === 'number'
  )
}

/** 一条未确认写的本地键。 */
export function pendingKey(threadId: string, clientMessageId: string): string {
  return `${threadId}::${clientMessageId}`
}

/**
 * 读出仍然有效的未确认写；过期的顺手清掉。
 *
 * 每次读取都做一次 TTL 清理，不另起定时器：账本只在真正需要时才被看见。
 */
export function loadPendingWrites(
  now = Date.now(),
  storage: StorageLike | null = defaultStorage(),
): PendingWrite[] {
  if (!storage) return []
  try {
    const parsed = JSON.parse(storage.getItem(STORAGE_KEY) || '[]') as unknown
    if (!Array.isArray(parsed)) return []
    const valid = parsed.filter(isPendingWrite)
    const live = valid.filter((item) => item.expiresAt > now)
    if (live.length !== parsed.length) {
      storage.setItem(STORAGE_KEY, JSON.stringify(live))
    }
    return live
  } catch {
    return []
  }
}

/** 记下一条「发出去了但没收到回执」的写；同键覆盖，不堆重复。 */
export function rememberPendingWrite(
  entry: PendingWrite,
  now = Date.now(),
  storage: StorageLike | null = defaultStorage(),
): PendingWrite[] {
  if (!storage) return []
  const live = loadPendingWrites(now, storage).filter((item) => item.key !== entry.key)
  live.push(entry)
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(live))
  } catch {
    // 存储不可用只影响跨重启恢复，这一次仍然能用。
  }
  return live
}

/** 收到回执 / 看到业务事件之后，把这条从未确认清单里去掉。 */
export function settlePendingWrite(
  key: string,
  now = Date.now(),
  storage: StorageLike | null = defaultStorage(),
): PendingWrite[] {
  if (!storage) return []
  const previous = loadPendingWrites(now, storage)
  const live = previous.filter((item) => item.key !== key)
  if (live.length === previous.length) return live
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(live))
  } catch {
    // 同上。
  }
  return live
}

/** 某条会话里还没收尾的写（界面要提示「上次还有 N 条没确认」时用）。 */
export function pendingWritesFor(
  threadId: string,
  now = Date.now(),
  storage: StorageLike | null = defaultStorage(),
): PendingWrite[] {
  return loadPendingWrites(now, storage).filter((item) => item.threadId === threadId)
}
