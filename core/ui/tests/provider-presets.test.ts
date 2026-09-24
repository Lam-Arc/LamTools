import { describe, expect, it } from 'vitest'

import { PROVIDER_PRESETS, providerPresetModelExtra } from '../src/data/provider-presets'

describe('DeepSeek provider preset', () => {
  it('matches the official direct API model contract', () => {
    const preset = PROVIDER_PRESETS.find(candidate => candidate.id === 'deepseek')

    expect(preset).toBeDefined()
    expect(preset).toMatchObject({
      baseUrl: 'https://api.deepseek.com',
      adapterProfile: 'deepseek-chat',
      defaultModelId: 'deepseek-flash',
    })

    expect(preset?.models).toEqual([
      expect.objectContaining({
        modelId: 'deepseek-flash',
        displayName: 'DeepSeek-V4.1-Flash',
        contextWindow: 1_000_000,
        maxOutputTokens: 393_216,
        thinkingSupported: true,
        extra: { capability: 'multimodal' },
      }),
      expect.objectContaining({
        modelId: 'deepseek-v4-pro',
        displayName: 'DeepSeek-V4-Pro-0813',
        contextWindow: 1_000_000,
        maxOutputTokens: 393_216,
        thinkingSupported: true,
        extra: { capability: 'text' },
      }),
    ])

    expect(preset?.models.map(model => model.modelId)).not.toEqual(
      expect.arrayContaining(['deepseek-chat', 'deepseek-v4-flash']),
    )
  })
})

describe('free provider presets', () => {
  it('keeps upstream reasoning adapters explicit on mixed Command Code models', () => {
    const preset = PROVIDER_PRESETS.find(candidate => candidate.id === 'command-code')
    const profileByModel = Object.fromEntries(
      (preset?.models ?? []).map(model => [model.modelId, model.extra?.adapter_profile_id]),
    )

    expect(profileByModel['deepseek/deepseek-v4-flash']).toBe('deepseek-chat')
    expect(profileByModel['deepseek/deepseek-v4.1-flash']).toBe('deepseek-chat')
    expect(profileByModel['Qwen/Qwen3.8-Max']).toBe('qwen')
    expect(profileByModel['zai-org/GLM-5.3']).toBe('glm')

    const capabilityByModel = Object.fromEntries(
      (preset?.models ?? []).map(model => [model.modelId, model.extra?.capability]),
    )
    expect(capabilityByModel['deepseek/deepseek-v4-pro']).toBe('text')
    expect(capabilityByModel['deepseek/deepseek-v4.1-flash']).toBe('multimodal')
    expect(capabilityByModel['Qwen/Qwen3.8-Max']).toBe('multimodal')
    expect(capabilityByModel['Qwen/Qwen3.8-Omni-Flash']).toBe('multimodal')
    expect(capabilityByModel['Qwen/Qwen3.7-Plus']).toBe('multimodal')
    expect(capabilityByModel['zai-org/GLM-5.3']).toBe('text')
  })

  it('infers upstream adapters for mixed gateway presets without model overrides', () => {
    expect(providerPresetModelExtra({
      modelId: 'qwen3.8-max', displayName: 'Qwen', contextWindow: 1, maxOutputTokens: 1,
      thinkingSupported: true, thinkingBudget: 1, temperature: 0.7,
    }).adapter_profile_id).toBe('qwen')
    expect(providerPresetModelExtra({
      modelId: 'glm-5.2', displayName: 'GLM', contextWindow: 1, maxOutputTokens: 1,
      thinkingSupported: true, thinkingBudget: 1, temperature: 0.7,
    }).adapter_profile_id).toBe('glm')
  })

  it('keeps the curated free providers OpenAI Chat compatible and key-driven', () => {
    const expected = [
      ['command-code-free', 'https://api.commandcode.ai/provider/v1', 'poolside/laguna-s-2.1-free'],
      ['opencode-free', 'https://opencode.ai/zen/v1', 'deepseek-v4-flash-free'],
      ['sambanova-free', 'https://api.sambanova.ai/v1', 'DeepSeek-V3.1'],
      ['groq-free', 'https://api.groq.com/openai/v1', 'openai/gpt-oss-120b'],
      ['google-gemini-free', 'https://generativelanguage.googleapis.com/v1beta/openai/', 'gemini-3.8-flash'],
      ['cloudflare-workers-ai-free', 'https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1', '@cf/meta/llama-3.1-8b-instruct'],
      ['openrouter-free', 'https://openrouter.ai/api/v1', 'openrouter/free'],
    ] as const

    for (const [id, baseUrl, defaultModelId] of expected) {
      const preset = PROVIDER_PRESETS.find(candidate => candidate.id === id)
      expect(preset, id).toBeDefined()
      expect(preset).toMatchObject({ group: 'free', apiType: 'openai', baseUrl, defaultModelId })
      expect(preset?.apiKeyUrl).toMatch(/^https:\/\//)
      expect(preset?.docsUrl).toMatch(/^https:\/\//)
      expect(preset?.defaultApiKey).toBeUndefined()
      expect(preset?.models.length).toBeGreaterThan(0)
    }
  })

  it('uses the verified Laguna S 2.1 maximum output limit', () => {
    const preset = PROVIDER_PRESETS.find(candidate => candidate.id === 'command-code-free')
    const model = preset?.models.find(candidate => candidate.modelId === 'poolside/laguna-s-2.1-free')

    expect(model?.contextWindow).toBe(256000)
    expect(model?.maxOutputTokens).toBe(32768)
  })

  it('does not keep retired OpenCode free model ids or non-chat endpoints', () => {
    const preset = PROVIDER_PRESETS.find(candidate => candidate.id === 'opencode-free')

    expect(preset?.models.map(model => model.modelId)).not.toEqual(
      expect.arrayContaining(['ling-3.0-flash-free', 'ling-3.0-tiny-free', 'north-mini-code-free', 'longcat-2.0-free']),
    )
    expect(preset?.models.map(model => model.modelId)).not.toEqual(
      expect.arrayContaining(['jev-1.13-free', 'muse-spark-1.3-contributor-free', 'muse-spark-1.2-contributor-free']),
    )
  })

  it('exposes the Free group metadata for onboarding and model catalog consumers', () => {
    const free = PROVIDER_PRESETS.filter(preset => preset.group === 'free')
    expect(free.map(preset => preset.id)).toEqual(expect.arrayContaining([
      'command-code-free',
      'opencode-free',
      'sambanova-free',
      'groq-free',
      'google-gemini-free',
      'cloudflare-workers-ai-free',
      'openrouter-free',
    ]))
  })
})
