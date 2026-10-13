import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ChatThread from '../src/components/ChatThread.vue'
import { hydrateSnapshot, selectCoreWorkbenchMessages, type CoreAppItem } from '../src/appServer'
import {
  artifactListingReference,
  artifactPathsInText,
  reportMentionsArtifactPath,
  shouldListTurnArtifact,
  workspaceRelativeFromReportPath,
} from '../src/artifacts/model'
import { createFakeTransport } from './fake-transport'

/**
 * 消息流「本轮产出」的入选规则（用户 2026-10-12）：
 * 一个回合写过的文件不再全部列出，只有①本回合被收进资料库的文件、
 * ②本回合汇报文本里以相对或绝对路径出现过的文件才进。
 */

const WORK_ROOT = 'E:\\LamTools'

describe('turn artifact selection rules', () => {
  const none = new Set<string>()

  it('reads path-like tokens out of the report, both separators, backticks and links', () => {
    const text = '交付：`E:\\LamTools\\lamsmoke\\a.md`，另有 lamsmoke/b.md 与 [c](E:/LamTools/lamsmoke/c.md)。'
    expect(artifactPathsInText(text).sort()).toEqual([
      'E:/LamTools/lamsmoke/a.md',
      'E:/LamTools/lamsmoke/c.md',
      'lamsmoke/b.md',
    ])
    // 不是路径的话不认：没有目录、没有扩展名。
    expect(artifactPathsInText('见 README 与 v1.2 版本')).toEqual([])
  })

  it('lands report paths on a workspace-relative reference, drive case included', () => {
    expect(workspaceRelativeFromReportPath('E:\\LamTools\\lamsmoke\\a.md', WORK_ROOT)).toBe('lamsmoke/a.md')
    expect(workspaceRelativeFromReportPath('e:/LamTools/lamsmoke/a.md', WORK_ROOT)).toBe('lamsmoke/a.md')
    expect(workspaceRelativeFromReportPath('lamsmoke/a.md', WORK_ROOT)).toBe('lamsmoke/a.md')
    // 越出工作区的绝对路径不是项目产物。
    expect(workspaceRelativeFromReportPath('D:/elsewhere/a.md', WORK_ROOT)).toBe('')
  })

  it('keeps a file the report names by relative path', () => {
    const artifact = { kind: 'file_change', uri: 'reports/out.md' }
    expect(shouldListTurnArtifact(artifact, {
      reportText: '本轮完成，产物见 `reports/out.md`。',
      libraryPaths: none,
      workRoot: WORK_ROOT,
    })).toBe(true)
  })

  it('keeps a file the report names by absolute path, either separator', () => {
    const artifact = { kind: 'file_change', uri: 'reports/out.md' }
    for (const text of [
      '写到 E:\\LamTools\\reports\\out.md 了',
      '写到 E:/LamTools/reports/out.md 了',
      '写到 `E:\\LamTools\\reports/out.md` 了',
    ]) {
      expect(shouldListTurnArtifact(artifact, {
        reportText: text, libraryPaths: none, workRoot: WORK_ROOT,
      }), text).toBe(true)
    }
  })

  it('matches the artifact reference written with backslashes too', () => {
    const artifact = { kind: 'file_change', uri: 'reports\\out.md' }
    expect(shouldListTurnArtifact(artifact, {
      reportText: '产物是 reports/out.md',
      libraryPaths: none,
      workRoot: WORK_ROOT,
    })).toBe(true)
    expect(artifactListingReference(artifact)).toBe('reports/out.md')
  })

  it('drops a written file the report never names', () => {
    expect(shouldListTurnArtifact({ kind: 'file_change', uri: 'scratch/tmp.txt' }, {
      reportText: '本轮完成，产物见 `reports/out.md`。',
      libraryPaths: none,
      workRoot: WORK_ROOT,
    })).toBe(false)
  })

  it('keeps a file filed into the library even when the report does not name it', () => {
    expect(shouldListTurnArtifact({ kind: 'file_change', uri: 'reports/out.md' }, {
      reportText: '本轮完成。',
      libraryPaths: new Set(['reports/out.md']),
      workRoot: WORK_ROOT,
    })).toBe(true)
  })

  it('drops an entry without any path to check', () => {
    expect(shouldListTurnArtifact({ kind: 'file_change' }, {
      reportText: 'reports/out.md',
      libraryPaths: none,
      workRoot: WORK_ROOT,
    })).toBe(false)
  })

  it('leaves generated images alone — they are not "files written this turn"', () => {
    expect(shouldListTurnArtifact({ kind: 'image', uri: 'assets/shot.png' }, {
      reportText: '无',
      libraryPaths: none,
      workRoot: WORK_ROOT,
    })).toBe(true)
  })

  it('does not match a bare basename mentioned without its directory', () => {
    // 只写文件名不算"以路径出现"：同名文件太多，按路径才是可核对的证据。
    expect(reportMentionsArtifactPath('改好了 out.md', 'reports/out.md', WORK_ROOT)).toBe(false)
    expect(reportMentionsArtifactPath('改好了 reports/out.md', 'reports/out.md', WORK_ROOT)).toBe(true)
  })
})

// ── 页面级：真实投影 → 聊天流 → 本轮产出区的条目 ──

