import NoiseHandshake from 'noise-handshake'
import NoiseCipher from 'noise-handshake/cipher'
import { generateKeyPair } from 'noise-handshake/dh'
import b4a from 'b4a'
import type { TransportConnectionState } from '@lamtools/ui/transport'
import type { DeviceIdentity } from '../pairing/DeviceIdentity'
import type { TrustedDevice } from '../pairing/TrustedDevices'
import type { RemoteDiagnosticSink, TunnelWire } from './TunnelTransport'

const PROLOGUE = new TextEncoder().encode('LamTools Remote Tunnel v1')
const MAX_NOISE_PLAINTEXT = 60_000
const WEBSOCKET_OPEN_TIMEOUT_MS = 5_000
export const NOISE_HANDSHAKE_MESSAGE_TIMEOUT_MS = 5_000
export const REMOTE_PROTOCOL = 'lamtools-remote'
export const REMOTE_PROTOCOL_VERSION = 1

type PairOptions = {
  mode: 'pair'
  url: string
  pairingId: string
  code: string
  desktopPublicKey: string
  identity: DeviceIdentity
  relay?: { ticket: string; mobileDeviceId: string; targetDeviceId: string }
}

type ConnectOptions = {
  mode: 'connect'
  url: string
  trustedDevice: TrustedDevice
  identity: DeviceIdentity
  relay?: { ticket: string; mobileDeviceId: string; targetDeviceId: string }
}

type SecureWireOptions = PairOptions | ConnectOptions

export class NoiseSecureWire implements TunnelWire {
  private socket: WebSocket | null = null
  private sendCipher: NoiseCipher | null = null
  private receiveCipher: NoiseCipher | null = null
  private readonly dataListeners = new Set<(data: Uint8Array) => void>()
  private readonly stateListeners = new Set<(state: TransportConnectionState) => void>()
  private connectPromise: Promise<void> | null = null
  // Monotonically increasing generation. Every socket callback must prove it
  // still belongs to this generation before it can touch shared wire state.
  private connectionGeneration = 0
  private pairingResult: Record<string, unknown> | null = null
  private tunnelId = ''
  private handshakeAbort: AbortController | null = null

  constructor(
    private readonly options: SecureWireOptions,
    private readonly diagnosticSink: RemoteDiagnosticSink = () => {},
    private readonly handshakeTimeoutMs = NOISE_HANDSHAKE_MESSAGE_TIMEOUT_MS,
  ) {}

  connect(): Promise<void> {
    if (!this.connectPromise) {
      const generation = ++this.connectionGeneration
      const controller = new AbortController()
      this.handshakeAbort = controller
      const promise = this.open(generation, controller).finally(() => {
        if (this.handshakeAbort === controller) this.handshakeAbort = null
      })
      this.connectPromise = promise
    }
    return this.connectPromise
  }

  result(): Record<string, unknown> | null { return this.pairingResult }

  send(data: Uint8Array): void {
    const socket = this.socket
    const cipher = this.sendCipher
    if (!socket || socket.readyState !== WebSocket.OPEN || !cipher) throw new Error('安全隧道尚未连接')
    for (let offset = 0; offset < data.length; offset += MAX_NOISE_PLAINTEXT) {
      this.sendPacket(cipher.encrypt(data.subarray(offset, offset + MAX_NOISE_PLAINTEXT)))
    }
  }

  onData(listener: (data: Uint8Array) => void): () => void {
    this.dataListeners.add(listener)
    return () => this.dataListeners.delete(listener)
  }

