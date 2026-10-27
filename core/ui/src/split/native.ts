import { invoke } from '@tauri-apps/api/core'
export interface SplitFileEntry { name: string; path: string; directory: boolean }
export function hasSplitNative(): boolean { return typeof window !== 'undefined' && Boolean((window as unknown as Record<string, unknown>).__TAURI_INTERNALS__) }
export async function splitNative<T>(command: string, args: Record<string, unknown>): Promise<T> {
  if (!hasSplitNative()) throw Error('此功能需要在桌面应用中使用')
  return invoke<T>(command, args)
}
export async function browserNative(id: string, action: string, options: Record<string, unknown> = {}) { return splitNative<void>('split_browser', { request: { id, action, ...options } }) }
