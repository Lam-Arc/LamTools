import type { CoreSessionGroup, ProductAdapter } from '@/types.ts'

/**
 * Create a standard product adapter object.
 */
export function createProductAdapter(
  id: string,
  displayName: string,
  version: string,
  supportedFeatures: string[],
): ProductAdapter {
  return { id, displayName, version, supportedFeatures }
}

/**
 * Create a standard session group for a member.
 */
export function createMemberSessionGroup(
  memberId: string,
  label: string,
  description?: string,
): CoreSessionGroup {
  return {
    id: `${memberId}-sessions`,
    label,
    description: description || `All ${label}`,
  }
}
