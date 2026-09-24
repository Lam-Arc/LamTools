/**
 * Plugin configuration on the phone.
 *
 * The desktop keeps one config file per plugin and validates it against the
 * plugin's `config/schema.jsonc`. The phone keeps one settings namespace per
 * plugin, and the namespace is the one the *runtime* reads, so what the panel
 * saves is what the agent uses. These helpers are shared by the panel surface
 * (`plugin.config.*` in the config store) and the plugin list (which reports
 * whether a plugin has a schema at all).
 */

/**
 * Where each bundled plugin's settings live.
 *
 * `imagegen` uses the namespace 设置 → 生图 writes and the runtime reads;
 * `websearch` is resolved into the search kernels by the host. A plugin absent
 * from this map has no settings on this device, and saying otherwise would be a
 * control that changes nothing.
 */
export const PLUGIN_CONFIG_NAMESPACES: Record<string, string> = {
  imagegen: 'core.imagegen',
  websearch: 'core.websearch',
}

/** Fields the desktop masks on read and preserves when submitted blank. */
const SECRET_FIELD_PATTERN = /(api[_-]?key|token|secret|password)/i

export function pluginConfigNamespace(name: string): string {
  return PLUGIN_CONFIG_NAMESPACES[name] || `plugin.${name}`
}

export function schemaProperties(schema: Record<string, unknown>): Record<string, Record<string, unknown>> {
  const properties = schema.properties
  return properties && typeof properties === 'object' && !Array.isArray(properties)
    ? properties as Record<string, Record<string, unknown>>
    : {}
}

export function hasSecretField(schema: Record<string, unknown>): boolean {
  return Object.keys(schemaProperties(schema)).some(key => SECRET_FIELD_PATTERN.test(key))
}

export function maskPluginSecrets(
  schema: Record<string, unknown>,
  config: Record<string, unknown>,
): Record<string, unknown> {
  const masked = { ...config }
  for (const key of Object.keys(schemaProperties(schema))) {
    if (!SECRET_FIELD_PATTERN.test(key)) continue
    if (typeof masked[key] === 'string' && masked[key]) masked[key] = '********'
  }
  return masked
}

export function preservePluginSecrets(
  schema: Record<string, unknown>,
  submitted: Record<string, unknown>,
  current: Record<string, unknown>,
): Record<string, unknown> {
  const merged = { ...submitted }
  for (const key of Object.keys(schemaProperties(schema))) {
    if (!SECRET_FIELD_PATTERN.test(key)) continue
    const value = merged[key]
    if (typeof value === 'string' && (value.trim() === '' || value === '********')) {
      merged[key] = current[key] ?? ''
    }
  }
  return merged
}

/**
 * Check submitted values against the schema the way the desktop's validator
 * does. Only the rules the bundled schemas actually use are enforced; anything
 * else is passed through rather than guessed at.
 */
export function validatePluginConfig(
  schema: Record<string, unknown>,
  submitted: Record<string, unknown>,
): string[] {
  const errors: string[] = []
  for (const [key, spec] of Object.entries(schemaProperties(schema))) {
    const value = submitted[key]
    if (value === undefined || value === null) continue
    const type = String(spec.type || '')
    if (type === 'string' && typeof value !== 'string') {
      errors.push(`${key} 必须是字符串`)
      continue
    }
    if (type === 'boolean' && typeof value !== 'boolean') {
      errors.push(`${key} 必须是布尔值`)
      continue
    }
    if (type === 'integer' && !Number.isInteger(value)) {
      errors.push(`${key} 必须是整数`)
      continue
    }
    if (type === 'number' && typeof value !== 'number') {
      errors.push(`${key} 必须是数字`)
      continue
    }
    if (type === 'array' && !Array.isArray(value)) {
      errors.push(`${key} 必须是数组`)
      continue
    }
    if (Array.isArray(spec.enum) && !spec.enum.includes(value)) {
      errors.push(`${key} 只能是 ${(spec.enum as unknown[]).join('/')}`)
      continue
    }
    if (typeof value === 'number') {
      if (typeof spec.minimum === 'number' && value < spec.minimum) {
        errors.push(`${key} 不能小于 ${spec.minimum}`)
        continue
      }
      if (typeof spec.maximum === 'number' && value > spec.maximum) {
        errors.push(`${key} 不能大于 ${spec.maximum}`)
      }
    }
  }
  return errors
}
