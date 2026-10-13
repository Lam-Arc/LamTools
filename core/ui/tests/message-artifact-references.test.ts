import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import MessageView from '../src/components/MessageView.vue'
import type { CoreMessage, MessagePart, ToolArtifact } from '../src/types'
import type {
  LamToolsTransport,
  TransportConnectionState,
  TransportMessage,
  TransportRequest,
  TransportHttpResponse,
} from '../src/transport'

/**
 * 后端在发送那一刻会把超限的内联图片正文换成引用：条目带 `availability: "reference"`，
 * metadata 里的 data URL 键被丢掉，正文要按需从 path/uri 取。客户端因此：
 *  · 绝不把图片源绑到一个（已不存在的）data URL；
 *  · 先渲染占位卡（名字 +体积），进视口/展开时再取字节；
 *  · 取不到给重试，不留破图；
 *  · 去重没有 data URL 可依靠时，用注册表标识作身份。
 */
class CountingTransport implements LamToolsTransport {
  readonly requests: TransportRequest[] = []
  private readonly listeners = new Set<(message: TransportMessage) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  status = 200

  async connect(): Promise<void> { for (const listener of this.stateListeners) listener('connected') }
  async close(): Promise<void> { for (const listener of this.stateListeners) listener('disconnected') }

  async request<TResponse = unknown>(request: TransportRequest): Promise<TResponse> {
    this.requests.push(request)
    if (request.kind !== 'http') throw new Error('unexpected rpc')
    return {
      status: this.status,
      headers: { 'content-type': 'image/png' },
      body: this.status === 200 ? new Uint8Array([137, 80, 78, 71]) : new Uint8Array(),
    } as TResponse as TransportHttpResponse & TResponse
  }

  send(_message: TransportMessage): void {}
  subscribe(listener: (message: TransportMessage) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }
  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    listener('connected')
    return () => this.stateListeners.delete(listener)
  }
  getState(): TransportConnectionState { return 'connected' }
}

function referenceArtifact(
  id: string,
  path: string,
  extra: { dataUrl?: string; size?: number; name?: string } = {},
): ToolArtifact & { artifact_id?: string } {
  return {
    kind: 'image',
    artifact_id: id,
    uri: path,
    path,
    availability: 'reference',
    mime_type: 'image/png',
    ...(extra.name ? { name: extra.name } : {}),
    ...(extra.size !== undefined ? { size_bytes: extra.size } : {}),
    ...(extra.dataUrl ? { metadata: { image_data_url: extra.dataUrl, path } } : { metadata: { path } }),
  }
}

function part(id: string, artifacts: Array<ToolArtifact & { artifact_id?: string }>): MessagePart {
  return {
    id,
    partType: 'tool_call',
    status: 'completed',
    label: 'read_file',
    toolName: 'read_file',
    toolArgs: { path: 'big.png' },
    toolResult: '已读取图片。',
    artifacts,
  }
}

function msg(id: string, parts: MessagePart[]): CoreMessage {
  return { id, role: 'assistant', content: 'Done.', timestamp: '', metadata: { timeline: true }, parts }
}

function mountView(
  parts: MessagePart[],
  transport: LamToolsTransport,
  extraProps: Record<string, unknown> = {},
) {
  const message = msg('assistant:t1', parts)
  return mount(MessageView, {
    props: {
      transport,
      msg: message,
      projectId: 'proj-1',
      // 过程卡默认收起：先展开这条消息的过程组，行内图片才会渲染。
      processExpandedIds: new Set([message.id]),
      ...extraProps,
    },
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})

async function expandToolRow(wrapper: ReturnType<typeof mountView>): Promise<void> {
  // 过程卡默认收起：点开这一行才会渲染工具卡正文（图片行在里面）。
  const header = wrapper.find('.tool-card-header')
  if (header.exists()) await header.trigger('click')
  await new Promise(resolve => setTimeout(resolve, 0))
}

describe('artifact references load lazily', () => {
  it('never binds the inline data URL when the backend replaced the body with a reference', async () => {
    const transport = new CountingTransport()
    transport.status = 500
    const wrapper = mountView(
      [part('p1', [referenceArtifact('art-big', 'workspace://.lam/artifacts/big.png', {
        // 后端契约上说这个键已被丢掉；这里故意留着，证明客户端也不再用它。
        dataUrl: 'data:image/png;base64,STALE',
        size: 3_000_000,
        name: 'big.png',
      })])],
      transport,
    )
    await expandToolRow(wrapper)

    // 没有任何图片被绑到 data URL 上。
    expect(wrapper.findAll('img').filter(img => (img.attributes('src') || '').startsWith('data:'))).toHaveLength(0)
    // 占位卡立即给出名字与体积。
    const placeholder = wrapper.find('.tool-image-placeholder')
    expect(placeholder.exists()).toBe(true)
    expect(placeholder.text()).toContain('big.png')
    expect(placeholder.text()).toContain('2.9 MB')
    // 取不到时给重试，而不是破图。
    await vi.waitFor(() => expect(wrapper.find('.tool-image-placeholder__retry').exists()).toBe(true))
    wrapper.unmount()
  })

  it('resolves the image on demand and retries after a failure', async () => {
    const transport = new CountingTransport()
    transport.status = 500
    const objectUrls: string[] = []
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: vi.fn(() => {
        const url = `blob:artifact-${objectUrls.length + 1}`
        objectUrls.push(url)
        return url
      }),
    })
    const wrapper = mountView(
      [part('p1', [referenceArtifact('art-big', 'workspace://.lam/artifacts/big.png', { size: 2048 })])],
      transport,
    )
    await expandToolRow(wrapper)
    await vi.waitFor(() => expect(wrapper.find('.tool-image-placeholder__retry').exists()).toBe(true))
    const failedRequests = transport.requests.length
    expect(failedRequests).toBeGreaterThan(0)

    // 重试：再取一次，成功后换成真实图片。
    transport.status = 200
    await wrapper.get('.tool-image-placeholder__retry').trigger('click')
    await vi.waitFor(() => expect(wrapper.find('.tool-image-card img').exists()).toBe(true))
    expect(transport.requests.length).toBeGreaterThan(failedRequests)
    // 取回后绑的是取到的字节（object URL），不再是空的或 data URL。
    expect(wrapper.get('.tool-image-card img').attributes('src')).toMatch(/^blob:/)
    expect(wrapper.find('.tool-image-placeholder').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keys the dedupe on the artifact identifier when there is no data URL', async () => {
    const transport = new CountingTransport()
    // 两张不同的引用图（无 data URL、标识符不同）：不能被并成一张。
    const wrapper = mountView([
      part('p1', [referenceArtifact('art-one', 'workspace://.lam/artifacts/one.png')]),
      part('p2', [referenceArtifact('art-two', 'workspace://.lam/artifacts/two.png')]),
    ], transport)
    expect(wrapper.findAll('.message-artifacts .message-attachment-deck__card')).toHaveLength(2)

    // 同一张引用图在多个 part 重复出现：只保留一项。
    const wrapper2 = mountView([
      part('p1', [referenceArtifact('art-one', 'workspace://.lam/artifacts/one.png')]),
      part('p2', [referenceArtifact('art-one', 'workspace://.lam/artifacts/one.png')]),
    ], transport)
    expect(wrapper2.findAll('.message-artifacts .message-attachment-deck__card')).toHaveLength(1)
    wrapper.unmount()
    wrapper2.unmount()
  })
})