function snapshotWithTurn(options: {
  report: string
  writes: Array<{ id: string; uri: string; metadataPath?: string }>
  library?: Array<{ id: string; artifactId: string; path: string }>
}) {
  const items: Record<string, CoreAppItem> = {}
  const order: string[] = []
  for (const write of options.writes) {
    items[write.id] = {
      item_id: write.id,
      turn_id: 'turn-1',
      kind: 'tool_result',
      status: 'completed',
      type: 'dynamicToolCall',
      tool_name: 'write_file',
      content: `Created ${write.uri}`,
      payload: { type: 'dynamicToolCall', tool_name: 'write_file', content: `Created ${write.uri}` },
      artifacts: [{
        kind: 'file_change',
        uri: write.uri,
        metadata: { path: write.metadataPath || write.uri, action: 'create' },
      }],
    }
    order.push(write.id)
  }
  for (const filed of options.library || []) {
    items[filed.id] = {
      item_id: filed.id,
      turn_id: 'turn-1',
      kind: 'tool_result',
      status: 'completed',
      type: 'dynamicToolCall',
      tool_name: 'library',
      content: `Filed ${filed.path} into the library as ${filed.artifactId}`,
      payload: {
        type: 'dynamicToolCall',
        tool_name: 'library',
        content: `Filed ${filed.path} into the library as ${filed.artifactId}`,
        metadata: { artifact_id: filed.artifactId, path: filed.path },
      },
    }
    order.push(filed.id)
  }
  items['item-report'] = {
    item_id: 'item-report',
    turn_id: 'turn-1',
    kind: 'message',
    status: 'completed',
    type: 'agentMessage',
    content: options.report,
    payload: { type: 'agentMessage', content: options.report },
  }
  order.push('item-report')
  return hydrateSnapshot({
    thread_id: 'thread-turn',
    snapshot_seq: order.length,
    core: {
      thread_id: 'thread-turn',
      snapshot_seq: order.length,
      status: 'completed',
      item_order: order,
      turns: { 'turn-1': { turn_id: 'turn-1', status: 'completed', items: order } },
      items,
      artifacts: {},
      requests: {},
      seen_event_ids: [],
    },
  } as never)
}

function mountTurn(
  options: Parameters<typeof snapshotWithTurn>[0],
  fileResponse?: { status: number; headers?: Record<string, string>; body?: Uint8Array },
) {
  const messages = selectCoreWorkbenchMessages(snapshotWithTurn(options))
  return mount(ChatThread, {
    props: {
      transport: createFakeTransport(fileResponse
        ? {
            status: fileResponse.status,
            headers: fileResponse.headers ?? { 'content-type': 'text/markdown' },
            body: fileResponse.body ?? new TextEncoder().encode('# reported'),
          }
        : undefined),
      messages,
      workRoot: WORK_ROOT,
      projectId: 'project-1',
    },
  })
}

/** 等存在性检查那一次请求落地并重渲染。 */
async function settleFileChecks(wrapper: ReturnType<typeof mount>): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  await wrapper.vm.$nextTick()
}

function deckKeys(wrapper: ReturnType<typeof mount>): string[] {
  return wrapper.findAll('.message-artifacts [data-deck-item]')
    .map(node => String(node.attributes('data-deck-item')))
}

describe('本轮产出收录规则（页面级）', () => {
  it('lists only files the turn filed into the library or named in its report', () => {
    const wrapper = mountTurn({
      report: '本轮完成。产物：`reports/out.md`。',
      writes: [
        { id: 'w-a', uri: 'reports/out.md' },
        { id: 'w-b', uri: 'reports/filed.md' },
        { id: 'w-c', uri: 'scratch/tmp.txt' },
      ],
      library: [{ id: 'lib-b', artifactId: 'art-b', path: 'reports/filed.md' }],
    })

    expect(wrapper.find('.message-artifacts').exists()).toBe(true)
    expect(deckKeys(wrapper).sort()).toEqual(['reports/filed.md', 'reports/out.md'])
  })

  it('takes a report-named file that exists even when the turn never wrote it — absolute backslash', async () => {
    const wrapper = mountTurn({
      report: '产物已落盘：`E:\\LamTools\\lamsmoke\\reported-artifact.md`。',
      writes: [],
      library: [],
    }, { status: 200 })
    await settleFileChecks(wrapper)

    expect(deckKeys(wrapper)).toEqual(['lamsmoke/reported-artifact.md'])
  })

  it('takes the same file when the report spells it with forward slashes', async () => {
    const wrapper = mountTurn({
      report: '产物已落盘：E:/LamTools/lamsmoke/reported-artifact.md',
      writes: [],
    }, { status: 200 })
    await settleFileChecks(wrapper)

    expect(deckKeys(wrapper)).toEqual(['lamsmoke/reported-artifact.md'])
  })

  it('takes a report-named file written as a relative path', async () => {
    const wrapper = mountTurn({
      report: '本轮产物是 lamsmoke/reported-artifact.md',
      writes: [],
    }, { status: 200 })
    await settleFileChecks(wrapper)

    expect(deckKeys(wrapper)).toEqual(['lamsmoke/reported-artifact.md'])
  })

  it('shows nothing for a report-named path that does not exist', async () => {
    const wrapper = mountTurn({
      report: '顺手看了一眼 `notes/old.md`，本轮没有新产物。',
      writes: [{ id: 'w-a', uri: 'scratch/tmp.txt' }],
    }, { status: 404, body: new Uint8Array() })
    await settleFileChecks(wrapper)

    // 路径不存在就不展示，也不凭空造卡片。
    expect(deckKeys(wrapper)).toEqual([])
  })

  it('lists the same file once when the report and the artifacts use different spellings', () => {
    const wrapper = mountTurn({
      report: '产物：`E:\\LamTools\\reports\\out.md`。',
      writes: [
        { id: 'w-a', uri: 'reports/out.md' },
        { id: 'w-b', uri: 'E:\\LamTools\\reports\\out.md', metadataPath: 'reports\\out.md' },
      ],
    })

    expect(deckKeys(wrapper)).toEqual(['reports/out.md'])
  })
})
