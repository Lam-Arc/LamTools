import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { Wrench } from 'lucide-vue-next'

import {
  processIconComponent,
  processIconStroke,
  resolveProcessIconKind,
  type ProcessIconKind,
} from '@/helpers/processIcons.ts'
import ProcessIcon, { ProcessChevron } from '@/components/process/ProcessIcon.vue'

/**
 * user:“废弃通用的扳手（Wrench）图标，所有内置及系统级能力必须映射至语义明确的专属图标”
 * +(过程行的图标必须说清这一步在干什么：认得出就给专属图标，认不出走 generic，
 * 任何输入都不许再落到扳手上。)
 */

const ALL_KINDS: ProcessIconKind[] = [
  'reasoning', 'planning', 'file-read', 'file-write', 'memory',
  'code', 'search', 'web', 'image', 'question', 'subagent',
  'computer', 'mcp', 'generic',
]

function kindOf(toolName: string, extra: Record<string, unknown> = {}): ProcessIconKind {
  return resolveProcessIconKind({ toolName, ...extra })
}

describe('resolveProcessIconKind · 工具名映射', () => {
  it('maps shell and command tools to code', () => {
    for (const name of ['run_command', 'shell', 'exec', 'bash', 'powershell', 'npm_install', 'python']) {
      expect(kindOf(name), name).toBe('code')
    }
  })

  it('maps write tools to file-write', () => {
    for (const name of ['write_file', 'edit_file', 'apply_patch', 'create_file']) {
      expect(kindOf(name), name).toBe('file-write')
    }
  })

  it('maps read tools to file-read', () => {
    for (const name of ['read_file', 'cat', 'open_file']) {
      expect(kindOf(name), name).toBe('file-read')
    }
  })

  it('maps directory listing to file-read', () => {
    for (const name of ['list_dir', 'ls', 'dir']) {
      expect(kindOf(name), name).toBe('file-read')
    }
  })

  it('maps local search tools to search', () => {
    for (const name of ['grep', 'rg', 'search_files', 'find', 'glob']) {
      expect(kindOf(name), name).toBe('search')
    }
  })

  it('maps fetch and browser tools to web', () => {
    for (const name of ['web_fetch', 'browser_open', 'http_request', 'open_url']) {
      expect(kindOf(name), name).toBe('web')
    }
  })

  it('maps git tools to code without being eaten by the file rules', () => {
    for (const name of ['git_status', 'git_diff', 'commit', 'branch']) {
      expect(kindOf(name), name).toBe('code')
    }
  })

  it('maps question tools to question', () => {
    for (const name of ['question', 'ask_user', 'decision']) {
      expect(kindOf(name), name).toBe('question')
    }
  })

  it('maps memory and knowledge tools to memory', () => {
    for (const name of ['memory', 'search_context', 'recall_context', 'load_skill', 'library']) {
      expect(kindOf(name), name).toBe('memory')
    }
  })

  it('maps image generation tools to image', () => {
    for (const name of ['generate_image', 'image_edit', 'upscale_image']) {
      expect(kindOf(name), name).toBe('image')
    }
  })

  it('maps checklist tools to planning', () => {
    for (const name of ['write_checklist', 'update_checklist']) {
      expect(kindOf(name), name).toBe('planning')
    }
  })

  it('maps every sub-agent lifecycle event to subagent', () => {
    for (const name of ['sub_agent', 'subagent', 'sub_agent_message', 'sub_agent_receive']) {
      expect(kindOf(name), name).toBe('subagent')
    }
    for (const action of ['create', 'created', 'enabled', 'close', 'closed', 'message_sent', 'message_received']) {
      expect(kindOf('sub_agent', { args: { action } }), action).toBe('subagent')
    }
  })

  it('keeps web_search as an online search rather than a plain web fetch', () => {
    const kind = kindOf('web_search')
    expect(kind).toBe('search')
    expect(processIconComponent(kind, { toolName: 'web_search' })).not.toBe(
      processIconComponent('web', { toolName: 'web_fetch' }),
    )
  })

  it('maps desktop and phone control tools to computer', () => {
    const names = [
      'computer_use', 'android_use', 'desktop_overlay', 'screenshot', 'screen_capture',
      'ping', 'overlay', 'mouse', 'keyboard', 'window', 'click', 'type_text', 'scroll',
    ]
    for (const name of names) {
      expect(kindOf(name), name).toBe('computer')
    }
  })

  it('maps mcp tools to mcp by the mcp__ prefix', () => {
    for (const name of ['mcp', 'mcp__filesystem__read_file', 'mcp__chrome__click', 'mcp__bilibili__search']) {
      expect(kindOf(name), name).toBe('mcp')
    }
  })

  it('does not let mapping or copying be mistaken for ping', () => {
    expect(kindOf('mapping')).not.toBe('computer')
    expect(kindOf('copying')).not.toBe('computer')
  })
})

