import { describe, expect, it } from 'vitest'
import {
  buildCoreComposerHighlightSegments,
  buildCoreComposerInputItems,
  coreStandaloneActionCommand,
} from '../src/composer/inputItems'
import type { CoreCommandCatalogItem, CoreInputItem } from '../src/types'

const commands: CoreCommandCatalogItem[] = [
  {
    name: 'review',
    title: 'Review',
    description: '',
    icon: 'scan',
    source: 'core',
    action: 'insert_token',
    kind: 'skill',
  },
  {
    name: 'compact',
    title: 'Compact',
    description: '',
    icon: 'archive',
    source: 'core',
    action: 'run_action',
    kind: 'action',
  },
]

describe('core composer input items', () => {
  it('turns insert-token slash commands into skill input items and preserves attachments', () => {
    const attachments: CoreInputItem[] = [
      { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
    ]

    expect(buildCoreComposerInputItems('before /review after', attachments, commands)).toEqual([
      { type: 'text', text: 'before ' },
      { type: 'skill', name: 'review', source_text: '/review' },
      { type: 'text', text: ' after' },
      { type: 'attachment', attachment_id: 'att-1', filename: 'note.md' },
    ])
  })

  it('detects standalone run-action commands only when no other text is present', () => {
    expect(coreStandaloneActionCommand('/compact', commands)).toBe('compact')
    expect(coreStandaloneActionCommand('please /compact', commands)).toBe('')
    expect(coreStandaloneActionCommand('/review', commands)).toBe('')
  })

  it('marks recognized action and skill spans without changing their text', () => {
    expect(buildCoreComposerHighlightSegments('before /review after', commands)).toEqual([
      { text: 'before ', command: false },
      { text: '/review', command: true },
      { text: ' after', command: false },
    ])
    expect(buildCoreComposerHighlightSegments('/compact', commands)).toEqual([
      { text: '/compact', command: true },
    ])
  })

  it('drops recognition immediately after partial or complete deletion', () => {
    expect(buildCoreComposerHighlightSegments('/revie', commands)).toEqual([
      { text: '/revie', command: false },
    ])
    expect(buildCoreComposerHighlightSegments('/unknown', commands)).toEqual([
      { text: '/unknown', command: false },
    ])
    expect(buildCoreComposerHighlightSegments('', commands)).toEqual([
      { text: '', command: false },
    ])
  })
})
