/**
 * Model catalog shared types.
 *
 * Extracted from CoreSettings.vue so the catalog surface (CoreModelCatalog)
 * and the settings shell can share one contract without importing each other.
 */

export type SettingsCatalogMutation =
  | 'create-provider'
  | 'update-provider'
  | 'create-model'
  | 'update-model'
  | 'create-model-group'
  | 'update-model-group'
  | 'set-model-group-members'
  | 'create-model-with-provider'

export interface CoreModelPricing {
  input_per_1m?: number
  output_per_1m?: number
  cache_read_per_1m?: number
  cache_write_per_1m?: number
  currency?: string
}

export interface CoreSettingsModel {
  id: string
  provider_id?: string
  provider_name?: string
  model_id?: string
  display_name?: string
  context_window?: number
  max_output_tokens?: number
  thinking_supported?: boolean
  thinking_budget?: number
  temperature?: number
  is_default?: boolean
  enabled?: boolean
  capability?: string
  notes?: string
  pricing?: CoreModelPricing
  extra?: Record<string, unknown> | null
}

export interface CoreSettingsProvider {
  id: string
  name?: string
  api_type?: string
  base_url?: string
  has_api_key?: boolean
  extra?: Record<string, unknown> | null
}

export interface CoreSettingsProviderPayload {
  provider_id?: string
  preset_id?: string
  name: string
  api_type: string
  base_url: string
  api_key?: string
  extra?: Record<string, unknown>
  models?: CoreSettingsModelPayload[]
  model_group_name?: string
}

export interface CoreSettingsModelGroup {
  id: string
  name: string
  model_ids: string[]
  revision?: number
  is_system?: boolean
}

export interface CoreSettingsModelPayload {
  model_record_id?: string
  provider_id: string
  provider_name?: string
  model_id: string
  display_name: string
  context_window: number
  max_output_tokens: number
  thinking_supported: boolean
  thinking_budget: number
  temperature: number
  is_default?: boolean
  enabled?: boolean
  capability?: string
  notes?: string
  pricing?: CoreModelPricing
  extra?: Record<string, unknown>
}

export type ModelCatalogRange = '24h' | '7d' | '30d'

export interface ModelUsageBucket {
  calls: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  tokens: number
}

export interface ModelUsageEntry extends ModelUsageBucket {
  model_record_id: string
  model_id: string
  provider_id: string
  provider_name: string
  cost: number | null
  priced: boolean
  last_used_at?: string
}

export interface ProviderUsageEntry extends ModelUsageBucket {
  provider_id: string
  provider_name: string
  cost: number
  priced_tokens: number
  unpriced_tokens: number
  budget_usd: number | null
  month_cost: number
  month_tokens: number
}

export interface ModelUsageDay extends ModelUsageBucket {
  date: string
}

export interface ModelUsageSummary {
  range: ModelCatalogRange
  days: number
  totals: ModelUsageBucket & { cost: number; unpriced_tokens: number; currency: string }
  by_model: ModelUsageEntry[]
  by_provider: ProviderUsageEntry[]
  daily: ModelUsageDay[]
  series: Record<string, number[]>
  tracking_since: string
  since: string
}

export type ProviderConnectionState =
  | 'ok'
  | 'no_model_list'
  | 'rate_limited'
  | 'unauthorized'
  | 'missing_key'
  | 'unreachable'
  | 'error'
  | 'invalid'
  | 'unknown'

export interface ProviderConnectionStatus {
  state: ProviderConnectionState
  detail: string
  latency_ms: number
  http_status: number
  model_count: number
  checked_at: string
  cached?: boolean
}
