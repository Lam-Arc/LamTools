/**
 * 桌宠配置文件的唯一读写入口。
 *
 * user:“桌宠设置：在设置里单独放一份，并持久化。这份的持久化是唯一源。包括右键
 * 出来的那个面板，修改之后也应该是去改这个持久化的文件，ping也是同理”+
 * (主界面设置、桌宠设置面板、右键面板、Ping 面板都只通过这里读写同一份
 *  .lam/pet/config.json；写入走 Rust 的 pet_config_patch，在同一把锁内做
 *  read-modify-write，后写者不会用旧副本覆盖别人刚改的字段。)
 */
import { migrateConfig, PET_CONFIG_VERSION, type PetConfigV1 } from './config.ts'

export function hasPetConfigAccess(): boolean {
  return typeof (globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ === 'object'
}

async function invokePet<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core')
  return await invoke<T>(command, args)
}

export async function readPetConfigText(): Promise<string | null> {
  if (!hasPetConfigAccess()) return null
  return await invokePet<string | null>('pet_config_read')
}

/**
 * 读取并迁移配置。迁移结果会立刻落盘：L3 默认关闭、presetVersion 等一次性
 * 迁移不能等到用户下一次编辑才生效。
 */
export async function readPetConfig(): Promise<PetConfigV1 | null> {
  const text = await readPetConfigText()
  if (!text) return null
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    return null
  }
  const migrated = migrateConfig(parsed)
  if (migrated.migratedFrom !== null) {
    try {
      // 迁移要广播：已经打开的桌宠窗口必须把内存里的旧 L3=true 一起换掉，
      // 否则它下一次保存会把迁移结果覆盖回去。
      await patchPetConfig({ ...migrated.config })
    } catch {
      // 只读预览/权限不足时仍返回内存中的迁移结果，下一次可写时再落盘。
    }
  }
  return migrated.config
}

export interface PatchPetConfigOptions {
  /** false 时不广播 config-changed（读迁移、内部写回用）。 */
  notify?: boolean
}

/** 只提交自己拥有的字段；Rust 侧递归合并对象、整体替换数组。 */
export async function patchPetConfig(
  patch: Record<string, unknown>,
  options: PatchPetConfigOptions = {},
): Promise<PetConfigV1> {
  if (!hasPetConfigAccess()) throw new Error('桌宠设置仅在桌面版可用')
  // 每次写入都带上当前版本号，避免局部 patch 让文件停留在旧版本、反复触发迁移。
  const payload = { version: PET_CONFIG_VERSION, ...patch }
  const text = await invokePet<string>('pet_config_patch', { patch: JSON.stringify(payload) })
  if (options.notify !== false) await emitPetConfigChanged()
  return migrateConfig(JSON.parse(text)).config
}

/** 先读最新文件再应用变更，避免主界面表单持有旧副本时覆盖别人刚写入的字段。 */
export async function updatePetConfig(
  mutate: (latest: PetConfigV1) => Record<string, unknown>,
  options: PatchPetConfigOptions = {},
): Promise<PetConfigV1> {
  const latest = await readPetConfig()
  if (!latest) throw new Error('找不到桌宠配置')
  return await patchPetConfig(mutate(latest), options)
}

/** 通知所有桌宠相关窗口重读文件（文件是唯一源）。 */
export async function emitPetConfigChanged(): Promise<void> {
  try {
    const { emit } = await import('@tauri-apps/api/event')
    await emit('pet://config-changed')
  } catch {
    // 浏览器预览没有 Tauri 事件。
  }
}