  onState(listener: (state: TransportConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    return () => this.stateListeners.delete(listener)
  }

  close(): void {
    this.connectionGeneration += 1
    this.handshakeAbort?.abort()
    this.handshakeAbort = null
    const socket = this.socket
    this.socket = null
    this.sendCipher = null
    this.receiveCipher = null
    this.connectPromise = null
    this.tunnelId = ''
    this.pairingResult = null
    if (socket && socket.readyState < WebSocket.CLOSING) socket.close()
    this.emitState('disconnected')
  }

  private async open(generation: number, controller: AbortController): Promise<void> {
    const signal = controller.signal
    this.emitState('connecting')
    let socket: WebSocket | null = null
    try {
      const identityKeys = generateKeyPair(fromBase64Url(this.options.identity.privateKey))
      if (!constantTimeEqual(identityKeys.publicKey, fromBase64Url(this.options.identity.publicKey))) {
        throw new Error('手机设备身份密钥不匹配')
      }
      // The short-lived pairing code is carried inside the encrypted third XX
      // message and is never exposed as a URL/query credential.
      const noise = new NoiseHandshake('XX', true, identityKeys)
      noise.initialise(PROLOGUE)
      const url = new URL(this.options.url)
      if (this.options.mode === 'pair') url.searchParams.set('pairing', this.options.pairingId)
      if (this.options.relay) {
        url.searchParams.set('role', 'mobile')
        url.searchParams.set('device_id', this.options.relay.mobileDeviceId)
        url.searchParams.set('target', this.options.relay.targetDeviceId)
        url.searchParams.set('ticket', this.options.relay.ticket)
        if (this.options.mode === 'pair') url.searchParams.set('pairing_id', this.options.pairingId)
      }
      socket = new WebSocket(url.toString())
      socket.binaryType = 'arraybuffer'
      this.socket = socket
      // Arm the relay-ready listener before waiting for the WebSocket open
      // event. A relay can have the bridge ready by the time the client sees
      // its open callback, and WebSocket events are not replayed for listeners
      // attached after delivery.
      const relayReadyPromise = this.options.relay
        ? nextTextMessage(socket, this.handshakeTimeoutMs, signal)
        : null
      // If opening fails before the relay-ready phase is awaited, the catch
      // path aborts this shared controller. Mark the pre-armed promise as
      // handled so that cleanup does not create an unhandled rejection.
      if (relayReadyPromise) void relayReadyPromise.catch(() => undefined)
      const isCurrent = () => this.socket === socket && this.connectionGeneration === generation
      await waitForOpen(socket, signal)
      if (!isCurrent()) throw new Error('安全隧道连接已取消')
      if (this.options.relay) {
        const ready = JSON.parse(await relayReadyPromise!) as { tunnel_id?: string }
        if (!isCurrent()) throw new Error('安全隧道连接已取消')
        if (!ready.tunnel_id || ready.tunnel_id.length !== 36) throw new Error('远程隧道路由失败')
        this.tunnelId = ready.tunnel_id
      }
      this.sendPacket(noise.send())
      noise.recv(await nextBinaryMessage(socket, this.tunnelId, this.handshakeTimeoutMs, signal))
      if (!isCurrent()) throw new Error('安全隧道连接已取消')
      const expectedDesktopKey = fromBase64Url(
        this.options.mode === 'pair' ? this.options.desktopPublicKey : this.options.trustedDevice.publicKey || '',
      )
      if (!expectedDesktopKey.length || !constantTimeEqual(noise.rs, expectedDesktopKey)) {
        throw new Error('电脑设备身份验证失败')
      }
      const auth = this.options.mode === 'pair'
        ? {
            mode: 'pair',
            code: this.options.code,
            device_id: this.options.identity.deviceId,
            device_name: 'LamTools Mobile',
            platform: 'mobile',
          }
        : {
            mode: 'connect',
            access_token: this.options.trustedDevice.accessToken || '',
            device_id: this.options.identity.deviceId,
          }
      this.sendPacket(noise.send(new TextEncoder().encode(JSON.stringify(auth))))
      // snow follows the Noise split convention: the initiator writes with
      // k1 (`tx`) and reads with k2 (`rx`).
      this.sendCipher = new NoiseCipher(noise.tx)
      this.receiveCipher = new NoiseCipher(noise.rx)
      const ack = this.receiveCipher.decrypt(await nextBinaryMessage(socket, this.tunnelId, this.handshakeTimeoutMs, signal))
      if (!isCurrent()) throw new Error('安全隧道连接已取消')
      const result = JSON.parse(new TextDecoder().decode(ack)) as Record<string, unknown>
      if (result.protocol !== REMOTE_PROTOCOL || result.version !== REMOTE_PROTOCOL_VERSION) {
        throw new Error('电脑安全隧道协议版本不兼容')
      }
      this.pairingResult = result
      socket.onmessage = (event) => {
        if (isCurrent()) this.handleMessage(event.data, generation)
      }
      socket.onerror = () => {
        if (!isCurrent()) return
        this.report({ event: 'socket_error', connection_generation: generation })
        this.emitState('failed')
      }
      socket.onclose = (event) => {
        if (!isCurrent()) return
        this.report({
          event: 'socket_closed',
          connection_generation: generation,
          close_code: event.code,
          close_reason: event.reason,
          close_was_clean: event.wasClean,
        })
        this.socket = null
        this.sendCipher = null
        this.receiveCipher = null
        this.tunnelId = ''
        this.pairingResult = null
        this.connectPromise = null
        this.emitState('disconnected')
      }
      this.emitState('connected')
    } catch (error) {
      controller.abort()
      if (socket && socket.readyState < WebSocket.CLOSING) socket.close()
      if (this.connectionGeneration === generation) {
        if (this.socket === socket) this.socket = null
        this.sendCipher = null
        this.receiveCipher = null
        this.tunnelId = ''
        this.connectPromise = null
        this.emitState('failed')
      }
      throw error
    }
  }

  private handleMessage(value: unknown, generation: number): void {
    const cipher = this.receiveCipher
    if (!cipher) return
    const tunnelId = this.tunnelId
    void binaryValue(value).then((packet) => {
      if (this.connectionGeneration !== generation || this.receiveCipher !== cipher) return
      const encrypted = tunnelId ? stripRelayPrefix(packet, tunnelId) : packet
      const plaintext = cipher.decrypt(encrypted)
      for (const listener of this.dataListeners) listener(plaintext)
    }).catch((error) => {
      if (this.connectionGeneration !== generation || this.receiveCipher !== cipher) return
      this.report({
        event: 'wire_message_failed',
        error: error instanceof Error ? error.stack || error.message : String(error),
        connection_generation: generation,
      })
      this.emitState('failed')
      this.close()
    })
  }

  private sendPacket(bytes: Uint8Array): void {
    const socket = this.socket
    if (!socket) throw new Error('安全隧道尚未连接')
    if (!this.tunnelId) { sendBinary(socket, bytes); return }
    const prefix = new TextEncoder().encode(this.tunnelId)
    const packet = new Uint8Array(prefix.length + bytes.length)
    packet.set(prefix)
    packet.set(bytes, prefix.length)
    sendBinary(socket, packet)
  }

  private emitState(state: TransportConnectionState): void {
    for (const listener of this.stateListeners) listener(state)
  }

  private report(event: Omit<Parameters<RemoteDiagnosticSink>[0], 'component'>): void {
    try {
      this.diagnosticSink({ component: 'mobile', ...event })
    } catch {
      // Diagnostics must never alter the transport's control flow.
    }
  }
}

export async function pairSecure(options: Omit<PairOptions, 'mode'>): Promise<Record<string, unknown>> {
  const wire = new NoiseSecureWire({ mode: 'pair', ...options })
  await wire.connect()
  const result = wire.result()
  wire.close()
  if (!result) throw new Error('配对服务未返回结果')
  return result
}

export function createTrustedSecureWire(
  url: string,
  trustedDevice: TrustedDevice,
  identity: DeviceIdentity,
  diagnosticSink?: RemoteDiagnosticSink,
  handshakeTimeoutMs?: number,
): NoiseSecureWire {
  return new NoiseSecureWire(
    { mode: 'connect', url, trustedDevice, identity },
    diagnosticSink,
    handshakeTimeoutMs,
  )
}

export function createRelaySecureWire(
  url: string,
  ticket: string,
  trustedDevice: TrustedDevice,
  identity: DeviceIdentity,
  diagnosticSink?: RemoteDiagnosticSink,
  handshakeTimeoutMs?: number,
): NoiseSecureWire {
  return new NoiseSecureWire({
    mode: 'connect',
    url,
    trustedDevice,
    identity,
    relay: { ticket, mobileDeviceId: identity.deviceId, targetDeviceId: trustedDevice.deviceId },
  }, diagnosticSink, handshakeTimeoutMs)
}

function fromBase64Url(value: string): Uint8Array {
  if (!value) return new Uint8Array()
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  return b4a.from(normalized + '='.repeat((4 - normalized.length % 4) % 4), 'base64')
}

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false
  let difference = 0
  for (let index = 0; index < left.length; index += 1) difference |= left[index] ^ right[index]
  return difference === 0
}

