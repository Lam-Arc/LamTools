import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = process.cwd()
const css = readFileSync(resolve(root, 'src/styles/message-stream.css'), 'utf8')
const defaults = readFileSync(resolve(root, 'src/helpers/messageStreamStyle.ts'), 'utf8')

/**
 * user:“所有过程行展开后均需配备专属容器，严禁直接裸露纯文本”+“思考过程 推荐默认容器形态 卡片式”
 * +(这两条以前只写了变量没人消费：正文元素真实类名是 reasoning-body / tool-card-body，
 * 选择器写成 .process-card-body 一条都匹配不上，设置怎么改都不生效。)
 */
describe('message stream consumers', () => {
  it('targets the real process body class names', () => {
    expect(css).toContain('.thread .reasoning-body')
    expect(css).toContain('.thread .tool-card-body')
    // 不存在的类名不该再被当成正文容器选择器
    expect(css).not.toMatch(/:root\[data-ms-proc-body-container="card"\] \.thread \.process-card-body\b/)
  })

  it('ships a card default for the process body', () => {
    expect(defaults).toMatch(/procBodyContainer: 'card'/)
  })

  it('keeps the message body default as plain text', () => {
    expect(defaults).toMatch(/bodyContainer: 'none'/)
  })

  it('neutralizes inner frames so the outer container stays visible', () => {
    expect(css).toContain('> .command-output')
    expect(css).toContain('> .diff-block')
  })
})