describe('resolveProcessIconKind · partType 优先', () => {
  it('reads the part type before the tool name', () => {
    expect(resolveProcessIconKind({ partType: 'reasoning', toolName: 'read_file' })).toBe('reasoning')
    expect(resolveProcessIconKind({ partType: 'compaction' })).toBe('memory')
    expect(resolveProcessIconKind({ partType: 'plan' })).toBe('planning')
    expect(resolveProcessIconKind({ partType: 'todo_update' })).toBe('planning')
    expect(resolveProcessIconKind({ partType: 'decision' })).toBe('question')
    expect(resolveProcessIconKind({ partType: 'questionGroup' })).toBe('question')
    expect(resolveProcessIconKind({ partType: 'file_diff' })).toBe('file-write')
    expect(resolveProcessIconKind({ partType: 'command_output' })).toBe('code')
    expect(resolveProcessIconKind({ partType: 'sub_line' })).toBe('subagent')
  })
})

describe('processIconComponent · 文件后缀细分', () => {
  const read = (path: string) => processIconComponent('file-read', { toolName: 'read_file', args: { path } })

  it('splits spreadsheets to the table icon', () => {
    for (const path of ['data.csv', 'a.xlsx', 'b.parquet', 'c.tsv']) {
      expect(read(path), path).toBe(processIconComponent('file-read', { toolName: 'read_file', args: { path: 'x.csv' } }))
    }
  })

  it('gives tables, code, images and plain files different glyphs', () => {
    const table = read('data.csv')
    const code = read('main.ts')
    const image = read('shot.png')
    const text = read('notes.md')
    const plain = read('blob.xyz')
    expect(new Set([table, code, image, text, plain]).size).toBe(5)
  })

  it('splits code files to the code icon', () => {
    const code = read('main.ts')
    for (const path of ['a.py', 'b.rs', 'c.go', 'd.js', 'e.vue', 'f.json']) {
      expect(read(path), path).toBe(code)
    }
  })

  it('splits images to the image icon', () => {
    const image = read('shot.png')
    for (const path of ['a.jpg', 'b.jpeg', 'c.webp', 'd.gif', 'e.svg']) {
      expect(read(path), path).toBe(image)
    }
  })

  it('reads the file name from the label when args are empty', () => {
    expect(resolveProcessIconKind({ label: 'read_file notes.csv' })).toBe('file-read')
    expect(processIconComponent('file-read', { label: 'read_file notes.csv' }))
      .toBe(processIconComponent('file-read', { args: { path: 'notes.csv' } }))
  })

  it('keeps write tools on the output icon for documents', () => {
    const out = processIconComponent('file-write', { toolName: 'write_file', args: { path: 'report.md' } })
    expect(out).toBe(processIconComponent('file-write', { toolName: 'write_file' }))
    expect(out).not.toBe(read('report.md'))
  })
})

describe('processIconComponent · 去扳手化', () => {
  it('never falls back to Wrench for unknown input', () => {
    expect(resolveProcessIconKind({ toolName: 'totally_unknown_tool' })).toBe('generic')
    expect(resolveProcessIconKind({})).toBe('generic')
    expect(processIconComponent('generic')).not.toBe(Wrench)
  })

  it('never returns Wrench for any kind, with or without extra input', () => {
    for (const kind of ALL_KINDS) {
      expect(processIconComponent(kind), kind).not.toBe(Wrench)
      expect(processIconComponent(kind, { toolName: 'mystery', args: { path: 'a.bin' } }), kind).not.toBe(Wrench)
    }
  })

  it('never returns Wrench across the whole legacy tool-name surface', () => {
    const legacy = [
      'run_command', 'shell', 'exec', 'bash', 'powershell', 'npm', 'python',
      'write_file', 'edit_file', 'patch', 'apply_patch', 'create_file',
      'read_file', 'cat', 'open', 'list_dir', 'ls', 'dir',
      'grep', 'rg', 'search', 'find', 'glob',
      'web_fetch', 'browser', 'http', 'web', 'web_search',
      'git_status', 'commit', 'branch',
      'question', 'ask', 'decision',
      'sub_agent', 'subagent', 'sub_agent_message', 'sub_agent_receive',
      'unknown_thing', '', '???',
    ]
    for (const toolName of legacy) {
      const kind = resolveProcessIconKind({ toolName })
      expect(processIconComponent(kind, { toolName }), toolName).not.toBe(Wrench)
    }
  })
})

describe('processIconStroke', () => {
  it('stays between 1.5 and 1.75 for every kind', () => {
    for (const kind of ALL_KINDS) {
      const stroke = processIconStroke(kind)
      expect(stroke, kind).toBeGreaterThanOrEqual(1.5)
      expect(stroke, kind).toBeLessThanOrEqual(1.75)
    }
  })
})

