/** Versioned, transport-neutral framing shared by LAN and Relay tunnels. */
export const TUNNEL_PROTOCOL_VERSION = 1 as const

export const TUNNEL_LIMITS = Object.freeze({
  frameBytes: 4 * 1024 * 1024,
  messageBytes: 128 * 1024 * 1024,
  chunkPayloadBytes: 256 * 1024,
  inflightMessages: 16,
})

export const TUNNEL_FRAME_TYPES = Object.freeze({
  rpc: 'rpc.data',
  httpRequest: 'http.request',
  httpResponse: 'http.response',
  httpCancel: 'http.cancel',
  binary: 'binary.data',
  control: 'control.data',
  event: 'event.data',
})

export const TUNNEL_STREAMS = Object.freeze({
  rpc: 'rpc',
  binary: 'binary',
  control: 'control',
  event: 'event',
})

export interface TunnelFrame {
  version: typeof TUNNEL_PROTOCOL_VERSION
  type: string
  stream_id: string
  request_id?: string
  payload?: string
  message_id?: string
  chunk_index?: number
  chunk_final?: boolean
  sequence: number
}

export interface TunnelFrameDecoderOptions {
  /** Test/resource-budget override; values above the protocol limit are rejected. */
  maxMessageBytes?: number
}

const textEncoder = new TextEncoder()

export function encodeTunnelFrame(frame: TunnelFrame): Uint8Array {
  validateTunnelFrame(frame)
  const encoded = textEncoder.encode(JSON.stringify(frame))
  if (encoded.length > TUNNEL_LIMITS.frameBytes) throw new Error('tunnel frame is too large')
  const line = new Uint8Array(encoded.length + 1)
  line.set(encoded)
  line[encoded.length] = 0x0a
  return line
}

export function decodeTunnelFrames(buffer: Uint8Array): { frames: TunnelFrame[]; remainder: Uint8Array } {
  const frames: TunnelFrame[] = []
  let start = 0
  for (let index = 0; index < buffer.length; index += 1) {
    if (buffer[index] !== 0x0a) continue
    if (index - start > TUNNEL_LIMITS.frameBytes) throw new Error('tunnel frame is too large')
    const line = new TextDecoder('utf-8', { fatal: true }).decode(buffer.subarray(start, index))
    start = index + 1
    if (!line.trim()) continue
    const parsed: unknown = JSON.parse(line)
    validateTunnelFrame(parsed)
    frames.push(parsed)
  }
  const remainder = buffer.slice(start)
  // A network read may contain many complete frames. Limit only the
  // unfinished frame, otherwise a valid coalesced batch would be rejected.
  if (remainder.length > TUNNEL_LIMITS.frameBytes) throw new Error('tunnel frame is too large')
  return { frames, remainder }
}

/** Incremental decoder with replay protection and bounded message assembly. */
export class TunnelFrameDecoder {
  private buffered: Uint8Array<ArrayBufferLike> = new Uint8Array()
  private lastSequence = 0
  private readonly maxMessageBytes: number
  private readonly partials = new Map<string, {
    frame: TunnelFrame
    chunks: string[]
    nextChunkIndex: number
    payloadBytes: number
  }>()

  constructor(options: TunnelFrameDecoderOptions = {}) {
    const maxMessageBytes = options.maxMessageBytes ?? TUNNEL_LIMITS.messageBytes
    if (!Number.isSafeInteger(maxMessageBytes)
      || maxMessageBytes <= 0
      || maxMessageBytes > TUNNEL_LIMITS.messageBytes) {
      throw new Error('invalid tunnel message limit')
    }
    this.maxMessageBytes = maxMessageBytes
  }

  push(chunk: Uint8Array): TunnelFrame[] {
    const merged = new Uint8Array(this.buffered.length + chunk.length)
    merged.set(this.buffered)
    merged.set(chunk, this.buffered.length)
    const { frames, remainder } = decodeTunnelFrames(merged)
    const complete: TunnelFrame[] = []
    for (const frame of frames) {
      if (frame.sequence <= this.lastSequence) throw new Error('tunnel frame sequence replay detected')
      this.lastSequence = frame.sequence
      const assembled = this.pushFrame(frame)
      if (assembled) complete.push(assembled)
    }
    this.buffered = remainder
    return complete
  }

  sequence(): number { return this.lastSequence }

  reset(): void {
    this.buffered = new Uint8Array()
    this.lastSequence = 0
    this.partials.clear()
  }

