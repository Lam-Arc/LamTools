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
  apiType: string
  baseUrl: string
  adapterProfile: string
  extra?: Record<string, unknown>
  defaultModelId: string
  models: ProviderPresetModel[]
}

export const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'openai',
    label: 'OpenAI',
    name: 'OpenAI',
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
    apiType: 'openai',
    baseUrl: 'https://api.deepseek.com',
    adapterProfile: 'openai-chat',
    defaultModelId: 'deepseek-chat',
    models: [
      {
        modelId: 'deepseek-chat',
        displayName: 'DeepSeek Chat',
        contextWindow: 64000,
        maxOutputTokens: 8192,
        thinkingSupported: false,
        thinkingBudget: 10000,
        temperature: 0.7,
      },
      {
        modelId: 'deepseek-v4-pro',
        displayName: 'DeepSeek V4 Pro',
        contextWindow: 500000,
        maxOutputTokens: 16384,
        thinkingSupported: false,
        thinkingBudget: 10000,
        temperature: 0.7,
      },
      {
        modelId: 'deepseek-v4-flash',
        displayName: 'DeepSeek V4 Flash',
        contextWindow: 500000,
        maxOutputTokens: 16384,
        thinkingSupported: false,
        thinkingBudget: 10000,
        temperature: 0.7,
      },
    ],
  },
  {
    id: 'zhipu',
    label: '智谱 GLM',
    name: '智谱 GLM',
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
      { modelId: 'xopqwen36v35b', displayName: 'Qwen3.6-35B-A3B', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopqwen35v35b', displayName: 'Qwen3.5-35B-A3B', contextWindow: 128000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xop3qwencodernext', displayName: 'Qwen3-Coder-Next-FP8', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
      { modelId: 'xopqwen35397b', displayName: 'Qwen3.5-397B-A17B', contextWindow: 256000, maxOutputTokens: 32768, thinkingSupported: true, thinkingBudget: 10000, temperature: 0.7 },
    ],
  },
]
