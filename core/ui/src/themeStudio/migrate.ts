import {
  THEME_STUDIO_SCHEMA_VERSION,
  type StudioDocument,
} from './schema.ts'

/**
 * 主题文档迁移。
 *
 * user:“主题保存、导入导出与恢复机制”+
 * (旧版本主题必须能升级到当前版本；未来版本的文档不能被静默降级，
 *  迁移失败时保留原文，不覆写用户数据。)
 */

export type StudioMigrationResult =
  | { ok: true; document: StudioDocument; from: number; migrated: boolean }
  | { ok: false; error: string; raw: unknown }

/** 各历史版本的升级步骤；每步只负责把上一版补成这一版。 */
const MIGRATIONS: Record<number, (raw: Record<string, unknown>) => Record<string, unknown>> = {
  // 0 → 1：早期没有版本字段，补齐结构即可。
  0: (raw) => ({
    schemaVersion: 1,
    themeId: typeof raw.themeId === 'string' ? raw.themeId : 'custom',
    nodes: raw.nodes && typeof raw.nodes === 'object' ? raw.nodes : {},
    templates: raw.templates && typeof raw.templates === 'object' ? raw.templates : {},
    instances: raw.instances && typeof raw.instances === 'object' ? raw.instances : {},
    breakpoints: Array.isArray(raw.breakpoints) ? raw.breakpoints : [],
    assets: Array.isArray(raw.assets) ? raw.assets : [],
    updatedAt: typeof raw.updatedAt === 'string' ? raw.updatedAt : new Date().toISOString(),
  }),
}

export function migrateStudioDocument(raw: unknown): StudioMigrationResult {
  if (!raw || typeof raw !== 'object') {
    return { ok: false, error: '主题文档必须是对象', raw }
  }
  const record = { ...(raw as Record<string, unknown>) }
  const version = typeof record.schemaVersion === 'number' ? record.schemaVersion : 0

  if (version > THEME_STUDIO_SCHEMA_VERSION) {
    return {
      ok: false,
      error: `主题版本 ${version} 高于当前支持的 ${THEME_STUDIO_SCHEMA_VERSION}，请升级应用`,
      raw,
    }
  }

  let current = record
  let migrated = false
  for (let from = version; from < THEME_STUDIO_SCHEMA_VERSION; from += 1) {
    const step = MIGRATIONS[from]
    if (!step) {
      return { ok: false, error: `缺少 ${from} 到 ${from + 1} 的迁移步骤`, raw }
    }
    current = step(current)
    migrated = true
  }

  return {
    ok: true,
    document: current as unknown as StudioDocument,
    from: version,
    migrated,
  }
}
