import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

// user:“dev 界面一直卡在加载中”+(真实事故：LamToolsApp.vue 的 firstRunState 计算属性在 setup 期就会求值，
// 它引用了后面才 `const coreSessions = computed(...)` 声明的变量，触发 TDZ
// 「Cannot access 'coreSessions' before initialization」→ setup 抛错 → 应用从未挂载 →
// completeStartupSplash() 永不执行 → 启动画面永远转圈)。
//
// 这条测试盯住「声明必须早于 setup 期求值的使用」这一类回归：拿 SFC 源码做静态顺序断言，
// 不依赖运行 GUI，几毫秒内能给结论。
// vitest 以 core/ui 为工作目录运行，直接按仓库内相对路径定位 SFC 源码。
const APP_PATH = resolve(process.cwd(), 'src/app/LamToolsApp.vue')

interface Declaration {
  name: string
  /** setup 期（或模板之外）第一次被读取的位置 */
  firstUse: number
  declaration: number
}

function scriptBlock(source: string): string {
  const start = source.indexOf('<script setup')
  expect(start, 'LamToolsApp.vue 应当有 <script setup>').toBeGreaterThanOrEqual(0)
  const end = source.indexOf('</script>', start)
  expect(end, '<script setup> 应当正常闭合').toBeGreaterThan(start)
  return source.slice(start, end)
}

/** 把注释替换成等长空格：注释里提到变量名不算「使用」，同时保持字符位置不变以便比较顺序。 */
function maskComments(source: string): string {
  const out = source.split('')
  let i = 0
  while (i < source.length) {
    if (source[i] === '/' && source[i + 1] === '/') {
      while (i < source.length && source[i] !== '\n') {
        out[i] = ' '
        i += 1
      }
      continue
    }
    if (source[i] === '/' && source[i + 1] === '*') {
      out[i] = ' '
      out[i + 1] = ' '
      i += 2
      while (i < source.length && !(source[i] === '*' && source[i + 1] === '/')) {
        if (source[i] !== '\n') out[i] = ' '
        i += 1
      }
      if (i < source.length) {
        out[i] = ' '
        out[i + 1] = ' '
        i += 2
      }
      continue
    }
    i += 1
  }
  return out.join('')
}

/** 找出 `const <name> = computed(` 的声明位置与它在脚本里的首次使用位置。 */
function locate(script: string, name: string): Declaration {
  const declarationMatch = new RegExp(`const\\s+${name}\\s*=\\s*computed\\(`).exec(script)
  expect(declarationMatch, `应当存在 const ${name} = computed(...) 声明`).toBeTruthy()
  const declaration = declarationMatch!.index
  const declarationEnd = script.indexOf('\n', declaration)

  // 首次使用：声明之后出现的 `name.value` / `name(` 之外，任何更早的 name 引用都算「使用」。
  const usages: number[] = []
  const usagePattern = new RegExp(`\\b${name}\\b(?!\\s*=\\s*computed)`, 'g')
  let match: RegExpExecArray | null
  while ((match = usagePattern.exec(script))) {
    usages.push(match.index)
  }
  const beforeOrAtDeclaration = usages.filter(index => index < declaration)
  expect(beforeOrAtDeclaration, `${name} 在声明之前就被引用了`).toEqual([])

  return { name, firstUse: usages.find(index => index > declarationEnd) ?? Number.POSITIVE_INFINITY, declaration }
}

describe('startup setup-scope ordering', () => {
  it('declares coreSessions before anything in setup reads it', () => {
    // 事故原样：firstRunState 在 1646 行读 coreSessions，而声明在 2064 行。
    const script = maskComments(scriptBlock(readFileSync(APP_PATH, 'utf8')))
    const located = locate(script, 'coreSessions')
    const beforeDeclaration = script
      .slice(0, located.declaration)
      .split('\n')
      .findIndex(line => /\bcoreSessions\b/.test(line))
    expect(beforeDeclaration, 'coreSessions 不得在声明之前出现（TDZ 会让 setup 直接抛错）').toBe(-1)
  })

  it('keeps the guard honest: a deliberately wrong order is rejected', () => {
    // 自证断言本身有效：把使用写在声明前，locate() 必须报错。
    const broken = [
      'const firstRunState = computed(() => ({ hasSession: coreSessions.value.length > 0 }))',
      'const coreSessions = computed(() => sessions.value)',
    ].join('\n')
    expect(() => locate(broken, 'coreSessions')).toThrow()
  })
})

// user:“启动期异常容错不足”+(任何启动异常都要给出可读原因，而不是无限转圈)。
describe('startup failure surface', () => {
  it('explains what failed and where to look', async () => {
    const { formatStartupFailure } = await import('../src/motion/startupSplash')
    const text = formatStartupFailure(new Error('backend not yet started'))
    expect(text).toContain('启动失败')
    expect(text).toContain('backend not yet started')
    expect(text).toContain('frontend-console.log')
  })

  it('never renders an empty reason', async () => {
    const { formatStartupFailure } = await import('../src/motion/startupSplash')
    for (const value of [undefined, null, '', new Error('')]) {
      expect(formatStartupFailure(value)).toContain('未知错误')
    }
  })
})
