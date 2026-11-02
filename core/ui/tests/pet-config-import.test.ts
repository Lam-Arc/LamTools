/**
 * 配置迁移、角色包校验与路由规则的单元测试。
 *
 * 这些是纯逻辑，不依赖桌面窗口；涉及真实 Agent 链路的验证放在验收报告里，
 * 用真实会话与真实审批跑，不用 Mock 顶替。
 */
import { describe, expect, it } from 'vitest'
import {
  DEFAULT_PING_PROMPTS,
  PET_CONFIG_VERSION,
  defaultConfig,
  migrateConfig,
  parseConfigText,
} from '@/pet/config.ts'
import {
  analyzeImport,
  isRelativeSafePath,
  suggestActionId,
  type ImportScanResult,
} from '@/pet/assets/importer.ts'

function scan(files: [string, number][], root = 'C:/pets/Demo'): ImportScanResult {
  return {
    root,
    files: files.map(([rel, size]) => ({ rel, size, ext: rel.split('.').pop()?.toLowerCase() || '' })),
    totalBytes: files.reduce((total, [, size]) => total + size, 0),
  }
}

describe('配置版本与迁移', () => {
  it('空配置写出默认值并带版本号', () => {
    const { config } = migrateConfig(null)
    expect(config.version).toBe(PET_CONFIG_VERSION)
    expect(config.ping.sectors.length).toBeGreaterThanOrEqual(6)
    expect(config.ping.hotkey).toBe('Ctrl+Alt+Space')
    // user:"默认关闭啦 l3"+(L3 视觉边缘识别默认关闭。)
    expect(config.useL3).toBe(false)
  })

  it('从无版本号的旧配置迁移，并补全提示词模板', () => {
    const legacy = {
      enabled: true,
      quality: 'high',
      ping: {
        hotkey: 'Ctrl+Shift+P',
        radius: 150,
        sectors: [{ id: 'question', label: '问', icon: '?', kind: 'question', color: '#fff', enabled: true }],
      },
    }
    const result = migrateConfig(legacy)
    expect(result.migratedFrom).toBe(0)
    expect(result.config.version).toBe(PET_CONFIG_VERSION)
    expect(result.config.ping.hotkey).toBe('Ctrl+Shift+P')
    // 用户项保留，缺的提示词用默认模板补齐。
    expect(result.config.ping.sectors[0].prompt).toBe(DEFAULT_PING_PROMPTS.question)
    expect(result.config.quality).toBe('high')
  })

  it('坏配置不炸：解析失败时回落到默认值并说明', () => {
    const result = parseConfigText('{ this is not json')
    expect(result.config.version).toBe(PET_CONFIG_VERSION)
    expect(result.warnings.length).toBeGreaterThan(0)
  })

  it('桌宠的名字与提示词模板可以逐项自定义', () => {
    const { config } = migrateConfig({
      version: 1,
      ping: {
        sectors: [
          { id: 'question', label: '解释', icon: '?', kind: 'question', color: '#123456', enabled: true, prompt: '自定义问题模板' },
          { id: 'exclamation', label: '风险', icon: '!', kind: 'exclamation', color: '#654321', enabled: true, prompt: '自定义注意模板' },
        ],
      },
    })
    expect(config.ping.sectors[0].prompt).toBe('自定义问题模板')
    expect(config.ping.sectors[1].prompt).toBe('自定义注意模板')
  })
})

