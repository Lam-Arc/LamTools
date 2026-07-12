import type { CoreCommandCatalogItem, CoreInputItem } from '../types'
import { parseComposerSyntax } from './syntax.ts'

export interface CoreComposerHighlightSegment {
  text: string
  command: boolean
}

export function buildCoreComposerHighlightSegments(
  text: string,
  commands: CoreCommandCatalogItem[] = [],
): CoreComposerHighlightSegment[] {
  const spans = parseComposerSyntax(text)
    .filter(span => span.kind === 'slash')
    .filter(span => Boolean(findCommand(commands, span.value, 'insert_token')))
  if (!spans.length) return [{ text, command: false }]

  const segments: CoreComposerHighlightSegment[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) segments.push({ text: text.slice(cursor, span.start), command: false })
    segments.push({ text: text.slice(span.start, span.end), command: true })
    cursor = span.end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), command: false })
  return segments
}

export function buildCoreComposerInputItems(
  text: string,
  attachments: CoreInputItem[] = [],
  commands: CoreCommandCatalogItem[] = [],
): CoreInputItem[] {
  const spans = parseComposerSyntax(text)
    .filter(span => span.kind === 'slash')
    .filter(span => Boolean(findCommand(commands, span.value, 'insert_token')))

  if (!spans.length) return [{ type: 'text', text }, ...attachments]

  const items: CoreInputItem[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) items.push({ type: 'text', text: text.slice(cursor, span.start) })
    const command = findCommand(commands, span.value, 'insert_token')
    if (command) items.push({ type: 'skill', name: command.name, source_text: span.raw })
    cursor = span.end
  }
  if (cursor < text.length) items.push({ type: 'text', text: text.slice(cursor) })
  return [...items, ...attachments]
}

export function coreStandaloneActionCommand(text: string, commands: CoreCommandCatalogItem[] = []): string {
  const spans = parseComposerSyntax(text)
  if (spans.length !== 1) return ''
  const span = spans[0]
  if (span.kind !== 'slash') return ''
  if (text.slice(0, span.start).trim() || text.slice(span.end).trim()) return ''
  return findCommand(commands, span.value, 'run_action')?.name ?? ''
}

function findCommand(
  commands: CoreCommandCatalogItem[],
  name: string,
  action: CoreCommandCatalogItem['action'],
): CoreCommandCatalogItem | undefined {
  const normalized = name.toLowerCase()
  return commands.find(command => command.name.toLowerCase() === normalized && command.action === action)
}
