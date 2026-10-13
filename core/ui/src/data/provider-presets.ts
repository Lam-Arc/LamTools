export type ProviderPresetGroup = 'standard' | 'free'

export type ProviderPresetModel = {
  modelId: string
  displayName: string
  contextWindow: number
  maxOutputTokens: number
  thinkingSupported: boolean
  thinkingBudget: number
  temperature: number
  extra?: Record<string, unknown>
}

export type ProviderPreset = {
  id: string
  label: string
  name: string
  group: ProviderPresetGroup
  apiType: string
  baseUrl: string
  adapterProfile: string
  apiKeyUrl?: string
  docsUrl?: string
  /** Official upstream model-list endpoint and its latest model ID snapshot. */
  modelCatalogUrl?: string
  modelCatalogIds?: readonly string[]
  /** Some OpenAI-compatible APIs require an account-specific base URL. */
  baseUrlEditable?: boolean
  extra?: Record<string, unknown>
  defaultApiKey?: string
  defaultModelId: string
  models: ProviderPresetModel[]
}

export const PROVIDER_PRESET_GROUP_LABELS: Record<ProviderPresetGroup, string> = {
  standard: '标准模型',
  free: 'Free',
}

/** Keep upstream reasoning/request mappings model-specific on mixed gateways. */
export function providerPresetModelExtra(model: ProviderPresetModel): Record<string, unknown> {
  const extra = { ...(model.extra || {}) }
  if (typeof extra.adapter_profile_id === 'string' && extra.adapter_profile_id) return extra
  const id = model.modelId.toLowerCase()
  if (id.includes('deepseek')) extra.adapter_profile_id = 'deepseek-chat'
  else if (id.includes('qwen') || id.includes('qwq')) extra.adapter_profile_id = 'qwen'
  else if (id.includes('glm') || id.includes('chatglm')) extra.adapter_profile_id = 'glm'
  return extra
}

/** The OpenCode model-list APIs return IDs only, so leave unknown context unset. */
function openCodeFreeModel(
  modelId: string,
  displayName: string,
  extra: Record<string, unknown> = { capability: 'text' },
): ProviderPresetModel {
  return {
    modelId,
    displayName,
    contextWindow: 0,
    maxOutputTokens: 4096,
    thinkingSupported: true,
    thinkingBudget: 4096,
    temperature: 0.7,
    extra,
  }
}

// Official model-list snapshots fetched on 2026-10-13. Keep these separate from
// each preset's `models`, which are the models directly created for the user.
const OPENCODE_ZEN_SUPPORTED_MODEL_IDS = [
  'big-pickle', 'ling-3.1-flash-free', 'cat-jam-free', 'mimo-v2.6-flash-free',
  'muse-spark-1.2-contributor-free', 'muse-spark-1.3-contributor-free',
  'nemotron-3.5-lightning-free', 'jev-1.13-free', 'step-5-preview-free',
  'longcat-2.5-preview-free', 'space-bunny-free', 'claude-fable-5',
  'jev-1.13', 'claude-fable-5-1', 'claude-haiku-4-5', 'claude-haiku-5-5',
  'claude-opus-4-5', 'claude-opus-4-6', 'claude-opus-4-7', 'claude-opus-4-8',
  'claude-opus-5', 'claude-opus-5-5', 'claude-opus-5-5-backup',
  'claude-sonnet-4-5', 'claude-sonnet-4-6', 'claude-sonnet-5', 'claude-sonnet-5-5',
  'deepseek-v4-flash', 'deepseek-v4.1-flash', 'deepseek-v4-pro', 'gemini-3-flash',
  'gemini-3.1-pro', 'gemini-3.5-flash', 'gemini-3.5-flash-lite', 'gemini-3.6-flash',
  'gemini-3.7-flash', 'gemini-3.8-flash', 'glm-5', 'glm-5.1', 'glm-5.2', 'glm-5.3',
  'glm-5.3-flash', 'gpt-5', 'gpt-5-codex', 'gpt-5-nano', 'gpt-5.1',
  'gpt-5.1-codex', 'gpt-5.1-codex-max', 'gpt-5.1-codex-mini', 'gpt-5.2',
  'gpt-5.2-codex', 'gpt-5.3-codex', 'gpt-5.3-codex-spark', 'gpt-5.4',
  'gpt-5.4-mini', 'gpt-5.4-nano', 'gpt-5.4-pro', 'gpt-5.5', 'gpt-5.5-pro',
  'gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-astra', 'gpt-6-sol', 'gpt-6.1-sol',
  'gpt-6-luna', 'gpt-5.6-terra', 'grok-4.5', 'grok-4.6', 'grok-4.7',
  'grok-build-0.1', 'kimi-k2.5', 'kimi-k2.6', 'kimi-k2.7-code', 'kimi-k3',
  'minimax-m2.5', 'minimax-m2.7', 'minimax-m3', 'muse-spark-1.2',
  'muse-spark-1.3', 'mistral-large-4', 'qwen3.5-plus', 'qwen3.6-plus',
  'qwen3.8-flash', 'qwen3.8-max',
] as const

