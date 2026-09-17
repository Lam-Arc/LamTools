import { describe, expect, it } from 'vitest'

import { PROVIDER_PRESETS } from '../src/data/provider-presets'

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
