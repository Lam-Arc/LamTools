/**
 * Ping 配置的逻辑仓储。
 *
 * user:“两个页面分别承担配置 + 编辑 + 预览 + 模拟测试 + 管理 + 诊断职责”+
 * “保存策略……不得一个窗口用旧整对象覆盖另一个窗口刚更新的子字段”+
 * (当前阶段仍共用 .lam/pet/config.json 这一个物理文件，但 Ping 工作台只提交
 *  自己拥有的 ping / bindings.ping 片段；Rust 在同一把锁里递归合并。这样即使
 *  尚未拆成 ping/config.json，也不会用整份配置覆盖桌宠字段。)
 */
import { defaultConfig, migrateConfig, PET_CONFIG_VERSION, type PingConfig, type PingSectorConfig } from './config.ts'
import { hasPetConfigAccess, patchPetConfig, readPetConfig, updatePetConfig } from './configFile.ts'

export type PingPatch = Partial<Omit<PingConfig, 'sectors'>> & { sectors?: PingSectorConfig[] }

export function defaultPingConfig(): PingConfig {
  return defaultConfig().ping
}

/** 只读取 Ping 领域；文件缺失时返回默认值。 */
export async function readPingConfig(): Promise<PingConfig> {
  if (!hasPetConfigAccess()) return defaultPingConfig()
  const config = await readPetConfig()
  return config?.ping || defaultPingConfig()
}

/** 只提交 Ping 字段；不会把桌宠字段整体写回。 */
export async function patchPingConfig(patch: PingPatch): Promise<PingConfig> {
  if (!hasPetConfigAccess()) throw new Error('Ping 设置仅在桌面版可用')
  const config = await updatePetConfig(latest => ({
    version: PET_CONFIG_VERSION,
    ping: {
      ...latest.ping,
      ...patch,
      // 数组必须整体替换，不能让 Rust 的递归合并把旧扇区拼回来。
      ...(patch.sectors ? { sectors: patch.sectors } : {}),
    },
  }))
  return config.ping
}

/** Ping 目标单独写，绝不触碰桌宠绑定。 */
export async function patchPingTarget(
  target: { projectId: string | null; sessionId: string | null },
): Promise<void> {
  if (!hasPetConfigAccess()) throw new Error('Ping 设置仅在桌面版可用')
  await updatePetConfig(latest => ({
    ping: { ...latest.ping, target },
    bindings: { ping: target },
  }))
}

/** 把旧版内嵌 ping 字段迁移成当前 schema；纯函数便于回归测试。 */
export function normalizePingConfig(raw: unknown): PingConfig {
  const input = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  const migrated = migrateConfig({
    version: PET_CONFIG_VERSION,
    // migrateConfig 需要整份桌宠配置；这里只把 Ping 输入挂到 ping 字段，
    // 其余字段由默认值补齐。
    ping: input,
  })
  return migrated.config.ping
}
