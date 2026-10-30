import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * user:“还有大文件拆分”+
 * (ChatThread 的全局样式已拆到 styles/chat-thread-*.css，六个分片按原顺序拼接。
 *  测试要断言这些样式时读全量，等价于拆分前直接读组件源码。)
 */
const PARTS = ['shell', 'tools', 'cards', 'process', 'reasoning', 'editing'] as const

/** root 传 src 目录的绝对路径。 */
export function readChatThreadSource(root: string): string {
  const vue = readFileSync(resolve(root, 'components/ChatThread.vue'), 'utf8')
  const css = PARTS
    .map((part) => readFileSync(resolve(root, `styles/chat-thread-${part}.css`), 'utf8'))
    .join('\n')
  return `${vue}\n${css}`
}