describe('角色包校验与动作建议', () => {
  it('拒绝绝对路径与穿越路径', () => {
    expect(isRelativeSafePath('images/idle.png')).toBe(true)
    expect(isRelativeSafePath('../secret.png')).toBe(false)
    expect(isRelativeSafePath('C:/windows/system32/x.dll')).toBe(false)
    expect(isRelativeSafePath('/etc/passwd')).toBe(false)
  })

  it('外部动画名不必遵守 Sunday 命名，仍能给出动作建议', () => {
    expect(suggestActionId('walk_cycle')?.actionId).toBe('walk')
    expect(suggestActionId('Stand')?.actionId).toBe('idle')
    expect(suggestActionId('celebrate')?.actionId).toBe('dance')
    expect(suggestActionId('完全无关的名字')).toBeNull()
  })

  it('只有一张 PNG 也能成为可用角色', () => {
    const analysis = analyzeImport(scan([['portrait.png', 2048]]))
    expect(analysis.ok).toBe(true)
    expect(analysis.actions.idle).toEqual({ type: 'static', source: 'portrait.png' })
    expect(analysis.previewSource).toBe('portrait.png')
  })

  it('序列帧按数字顺序归组并识别动作', () => {
    const analysis = analyzeImport(scan([
      ['walk_0.png', 100],
      ['walk_1.png', 100],
      ['walk_10.png', 100],
      ['walk_2.png', 100],
    ]))
    const walk = analysis.actions.walk
    expect(walk?.type).toBe('frames')
    if (walk?.type === 'frames') {
      expect(walk.sources).toEqual(['walk_0.png', 'walk_1.png', 'walk_2.png', 'walk_10.png'])
      expect(walk.loop).toBe(true)
    }
  })

  it('pet.json 描述的动作各自引用不同资源，缺失的文件给出提示', () => {
    const manifest = JSON.stringify({
      schema_version: 1,
      name: 'Mixed',
      actions: {
        idle: { source: 'idle.png', type: 'static' },
        walk: { source: 'anim/walk.png', type: 'spritesheet', frame_width: 64, frame_height: 64, frame_count: 6 },
        jump: { source: 'missing.png', type: 'static' },
      },
    })
    const analysis = analyzeImport(scan([
      ['pet.json', manifest.length],
      ['idle.png', 100],
      ['anim/walk.png', 300],
    ]), manifest)
    expect(analysis.actions.idle?.type).toBe('static')
    expect(analysis.actions.walk?.type).toBe('spritesheet')
    expect(analysis.actions.jump).toBeUndefined()
    expect(analysis.warnings.some(item => item.includes('jump'))).toBe(true)
    expect(analysis.unsupported.length).toBe(0)
  })

  it('GLB 已支持；没有运行时的格式仍然明确列出，不假装兼容', () => {
    const analysis = analyzeImport(scan([
      ['portrait.png', 100],
      ['model.glb', 5000],
      ['avatar.vrm', 4000],
      ['rig.vrma', 2000],
      ['old.fbx', 3000],
    ]))
    expect(analysis.ok).toBe(true)
    // glb 与 vrm 现在是可播放资源，不该出现在"不支持"里。
    expect(analysis.unsupported.some(item => item.includes('model.glb'))).toBe(false)
    expect(analysis.unsupported.some(item => item.includes('avatar.vrm'))).toBe(false)
    expect(analysis.unsupported.some(item => item.includes('vrma'))).toBe(true)
    expect(analysis.unsupported.some(item => item.includes('fbx'))).toBe(true)
    // 静态图仍然可用：单一资源失败不拖垮整包。
    expect(analysis.actions.idle).toBeDefined()
  })

  it('pet.json 可以给不同动作分别指定静态图与 GLB 模型', () => {
    const manifest = JSON.stringify({
      schema_version: 1,
      name: 'Hybrid',
      actions: {
        idle: { source: 'idle.png', type: 'static' },
        dance: { source: 'dance.glb', type: 'model', model_clip: 'Dance', loop: true },
      },
    })
    const analysis = analyzeImport(scan([
      ['pet.json', manifest.length],
      ['idle.png', 100],
      ['dance.glb', 9000],
    ]), manifest)
    expect(analysis.actions.idle?.type).toBe('static')
    expect(analysis.actions.dance?.type).toBe('model')
    if (analysis.actions.dance?.type === 'model') {
      expect(analysis.actions.dance.source).toBe('dance.glb')
      expect(analysis.actions.dance.clip).toBe('Dance')
    }
  })

  it('只有 GLB 也能成为角色（自动识别为 idle 模型）', () => {
    const analysis = analyzeImport(scan([['avatar.glb', 120000]]))
    expect(analysis.ok).toBe(true)
    expect(analysis.actions.idle?.type).toBe('model')
    if (analysis.actions.idle?.type === 'model') {
      expect(analysis.actions.idle.source).toBe('avatar.glb')
    }
  })

  it('没有任何图片时报错，但不会抛异常', () => {
    const analysis = analyzeImport(scan([['readme.txt', 10]]))
    expect(analysis.ok).toBe(false)
    expect(analysis.errors.length).toBeGreaterThan(0)
  })
})