describe('ProcessIcon.vue · 状态叠加', () => {
  const base = { toolName: 'read_file', args: { path: 'notes.md' } }

  it('renders a 16px glyph with a 1.6 stroke by default', () => {
    const wrapper = mount(ProcessIcon, { props: { ...base } })
    const svg = wrapper.find('svg')
    expect(svg.attributes('width')).toBe('16')
    expect(svg.attributes('height')).toBe('16')
    expect(svg.attributes('stroke-width')).toBe('1.6')
    expect(wrapper.attributes('data-process-icon-kind')).toBe('file-read')
  })

  // user:“把圈去掉”+(运行态不再画旋转细环：状态只靠图标本身与行内流光表达。)
  it('stays static while running because the ring was removed', () => {
    const wrapper = mount(ProcessIcon, { props: { ...base, status: 'running' } })
    expect(wrapper.classes()).toContain('process-icon--running')
    expect(wrapper.find('.process-icon__ring').exists()).toBe(false)
    expect(wrapper.find('.process-icon__badge').exists()).toBe(false)
  })

  it('goes static and dim when completed', () => {
    const wrapper = mount(ProcessIcon, { props: { ...base, status: 'completed' } })
    expect(wrapper.classes()).toContain('process-icon--completed')
    expect(wrapper.find('.process-icon__ring').exists()).toBe(false)
    expect(wrapper.find('.process-icon__badge').exists()).toBe(false)
  })

  it('marks failure with a warning badge for both failed and error', () => {
    for (const status of ['failed', 'error'] as const) {
      const wrapper = mount(ProcessIcon, { props: { ...base, status } })
      expect(wrapper.classes()).toContain(`process-icon--${status}`)
      expect(wrapper.find('.process-icon__badge').exists(), status).toBe(true)
      expect(wrapper.find('.process-icon__ring').exists(), status).toBe(false)
    }
  })

  it('honours an explicit kind and a custom stroke width', () => {
    const wrapper = mount(ProcessIcon, { props: { kind: 'reasoning', strokeWidth: 1.75 } })
    expect(wrapper.attributes('data-process-icon-kind')).toBe('reasoning')
    expect(wrapper.find('svg').attributes('stroke-width')).toBe('1.75')
  })
})

describe('processIconComponent · 系统级能力不再落 generic', () => {
  it('gives computer_use its own glyph instead of a file glyph', () => {
    const kind = kindOf('computer_use')
    expect(kind).toBe('computer')
    const icon = processIconComponent(kind, { toolName: 'computer_use' })
    // computer_use 里有 "use"，但绝不能因此被读文件规则抢走。
    expect(icon).not.toBe(processIconComponent('file-read', { toolName: 'read_file' }))
    expect(icon).not.toBe(processIconComponent('generic'))
  })

  it('keeps computer and mcp out of the generic bucket', () => {
    for (const toolName of ['computer_use', 'android_use', 'desktop_overlay', 'screenshot', 'click', 'mcp__fs__read']) {
      expect(resolveProcessIconKind({ toolName }), toolName).not.toBe('generic')
    }
  })

  it('uses distinct glyphs for computer, mcp and generic', () => {
    const computer = processIconComponent('computer')
    const mcp = processIconComponent('mcp')
    const generic = processIconComponent('generic')
    expect(new Set([computer, mcp, generic]).size).toBe(3)
  })
})

describe('ProcessChevron · 折叠态箭头', () => {
  it('rotates only while expanded', () => {
    const collapsed = mount(ProcessChevron, { props: { expanded: false } })
    expect(collapsed.classes()).toContain('process-chevron')
    expect(collapsed.classes()).not.toContain('is-expanded')

    const expanded = mount(ProcessChevron, { props: { expanded: true } })
    expect(expanded.classes()).toContain('process-chevron')
    expect(expanded.classes()).toContain('is-expanded')
  })

  it('follows the expanded prop reactively', async () => {
    const wrapper = mount(ProcessChevron, { props: { expanded: false } })
    expect(wrapper.classes()).not.toContain('is-expanded')
    await wrapper.setProps({ expanded: true })
    expect(wrapper.classes()).toContain('is-expanded')
    await wrapper.setProps({ expanded: false })
    expect(wrapper.classes()).not.toContain('is-expanded')
  })

  it('defaults to 16px and accepts a custom size', () => {
    const wrapper = mount(ProcessChevron)
    expect(wrapper.attributes('width')).toBe('16')
    expect(wrapper.attributes('height')).toBe('16')
    expect(wrapper.attributes('aria-hidden')).toBe('true')

    const small = mount(ProcessChevron, { props: { size: 12 } })
    expect(small.attributes('width')).toBe('12')
  })
})
