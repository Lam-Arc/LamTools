import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import CorePluginsEditor from '../src/components/CorePluginsEditor.vue'

// lamtools-rag 的 configSchema（x-control 协议，见 plugins/lamtools-rag/config/schema.jsonc）
const RAG_SCHEMA = {
  type: 'object',
  properties: {
    autoRoots: {
      type: 'array',
      items: { type: 'string' },
      'x-control': {
        kind: 'path-list',
        browse: { type: 'directory', mode: 'multi' },
        scan: { label: '扫描工作区 docs', dirs: ['docs', '.lam/docs'], case_insensitive: true },
      },
    },
    vlmModel: {
      type: 'string',
      'x-control': { kind: 'model-select', capability: 'multimodal' },
    },
  },
}

const RAG_PLUGIN = {
  name: 'lamtools-rag',
  version: '0.1.0',
  description: 'RAG',
  root: 'E:\\plugins\\lamtools-rag',
  enabled: true,
  skills: [],
  hooks: [],
  mcp: [],
  tools: [],
  skill_names: [],
  hook_summary: [],
  dependencies: [],
  deps_status: 'none',
  config_schema: 'E:\\plugins\\lamtools-rag\\config\\schema.jsonc',
}

interface RpcOverrides {
  detectDirs?: Record<string, unknown>
  models?: Record<string, unknown>
}

function makeRpc(overrides: RpcOverrides = {}) {
  return vi.fn(async (method: string) => {
    switch (method) {
      case 'plugin.list':
        return { plugins: [RAG_PLUGIN], errors: [] }
      case 'plugin.config.get':
        return {
          name: 'lamtools-rag',
          config: { autoRoots: ['docs'], vlmModel: '' },
          schema: RAG_SCHEMA,
          work_root: 'E:\\ws',
        }
      case 'plugin.config.detect-dirs':
        return overrides.detectDirs || { found: [], missing: [] }
      case 'config.models.list':
        return overrides.models || { models: [] }
      default:
        return {}
    }
  })
}

async function openConfig(wrapper: ReturnType<typeof mount>) {
  await flushPromises()
  const configBtn = wrapper.findAll('button').find((b) => b.text() === '配置')
  expect(configBtn).toBeTruthy()
  await configBtn!.trigger('click')
  await flushPromises()
}

describe('插件配置表单 x-control', () => {
  it('path-list：渲染扫描按钮（label 取自协议）与每项浏览键，扫描结果去重追加并提示缺失', async () => {
    const rpc = makeRpc({
      detectDirs: {
        found: [
          { dir: 'docs', path: 'E:\\ws\\docs', relative: 'docs' },
          { dir: '.lam/docs', path: 'E:\\ws\\.lam\\docs', relative: '.lam/docs' },
        ],
        missing: ['docs-zh'],
      },
    })
    const wrapper = mount(CorePluginsEditor, {
      props: { requestRpc: rpc },
      global: { stubs: { Teleport: true } },
    })
    await openConfig(wrapper)

    // 扫描按钮 label 取自 x-control.scan.label
    const scanBtn = wrapper.findAll('button').find((b) => b.text() === '扫描工作区 docs')
    expect(scanBtn).toBeTruthy()

    await scanBtn!.trigger('click')
    await flushPromises()

    // detect-dirs 调用参数与协议一致
    expect(rpc).toHaveBeenCalledWith('plugin.config.detect-dirs', {
      dirs: ['docs', '.lam/docs'],
      case_insensitive: true,
    })

    // 原有 docs 重复去重，.lam/docs 追加；提示列出缺失目录
    const values = wrapper
      .findAll('.path-row input.path-input')
      .map((i) => (i.element as HTMLInputElement).value)
    expect(values.filter((v) => v === 'docs')).toHaveLength(1)
    expect(values).toContain('.lam/docs')
    expect(wrapper.find('.scan-notice').text()).toContain('docs-zh')

    // 每项都有浏览键
    const browseCount = wrapper.findAll('.path-row button').filter((b) => b.text() === '浏览').length
    expect(browseCount).toBeGreaterThanOrEqual(1)
  })

  it('path-list：浏览键在非 Tauri 环境回落内置目录树对话框', async () => {
    const rpc = makeRpc()
    const wrapper = mount(CorePluginsEditor, {
      props: { requestRpc: rpc },
      global: { stubs: { Teleport: true } },
    })
    await openConfig(wrapper)

    const browseBtn = wrapper.findAll('.path-row button').find((b) => b.text() === '浏览')
    expect(browseBtn).toBeTruthy()
    await browseBtn!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.fb-dialog').exists()).toBe(true)
  })

  it('model-select：选项来自 config.models.list 且按 capability 过滤', async () => {
    const rpc = makeRpc({
      models: {
        models: [
          { id: 'm1', model_id: 'm1', display_name: 'M1', capability: 'multimodal' },
          { id: 'm2', model_id: 'm2', display_name: 'M2', capability: 'text' },
        ],
      },
    })
    const wrapper = mount(CorePluginsEditor, {
      props: { requestRpc: rpc },
      global: { stubs: { Teleport: true } },
    })
    await openConfig(wrapper)

    expect(rpc).toHaveBeenCalledWith('config.models.list')
    // 只保留 multimodal
    const options = wrapper
      .findAll('#plugin-model-vlmModel option')
      .map((o) => o.attributes('value'))
    expect(options).toEqual(['m1'])
    // 输入框带 datalist 下拉（可自由输入）
    expect(wrapper.find('input[list="plugin-model-vlmModel"]').exists()).toBe(true)
  })

  it('model-select：无多模态模型时退化为可自由输入的普通输入框', async () => {
    const rpc = makeRpc({
      models: {
        models: [{ id: 'm2', model_id: 'm2', display_name: 'M2', capability: 'text' }],
      },
    })
    const wrapper = mount(CorePluginsEditor, {
      props: { requestRpc: rpc },
      global: { stubs: { Teleport: true } },
    })
    await openConfig(wrapper)

    expect(wrapper.find('input[list="plugin-model-vlmModel"]').exists()).toBe(false)
    const input = wrapper
      .findAll('.config-form input')
      .find((i) => (i.attributes('placeholder') || '').includes('可手动输入'))
    expect(input).toBeTruthy()
  })
})