function waitForOpen(socket: WebSocket, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false
    const onOpen = () => finish(resolve)
    const onError = () => finish(() => reject(new Error('无法连接电脑安全隧道')))
    const onClose = () => finish(() => reject(new Error('电脑安全隧道已关闭')))
    const onAbort = () => finish(() => reject(new Error('安全隧道连接已取消')))
    const cleanup = () => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      if (socket.onopen === onOpen) socket.onopen = null
      if (socket.onerror === onError) socket.onerror = null
      if (socket.onclose === onClose) socket.onclose = null
    }
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      cleanup()
      callback()
    }
    const timer = setTimeout(() => {
      finish(() => reject(new Error('电脑安全隧道连接超时')))
    }, WEBSOCKET_OPEN_TIMEOUT_MS)
    socket.onopen = onOpen
    socket.onerror = onError
    socket.onclose = onClose
    signal?.addEventListener('abort', onAbort, { once: true })
    if (signal?.aborted) onAbort()
  })
}

function sendBinary(socket: WebSocket, bytes: Uint8Array): void {
  socket.send(Uint8Array.from(bytes).buffer)
}

function nextBinaryMessage(
  socket: WebSocket,
  tunnelId = '',
  timeoutMs = NOISE_HANDSHAKE_MESSAGE_TIMEOUT_MS,
  signal?: AbortSignal,
): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    let settled = false
    let messageSeen = false
    const onMessage = (event: MessageEvent) => {
      if (messageSeen) return
      messageSeen = true
      void binaryValue(event.data).then((packet) => finish(() => resolve(tunnelId ? stripRelayPrefix(packet, tunnelId) : packet)), (error) => finish(() => reject(error)))
    }
    const onClose = () => finish(() => reject(new Error('安全握手期间连接已关闭')))
    const onError = () => finish(() => reject(new Error('安全握手失败')))
    const onAbort = () => finish(() => reject(new Error('安全隧道连接已取消')))
    const cleanup = () => {
      clearTimeout(timer)
      socket.removeEventListener('message', onMessage)
      socket.removeEventListener('close', onClose)
      socket.removeEventListener('error', onError)
      signal?.removeEventListener('abort', onAbort)
    }
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      cleanup()
      callback()
    }
    const timer = setTimeout(() => finish(() => reject(new Error('安全握手消息超时'))), timeoutMs)
    socket.addEventListener('message', onMessage)
    socket.addEventListener('close', onClose, { once: true })
    socket.addEventListener('error', onError, { once: true })
    signal?.addEventListener('abort', onAbort, { once: true })
    if (signal?.aborted) onAbort()
  })
}

