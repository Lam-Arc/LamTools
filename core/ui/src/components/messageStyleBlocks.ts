import type { Renderer, TokenizerAndRendererExtension } from 'marked'
import { t } from '@/i18n'

const labels: Record<string, string> = { note: '说明', info: '信息', tip: '提示', warning: '注意', danger: '警告', success: '完成', details: '详情', writing: '成稿' }
const opening = /^ {0,3}:::(note|info|tip|warning|danger|success|details|writing)(?=\s|\{|$)([^\n]*)\r?\n/
export function escapeBlockText(value: string): string {
  return value.replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]!)
}

// user:“辅助说明块呢？总的来说就是样式块”+(统一语义块协议，分隔符不匹配代码围栏中的示例)。
export function messageStyleExtension(renderBody: (source: string) => string, editable: boolean, restoreSource: (source: string) => string): TokenizerAndRendererExtension {
  return {
    name: 'sundayStyleBlock', level: 'block',
    start(source) { const index = source.search(/^ {0,3}:::(?:note|info|tip|warning|danger|success|details|writing)(?=\s|\{|$)/m); return index < 0 ? undefined : index },
    tokenizer(source) {
      const match = opening.exec(source)
      if (!match) return
      let offset = match[0].length, depth = 1, fence = ''
      for (const line of source.slice(offset).match(/[^\n]*(?:\n|$)/g) || []) {
        const marker = /^ {0,3}(`{3,}|~{3,})/.exec(line)?.[1]
        if (marker && !fence) fence = marker
        else if (fence && new RegExp(`^ {0,3}${fence[0]}{${fence.length},}\\s*$`).test(line.trimEnd())) fence = ''
        else if (!fence) {
          if (opening.test(line)) depth += 1
          else if (/^ {0,3}:::\s*$/.test(line)) {
            depth -= 1
            if (!depth) return { type: 'sundayStyleBlock', raw: source.slice(0, offset + line.length), kind: match[1], heading: match[2].trim(), body: source.slice(match[0].length, offset).trimEnd() }
          }
        }
        offset += line.length
      }
    },
    renderer(token) {
      const kind = String(token.kind), body = kind === 'writing' ? restoreSource(String(token.body)) : String(token.body), heading = String(token.heading)
      if (kind === 'writing') {
        const attrs: Record<string, string> = {}
        for (const match of heading.matchAll(/([a-z]+)="([^"\n]*)"/g)) attrs[match[1]] = match[2]
        const variant = ['email', 'document', 'chat_message', 'social_post', 'standard'].includes(attrs.variant) ? attrs.variant : 'standard'
        const title = restoreSource(attrs.subject || attrs.title || t(labels.writing))
        const header = `<strong>${escapeBlockText(title)}</strong>`
        if (!editable) return `<section class="message-style-block" data-style-block="writing">${header}${renderBody(body)}</section>`
        return `<section data-writing-block data-writing-title="${escapeBlockText(title)}" data-writing-variant="${variant}"><span class="writing-source" hidden data-no-linkify>${escapeBlockText(body)}</span></section>`
      }
      const title = escapeBlockText(heading || t(labels[kind]))
      if (kind === 'details') return `<details class="message-style-block" data-style-block="details"><summary>${title}</summary>${renderBody(body)}</details>`
      return `<aside class="message-style-block" data-style-block="${kind}"><strong class="message-style-title">${title}</strong>${renderBody(body)}</aside>`
    },
  }
}

export function addAlertRenderer(renderer: Renderer, renderBody: (source: string) => string) {
  renderer.blockquote = function (token) {
    const match = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*(?:\r?\n|$)/.exec(token.text)
    if (!match) return `<blockquote>${this.parser.parse(token.tokens)}</blockquote>`
    const kind = ({ NOTE: 'note', TIP: 'tip', IMPORTANT: 'info', WARNING: 'warning', CAUTION: 'danger' } as Record<string, string>)[match[1]]
    return `<aside class="message-style-block" data-style-block="${kind}"><strong class="message-style-title">${escapeBlockText(t(labels[kind]))}</strong>${renderBody(token.text.slice(match[0].length))}</aside>`
  }
}
