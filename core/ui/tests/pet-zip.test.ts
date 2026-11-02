/**
 * `.sundaypet` 导入校验：解包、去公共目录、路径安全、类型白名单、体积上限。
 *
 * 这些规则和 Rust 侧的写入校验是同一套语义，两边都测，避免"前端放过、后端拒绝"
 * 或反过来的错位。
 */
import { describe, expect, it } from 'vitest'
import { zipSync, strToU8 } from 'fflate'
import { MAX_ENTRIES, packNameFrom, readSundayPetZip } from '@/pet/assets/zip.ts'

function buildZip(files: Record<string, string | Uint8Array>): Uint8Array {
  const input: Record<string, Uint8Array> = {}
  for (const [name, content] of Object.entries(files)) {
    input[name] = typeof content === 'string' ? strToU8(content) : content
  }
  return zipSync(input)
}

describe('.sundaypet ZIP 导入', () => {
  it('剥掉公共顶层目录，保留相对路径', () => {
    const zip = buildZip({
      'MyPet/pet.json': '{"schema_version":1,"name":"ZipCat"}',
      'MyPet/portrait.png': 'png',
      'MyPet/anim/walk_0.png': 'a',
    })
    const result = readSundayPetZip(zip)
    expect(result.errors).toEqual([])
    const rels = result.entries.map(entry => entry.rel).sort()
    expect(rels).toEqual(['anim/walk_0.png', 'pet.json', 'portrait.png'])
    expect(result.map.get('pet.json')).toBeDefined()
  })

  it('没有公共目录时原样保留', () => {
    const zip = buildZip({ 'pet.json': '{}', 'idle.png': 'png' })
    const result = readSundayPetZip(zip)
    expect(result.entries.map(entry => entry.rel).sort()).toEqual(['idle.png', 'pet.json'])
  })

  it('路径穿越条目被拒绝，不会带进安装目录', () => {
    const zip = buildZip({
      'pet.json': '{}',
      '../evil.png': 'x',
      'a/../../evil2.png': 'y',
      'ok.png': 'z',
    })
    const result = readSundayPetZip(zip)
    const rels = result.entries.map(entry => entry.rel)
    expect(rels).toContain('ok.png')
    expect(rels.some(rel => rel.includes('..'))).toBe(false)
    expect(result.errors.some(error => error.includes('路径不安全'))).toBe(true)
  })

  it('脚本类文件不进角色包，只给警告', () => {
    const zip = buildZip({
      'pet.json': '{}',
      'idle.png': 'png',
      'run.js': 'alert(1)',
      'setup.py': 'print(1)',
      'tool.exe': 'MZ',
    })
    const result = readSundayPetZip(zip)
    const rels = result.entries.map(entry => entry.rel)
    expect(rels).toEqual(expect.arrayContaining(['pet.json', 'idle.png']))
    expect(rels).not.toContain('run.js')
    expect(rels).not.toContain('setup.py')
    expect(rels).not.toContain('tool.exe')
    expect(result.warnings.filter(item => item.includes('不支持的文件类型')).length).toBeGreaterThanOrEqual(3)
  })

  it('macOS 打包噪音被忽略', () => {
    const zip = buildZip({
      'pet.json': '{}',
      'idle.png': 'png',
      '__MACOSX/._idle.png': 'meta',
    })
    const result = readSundayPetZip(zip)
    expect(result.entries.map(entry => entry.rel)).not.toContain('__MACOSX/._idle.png')
    expect(result.warnings.some(item => item.includes('打包噪音'))).toBe(true)
  })

  it('不是 ZIP 时给出可读错误，而不是抛异常', () => {
    const result = readSundayPetZip(strToU8('this is not a zip'))
    expect(result.entries).toEqual([])
    expect(result.errors.length).toBeGreaterThan(0)
  })

  it('空文件与超大文件都被挡在解包之前', () => {
    expect(readSundayPetZip(new Uint8Array(0)).errors).toContain('角色包是空文件')
    const huge = new Uint8Array(81 * 1024 * 1024)
    const result = readSundayPetZip(huge)
    expect(result.errors.some(error => error.includes('超过'))).toBe(true)
  })

  it('文件数超过上限时明确报错', () => {
    const files: Record<string, string> = {}
    for (let index = 0; index < MAX_ENTRIES + 5; index += 1) files[`f${index}.png`] = 'x'
    const result = readSundayPetZip(buildZip(files))
    expect(result.errors.some(error => error.includes('超过上限'))).toBe(true)
  })

  it('角色名优先取 pet.json，其次取文件名', () => {
    expect(packNameFrom('C:/x/MyPet.sundaypet', 'ZipCat')).toBe('ZipCat')
    expect(packNameFrom('C:/x/MyPet.sundaypet')).toBe('MyPet')
    expect(packNameFrom('C:\\x\\arc-ball.zip')).toBe('arc-ball')
  })
})