function nextTextMessage(
  socket: WebSocket,
  timeoutMs = NOISE_HANDSHAKE_MESSAGE_TIMEOUT_MS,
  signal?: AbortSignal,
): Promise<string> {
  return new Promise((resolve, reject) => {
    let settled = false
    const onMessage = (event: MessageEvent) => {
      if (typeof event.data !== 'string') return
      finish(() => resolve(event.data))
    }
    const onClose = () => finish(() => reject(new Error('远程服务已关闭连接')))
    const onError = () => finish(() => reject(new Error('远程服务握手失败')))
    const onAbort = () => finish(() => reject(new Error('安全隧道连接已取消')))
    const cleanup = () => {
      clearTimeout(timer)
      socket.removeEventListener('message', onMessage)
      socket.removeEventListener('close', onClose)
      socket.removeEventListener('error', onError)
      signal?.removeEventListener('abort', onAbort)
    }
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      cleanup()
      callback()
    }
    const timer = setTimeout(() => finish(() => reject(new Error('远程服务握手超时'))), timeoutMs)
    socket.addEventListener('message', onMessage)
    socket.addEventListener('close', onClose, { once: true })
    socket.addEventListener('error', onError, { once: true })
    signal?.addEventListener('abort', onAbort, { once: true })
    if (signal?.aborted) onAbort()
  })
}

function stripRelayPrefix(packet: Uint8Array, tunnelId: string): Uint8Array {
  if (packet.length < 36 || new TextDecoder().decode(packet.subarray(0, 36)) !== tunnelId) throw new Error('远程隧道路由标识无效')
  return packet.subarray(36)
}

async function binaryValue(value: unknown): Promise<Uint8Array> {
  if (value instanceof ArrayBuffer) return new Uint8Array(value)
  if (typeof Blob !== 'undefined' && value instanceof Blob) return new Uint8Array(await value.arrayBuffer())
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
  throw new Error('安全隧道收到非二进制数据')
}