  private pushFrame(frame: TunnelFrame): TunnelFrame | null {
    if (frame.message_id === undefined) {
      if (frame.chunk_index !== undefined || frame.chunk_final !== undefined) {
        throw new Error('无效的 tunnel 分片元数据')
      }
      return frame
    }
    if (frame.chunk_index === undefined || frame.chunk_final === undefined || typeof frame.payload !== 'string') {
      throw new Error('无效的 tunnel 分片元数据')
    }
    const messageId = frame.message_id
    const chunkIndex = frame.chunk_index
    const payloadBytes = utf8ByteLength(frame.payload)
    if (chunkIndex === 0) {
      if (this.partials.size >= TUNNEL_LIMITS.inflightMessages || this.partials.has(messageId)) {
        throw new Error('tunnel 分片消息过多或重复')
      }
      if (payloadBytes > this.maxMessageBytes) throw new Error('tunnel 消息过大')
      if (frame.chunk_final) return withoutChunkMetadata(frame)
      const base = withoutChunkMetadata(frame)
      delete base.payload
      this.partials.set(messageId, {
        frame: base,
        chunks: [frame.payload],
        nextChunkIndex: 1,
        payloadBytes,
      })
      return null
    }
    const partial = this.partials.get(messageId)
    if (!partial || chunkIndex !== partial.nextChunkIndex || !sameChunkEnvelope(partial.frame, frame)) {
      throw new Error('tunnel 分片顺序或信封无效')
    }
    const totalBytes = partial.payloadBytes + payloadBytes
    if (totalBytes > this.maxMessageBytes) throw new Error('tunnel 消息过大')
    partial.payloadBytes = totalBytes
    partial.nextChunkIndex += 1
    partial.chunks.push(frame.payload)
    if (!frame.chunk_final) return null
    this.partials.delete(messageId)
    return { ...partial.frame, payload: partial.chunks.join('') }
  }
}

/** Split by encoded bytes while preserving UTF-16 surrogate pairs. */
export function splitTunnelPayload(payload: string): string[] {
  const chunks: string[] = []
  let start = 0
  let bytes = 0
  for (let index = 0; index < payload.length;) {
    const codePoint = payload.codePointAt(index) ?? 0xfffd
    const width = codePoint > 0xffff ? 2 : 1
    const encodedBytes = codePoint <= 0x7f ? 1 : codePoint <= 0x7ff ? 2 : codePoint <= 0xffff ? 3 : 4
    if (bytes > 0 && bytes + encodedBytes > TUNNEL_LIMITS.chunkPayloadBytes) {
      chunks.push(payload.slice(start, index))
      start = index
      bytes = 0
    }
    index += width
    bytes += encodedBytes
  }
  chunks.push(payload.slice(start))
  return chunks
}

export function utf8ByteLength(value: string): number {
  return textEncoder.encode(value).byteLength
}

export function validateTunnelFrame(frame: unknown): asserts frame is TunnelFrame {
  if (!isRecord(frame)
    || frame.version !== TUNNEL_PROTOCOL_VERSION
    || typeof frame.type !== 'string'
    || frame.type.trim().length === 0
    || utf8ByteLength(frame.type) > 64
    || typeof frame.stream_id !== 'string'
    || frame.stream_id.trim().length === 0
    || utf8ByteLength(frame.stream_id) > 256
    || !Number.isSafeInteger(frame.sequence)
    || Number(frame.sequence) <= 0
    || (frame.request_id !== undefined
      && (typeof frame.request_id !== 'string'
        || frame.request_id.length === 0
        || utf8ByteLength(frame.request_id) > 256))
    || (frame.payload !== undefined && typeof frame.payload !== 'string')
    || (frame.message_id !== undefined
      && (typeof frame.message_id !== 'string'
        || frame.message_id.length === 0
        || utf8ByteLength(frame.message_id) > 256))
    || (frame.chunk_index !== undefined
      && (!Number.isSafeInteger(frame.chunk_index) || Number(frame.chunk_index) < 0 || Number(frame.chunk_index) > 524_288))
    || (frame.chunk_final !== undefined && typeof frame.chunk_final !== 'boolean')) {
    throw new Error('无效的 tunnel frame')
  }
  const hasMessageId = frame.message_id !== undefined
  if (hasMessageId !== (frame.chunk_index !== undefined)
    || hasMessageId !== (frame.chunk_final !== undefined)) {
    throw new Error('无效的 tunnel 分片元数据')
  }
}

function withoutChunkMetadata(frame: TunnelFrame): TunnelFrame {
  const { message_id: _messageId, chunk_index: _chunkIndex, chunk_final: _chunkFinal, ...complete } = frame
  return complete
}

function sameChunkEnvelope(initial: TunnelFrame, continuation: TunnelFrame): boolean {
  return initial.version === continuation.version
    && initial.type === continuation.type
    && initial.stream_id === continuation.stream_id
    && initial.request_id === continuation.request_id
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