const OPENCODE_GO_SUPPORTED_MODEL_IDS = [
  'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp', 'deepseek-flash',
  'deepseek-v4.1-flash', 'deepseek-v4-pro', 'glm-5.1', 'glm-5.2', 'glm-5.3',
  'grok-4.6', 'grok-4.7', 'muse-spark-1.2-contributor',
  'muse-spark-1.3-contributor', 'glm-5.3-flash', 'omen-alpha', 'gpt-5.6-luna',
  'gpt-6-luna', 'claude-haiku-5-5', 'hy3', 'hy4-preview', 'kimi-k2.6',
  'kimi-k2.7-code', 'kimi-k3', 'mimo-v2.5', 'mimo-v2.6-flash', 'mimo-v2.5-pro',
  'mimo-v2.6-pro', 'minimax-m2.5', 'minimax-m2.7', 'minimax-m3', 'space-bunny',
  'longcat-2.0', 'longcat-2.5-preview-free', 'step-5-preview-free', 'cat-jam-free',
  'qwen3.6-plus', 'qwen3.7-max', 'qwen3.8-max', 'qwen3.8-flash', 'qwen3.7-plus',
] as const

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    name: 'OpenAI',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://api.openai.com/v1',
    adapterProfile: 'openai-chat',
    defaultModelId: 'gpt-4.1',
    models: [
      {
        modelId: 'gpt-4.1',
        displayName: 'GPT-4.1',
        contextWindow: 1047576,
        maxOutputTokens: 32768,
        thinkingSupported: false,
        thinkingBudget: 10000,
        temperature: 0.7,
      },
    ],
  },
  {
    id: 'anthropic',
    label: 'Claude / Anthropic',
    name: 'Anthropic',
    group: 'standard',
    apiType: 'anthropic',
    baseUrl: 'https://api.anthropic.com/v1',
    adapterProfile: 'anthropic-messages',
    defaultModelId: 'claude-sonnet-4-5',
    models: [
      {
        modelId: 'claude-sonnet-4-5',
        displayName: 'Claude Sonnet 4.5',
        contextWindow: 200000,
        maxOutputTokens: 8192,
        thinkingSupported: true,
        thinkingBudget: 10000,
        temperature: 0.7,
      },
    ],
  },
  {
    id: 'deepseek',
    label: 'DeepSeek',
    name: 'DeepSeek',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://api.deepseek.com',
    adapterProfile: 'deepseek-chat',
    defaultModelId: 'deepseek-flash',
    models: [
      {
        modelId: 'deepseek-flash',
        displayName: 'DeepSeek-V4.1-Flash',
        contextWindow: 1000000,
        maxOutputTokens: 393216,
        thinkingSupported: true,
        thinkingBudget: 10000,
        temperature: 0.7,
        extra: { capability: 'multimodal' },
      },
      {
        modelId: 'deepseek-v4-pro',
        displayName: 'DeepSeek-V4-Pro-0813',
        contextWindow: 1000000,
        maxOutputTokens: 393216,
        thinkingSupported: true,
        thinkingBudget: 10000,
        temperature: 0.7,
        extra: { capability: 'text' },
      },
    ],
  },
  {
    id: 'zhipu',
    label: '智谱 GLM',
    name: '智谱 GLM',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    adapterProfile: 'openai-chat',
    defaultModelId: 'glm-4.5',
    models: [
      {
        modelId: 'glm-4.5',
        displayName: 'GLM-4.5',
        contextWindow: 128000,
        maxOutputTokens: 16384,
        thinkingSupported: true,
        thinkingBudget: 10000,
        temperature: 0.7,
      },
    ],
  },
  {
    id: 'xfyun-coding',
    label: '讯飞 Coding',
    name: '讯飞 MaaS',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://maas-coding-api.cn-huabei-1.xf-yun.com/v2',
    adapterProfile: 'xfyun-coding-plan',
    defaultModelId: 'xopkimik26',
    models: [
      { modelId: 'xsparkx2', displayName: 'Spark X2', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xsparkx2agent', displayName: 'Spark-X2-Agent', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xsparkx2flash', displayName: 'Spark-X2-Flash', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'auto', displayName: 'Auto', contextWindow: 200000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopglm5', displayName: 'GLM-5', contextWindow: 200000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopglm51', displayName: 'GLM-5.1', contextWindow: 200000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopglm52', displayName: 'GLM-5.2', contextWindow: 500000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopglmv47flash', displayName: 'GLM-4.7-Flash', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopkimik26', displayName: 'Kimi-K2.6', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopkimik25', displayName: 'KIMI-K2.5', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xminimaxm25', displayName: 'MiniMax-M2.5', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopdeepseekv32', displayName: 'DeepSeek-V3.2', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopdeepseekv4pro', displayName: 'DeepSeek-V4-Pro', contextWindow: 1000000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopdeepseekv4flash', displayName: 'DeepSeek-V4-Flash', contextWindow: 1000000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopdeepseekv4flash0731', displayName: 'DeepSeek-V4-Flash-0731', contextWindow: 1000000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopqwen36v35b', displayName: 'Qwen3.6-35B-A3B', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopqwen35v35b', displayName: 'Qwen3.5-35B-A3B', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xop3qwencodernext', displayName: 'Qwen3-Coder-Next-FP8', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopqwen35397b', displayName: 'Qwen3.5-397B-A17B', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
    ],
  },
  {
    id: 'opencode-zen',
    label: 'OpenCode Zen',
    name: 'OpenCode Zen',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://opencode.ai/inference/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://opencode.ai/auth',
    docsUrl: 'https://opencode.ai/docs/zen/',
    modelCatalogUrl: 'https://opencode.ai/inference/v1/models',
    modelCatalogIds: OPENCODE_ZEN_SUPPORTED_MODEL_IDS,
    defaultModelId: 'deepseek-v4.1-flash',
    models: [
      { modelId: 'deepseek-v4.1-flash', displayName: 'DeepSeek V4.1 Flash', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'deepseek-chat' } },
      { modelId: 'big-pickle', displayName: 'Big Pickle (Free)', contextWindow: 400000, maxOutputTokens: 16384, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      openCodeFreeModel('ling-3.1-flash-free', 'Ling 3.1 Flash Free'),
      openCodeFreeModel('cat-jam-free', 'Cat Jam Free'),
      openCodeFreeModel('mimo-v2.6-flash-free', 'MiMo-V2.6-Flash Free'),
      openCodeFreeModel('muse-spark-1.2-contributor-free', 'Muse Spark 1.2 Contributor Free', { capability: 'multimodal', adapter_profile_id: 'openai-responses' }),
      openCodeFreeModel('muse-spark-1.3-contributor-free', 'Muse Spark 1.3 Contributor Free', { capability: 'multimodal', adapter_profile_id: 'openai-responses' }),
      { modelId: 'nemotron-3.5-lightning-free', displayName: 'Nemotron 3.5 Lightning Free', contextWindow: 1048576, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      openCodeFreeModel('step-5-preview-free', 'Step 5 Preview Free'),
      openCodeFreeModel('longcat-2.5-preview-free', 'LongCat 2.5 Preview Free'),
      openCodeFreeModel('space-bunny-free', 'Space Bunny Free'),
    ],
  },
  {
    id: 'opencode-go',
    label: 'OpenCode Go',
    name: 'OpenCode Go',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://opencode.ai/inference/go/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://opencode.ai/auth',
    docsUrl: 'https://opencode.ai/docs/go/',
    modelCatalogUrl: 'https://opencode.ai/inference/go/v1/models',
    modelCatalogIds: OPENCODE_GO_SUPPORTED_MODEL_IDS,
    defaultModelId: 'deepseek-v4.1-flash',
    models: [
      { modelId: 'deepseek-v4.1-flash', displayName: 'DeepSeek V4.1 Flash', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'deepseek-chat' } },
      openCodeFreeModel('longcat-2.5-preview-free', 'LongCat 2.5 Preview Free'),
      openCodeFreeModel('step-5-preview-free', 'Step 5 Preview Free'),
      openCodeFreeModel('cat-jam-free', 'Cat Jam Free'),
    ],
  },
  {
    id: 'opencode-free',
    label: 'OpenCode Free',
    name: 'OpenCode Free',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://opencode.ai/inference/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://opencode.ai/auth',
    docsUrl: 'https://opencode.ai/docs/zen/',
    modelCatalogUrl: 'https://opencode.ai/inference/v1/models',
    modelCatalogIds: OPENCODE_ZEN_SUPPORTED_MODEL_IDS,
    defaultModelId: 'big-pickle',
    models: [
      { modelId: 'big-pickle', displayName: 'Big Pickle (Free)', contextWindow: 400000, maxOutputTokens: 16384, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      openCodeFreeModel('ling-3.1-flash-free', 'Ling 3.1 Flash Free'),
      openCodeFreeModel('cat-jam-free', 'Cat Jam Free'),
      openCodeFreeModel('mimo-v2.6-flash-free', 'MiMo-V2.6-Flash Free'),
      openCodeFreeModel('muse-spark-1.2-contributor-free', 'Muse Spark 1.2 Contributor Free', { capability: 'multimodal', adapter_profile_id: 'openai-responses' }),
      openCodeFreeModel('muse-spark-1.3-contributor-free', 'Muse Spark 1.3 Contributor Free', { capability: 'multimodal', adapter_profile_id: 'openai-responses' }),
      { modelId: 'nemotron-3.5-lightning-free', displayName: 'Nemotron 3.5 Lightning Free', contextWindow: 1048576, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      openCodeFreeModel('step-5-preview-free', 'Step 5 Preview Free'),
      openCodeFreeModel('longcat-2.5-preview-free', 'LongCat 2.5 Preview Free'),
      openCodeFreeModel('space-bunny-free', 'Space Bunny Free'),
    ],
  },
  {
    id: 'command-code',
    label: 'Command Code',
    name: 'Command Code',
    group: 'standard',
    apiType: 'openai',
    baseUrl: 'https://api.commandcode.ai/provider/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://commandcode.ai/settings/keys',
    docsUrl: 'https://commandcode.ai/docs/provider',
    defaultModelId: 'deepseek/deepseek-v4-flash',
    models: [
      { modelId: 'deepseek/deepseek-v4-pro', displayName: 'DeepSeek V4 Pro', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', adapter_profile_id: 'deepseek-chat' } },
      { modelId: 'deepseek/deepseek-v4-flash', displayName: 'DeepSeek V4 Flash', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'deepseek-chat' } },
      { modelId: 'deepseek/deepseek-v4.1-flash', displayName: 'DeepSeek V4.1 Flash', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'deepseek-chat' } },
      { modelId: 'Qwen/Qwen3.8-Max', displayName: 'Qwen 3.8 Max', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'qwen' } },
      { modelId: 'Qwen/Qwen3.8-Omni-Flash', displayName: 'Qwen 3.8 Omni Flash', contextWindow: 1000000, maxOutputTokens: 65536, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'qwen' } },
      { modelId: 'Qwen/Qwen3.7-Plus', displayName: 'Qwen 3.7 Plus', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal', adapter_profile_id: 'qwen' } },
      { modelId: 'zai-org/GLM-5.3', displayName: 'GLM-5.3', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', adapter_profile_id: 'glm' } },
      { modelId: 'z-ai/glm-5.3-flash', displayName: 'GLM-5.3 Flash', contextWindow: 1048576, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', adapter_profile_id: 'glm' } },
      { modelId: 'z-ai/glm-5.3-flashx', displayName: 'GLM-5.3 FlashX', contextWindow: 1000000, maxOutputTokens: 131072, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', adapter_profile_id: 'glm' } },
    ],
  },
  {
    id: 'command-code-free',
    label: 'Command Code Free',
    name: 'Command Code Free',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://api.commandcode.ai/provider/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://commandcode.ai/settings/keys',
    docsUrl: 'https://commandcode.ai/docs/provider',
    defaultModelId: 'poolside/laguna-s-2.1-free',
    models: [
      { modelId: 'poolside/laguna-s-2.1-free', displayName: 'Laguna S 2.1 (Free)', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      { modelId: 'inclusionai/ling-3.0-flash-sante:free', displayName: 'Ling 3.0 Flash Sante (Free)', contextWindow: 262144, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
    ],
  },
  {
    id: 'sambanova-free',
    label: 'SambaNova Free',
    name: 'SambaNova Cloud',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://api.sambanova.ai/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://cloud.sambanova.ai/',
    docsUrl: 'https://docs.sambanova.ai/docs/en/get-started/api-keys-urls',
    defaultModelId: 'DeepSeek-V3.1',
    models: [
      { modelId: 'DeepSeek-V3.1', displayName: 'DeepSeek-V3.1', contextWindow: 131072, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', adapter_profile_id: 'deepseek-chat' } },
      { modelId: 'Meta-Llama-3.3-70B-Instruct', displayName: 'Llama 3.3 70B Instruct', contextWindow: 131072, maxOutputTokens: 32768, thinkingSupported: false, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      { modelId: 'gpt-oss-120b', displayName: 'GPT OSS 120B', contextWindow: 131072, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
    ],
  },
  {
    id: 'groq-free',
    label: 'Groq Free',
    name: 'Groq',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://api.groq.com/openai/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://console.groq.com/keys',
    docsUrl: 'https://console.groq.com/docs/openai',
    defaultModelId: 'openai/gpt-oss-120b',
    models: [
      { modelId: 'openai/gpt-oss-120b', displayName: 'GPT OSS 120B', contextWindow: 131072, maxOutputTokens: 65536, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      { modelId: 'openai/gpt-oss-20b', displayName: 'GPT OSS 20B', contextWindow: 131072, maxOutputTokens: 65536, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
      { modelId: 'qwen/qwen3.8-27b', displayName: 'Qwen 3.8 27B', contextWindow: 131072, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', adapter_profile_id: 'qwen' } },
    ],
  },
  {
    id: 'google-gemini-free',
    label: 'Google Gemini Free',
    name: 'Google Gemini',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://aistudio.google.com/apikey',
    docsUrl: 'https://ai.google.dev/gemini-api/docs/openai',
    defaultModelId: 'gemini-3.8-flash',
    models: [
      { modelId: 'gemini-3.8-flash', displayName: 'Gemini 3.8 Flash', contextWindow: 1048576, maxOutputTokens: 65536, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal' } },
      { modelId: 'gemini-3.5-flash-lite', displayName: 'Gemini 3.5 Flash Lite', contextWindow: 1048576, maxOutputTokens: 65536, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'multimodal' } },
    ],
  },
  {
    id: 'cloudflare-workers-ai-free',
    label: 'Cloudflare Workers AI Free',
    name: 'Cloudflare Workers AI',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1',
    baseUrlEditable: true,
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://dash.cloudflare.com/profile/api-tokens',
    docsUrl: 'https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/',
    defaultModelId: '@cf/meta/llama-3.1-8b-instruct',
    models: [
      { modelId: '@cf/meta/llama-3.1-8b-instruct', displayName: 'Llama 3.1 8B Instruct', contextWindow: 131072, maxOutputTokens: 8192, thinkingSupported: false, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text' } },
    ],
  },
  {
    id: 'openrouter-free',
    label: 'OpenRouter Free',
    name: 'OpenRouter',
    group: 'free',
    apiType: 'openai',
    baseUrl: 'https://openrouter.ai/api/v1',
    adapterProfile: 'openai-chat',
    apiKeyUrl: 'https://openrouter.ai/settings/keys',
    docsUrl: 'https://openrouter.ai/docs/api-reference/overview',
    defaultModelId: 'openrouter/free',
    models: [
      { modelId: 'openrouter/free', displayName: 'Free Models Router', contextWindow: 200000, maxOutputTokens: 32768, thinkingSupported: false, thinkingBudget: 10000, temperature: 0.7, extra: { capability: 'text', dynamic_catalog: true } },
    ],
  },
]
