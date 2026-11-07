/**
 * 桌宠创建草稿（IndexedDB）。
 *
 * user:“角色创建中途关闭页面，重进可恢复上次草稿；至少 20 次模拟中断不丢资源”+
 * (图片字节太大，不能塞 localStorage；这里用浏览器 IndexedDB 保存最近一次
 *  创建草稿，成功发布或用户主动清空后删除。)
 */
import type { CreationFile } from './creation.ts'

export interface CreationDraft {
  name: string
  files: CreationFile[]
  updatedAt: number
}

const DB_NAME = 'lamtools-pet-drafts'
const STORE = 'drafts'
const KEY = 'create'
const VERSION = 1
const MAX_DRAFT_BYTES = 120 * 1024 * 1024

function hasIndexedDb(): boolean {
  return typeof indexedDB !== 'undefined'
}

function openDatabase(): Promise<IDBDatabase | null> {
  if (!hasIndexedDb()) return Promise.resolve(null)
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('创建草稿数据库失败'))
  })
}

export async function saveCreationDraft(draft: CreationDraft): Promise<void> {
  const total = draft.files.reduce((sum, file) => sum + file.bytes.byteLength, 0)
  if (draft.files.length === 0 || total > MAX_DRAFT_BYTES) return
  const db = await openDatabase()
  if (!db) return
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, 'readwrite')
      transaction.objectStore(STORE).put({ ...draft, updatedAt: Date.now() }, KEY)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error || new Error('保存创建草稿失败'))
    })
  } finally {
    db.close()
  }
}

export async function loadCreationDraft(): Promise<CreationDraft | null> {
  const db = await openDatabase()
  if (!db) return null
  try {
    return await new Promise<CreationDraft | null>((resolve, reject) => {
      const transaction = db.transaction(STORE, 'readonly')
      const request = transaction.objectStore(STORE).get(KEY)
      request.onsuccess = () => {
        const value = request.result as CreationDraft | undefined
        if (!value || !Array.isArray(value.files)) {
          resolve(null)
          return
        }
        resolve({
          name: String(value.name || ''),
          files: value.files.map(file => ({
            name: String(file.name || 'image.png'),
            size: Number(file.size || file.bytes?.byteLength || 0),
            bytes: file.bytes instanceof Uint8Array ? file.bytes : new Uint8Array(file.bytes || []),
            width: Number(file.width || 0),
            height: Number(file.height || 0),
          })),
          updatedAt: Number(value.updatedAt || 0),
        })
      }
      request.onerror = () => reject(request.error || new Error('读取创建草稿失败'))
    })
  } finally {
    db.close()
  }
}

export async function clearCreationDraft(): Promise<void> {
  const db = await openDatabase()
  if (!db) return
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(STORE, 'readwrite')
      transaction.objectStore(STORE).delete(KEY)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error || new Error('清空创建草稿失败'))
    })
  } finally {
    db.close()
  }
}
