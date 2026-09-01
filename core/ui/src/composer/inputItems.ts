import type { CoreCommandCatalogItem, CoreInputItem } from '../types'
import {
  parseComposerInput,
  parseComposerSyntax,
  resolveComposerCommandKind,
} from './syntax.ts'

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
    .filter(span => Boolean(findCommand(commands, span.value)))
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
    .filter(span => Boolean(findSkillCommand(commands, span.value)))

  if (!spans.length) return [{ type: 'text', text }, ...attachments]

  const items: CoreInputItem[] = []
  let cursor = 0
  for (const span of spans) {
    if (span.start > cursor) items.push({ type: 'text', text: text.slice(cursor, span.start) })
    const command = findSkillCommand(commands, span.value)
    if (command) items.push({ type: 'skill', name: command.name, source_text: span.raw })
    cursor = span.end
  }
  if (cursor < text.length) items.push({ type: 'text', text: text.slice(cursor) })
  return [...items, ...attachments]
}

export function coreStandaloneActionCommand(text: string, commands: CoreCommandCatalogItem[] = []): string {
  const parsed = parseComposerInput(text, commands)
  return parsed?.kind === 'action' ? parsed.name : ''
}

function findSkillCommand(
  commands: CoreCommandCatalogItem[],
  name: string,
): CoreCommandCatalogItem | undefined {
  const normalized = name.toLowerCase()
  return commands.find(command => (
    command.name.toLowerCase() === normalized && resolveComposerCommandKind(command) === 'skill'
  ))
}

function findCommand(
  commands: CoreCommandCatalogItem[],
  name: string,
): CoreCommandCatalogItem | undefined {
  const normalized = name.toLowerCase()
  return commands.find(command => command.name.toLowerCase() === normalized)
}
