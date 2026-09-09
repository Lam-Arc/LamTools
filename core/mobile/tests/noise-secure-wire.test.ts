import { afterEach, describe, expect, it } from 'vitest'
import { WebSocketServer, WebSocket as NodeWebSocket } from 'ws'
import NoiseHandshake from 'noise-handshake'
import NoiseCipher from 'noise-handshake/cipher'
import { generateKeyPair } from 'noise-handshake/dh'
import { MemorySecureStorage } from '../src/native/secureStorage'
import { loadOrCreateAccountDeviceIdentity, loadOrCreateDeviceIdentity } from '../src/pairing/DeviceIdentity'
import { createTrustedSecureWire } from '../src/connection/NoiseSecureWire'

const originalWebSocket = globalThis.WebSocket
const PROLOGUE = new TextEncoder().encode('LamTools Remote Tunnel v1')
let server: WebSocketServer | null = null

describe('NoiseSecureWire', () => {
  it('keeps device identities isolated between server accounts', async () => {
    const storage = new MemorySecureStorage()
    const first = await loadOrCreateAccountDeviceIdentity('server-1', 'alice', storage)
    const restored = await loadOrCreateAccountDeviceIdentity('server-1', 'Alice', storage)
    const second = await loadOrCreateAccountDeviceIdentity('server-1', 'bob', storage)
    expect(restored.deviceId).toBe(first.deviceId)
    expect(second.deviceId).not.toBe(first.deviceId)
  })

  afterEach(async () => {
    if (server) await new Promise<void>((resolve) => server!.close(() => resolve()))
    server = null
    globalThis.WebSocket = originalWebSocket
  })

  it('interoperates with the Rust snow XX transcript direction', async () => {
    globalThis.WebSocket = NodeWebSocket as unknown as typeof WebSocket
    const desktopKeys = generateKeyPair()
    const mobileIdentity = await loadOrCreateDeviceIdentity(new MemorySecureStorage())
    const mobileKeys = generateKeyPair(fromBase64Url(mobileIdentity.privateKey))
    const port = await startResponder(desktopKeys, 1)
    const trusted = {
      deviceId: 'desktop-test', name: 'Desktop', publicKey: toBase64Url(desktopKeys.publicKey), accessToken: 'access-token',
    }
    const wire = createTrustedSecureWire(`ws://127.0.0.1:${port}/_lamtools/tunnel`, trusted, mobileIdentity)
    // Keep the generated keypair referenced so the test asserts the identity
    // used by the browser implementation is valid X25519 material.
    expect(mobileKeys.publicKey).toHaveLength(32)
    await wire.connect()
    const received = new Promise<Uint8Array>((resolve) => wire.onData(resolve))
    wire.send(new TextEncoder().encode('hello'))
    expect(new TextDecoder().decode(await received)).toBe('hello')
    wire.close()
  })

  it('rejects a local device identity whose public key does not match its private key', async () => {
    const identity = await loadOrCreateDeviceIdentity(new MemorySecureStorage())
    const mismatched = generateKeyPair()
    const wire = createTrustedSecureWire('ws://127.0.0.1:1/_lamtools/tunnel', {
      deviceId: 'desktop-test',
      name: 'Desktop',
      publicKey: toBase64Url(generateKeyPair().publicKey),
      accessToken: 'access-token',
    }, { ...identity, publicKey: toBase64Url(mismatched.publicKey) })
    const states: string[] = []
    wire.onState((state) => states.push(state))

    await expect(wire.connect()).rejects.toThrow('手机设备身份密钥不匹配')
    expect(states).toEqual(['connecting', 'failed'])
  })

  it('rejects a Noise peer whose static identity does not match the paired desktop', async () => {
    globalThis.WebSocket = NodeWebSocket as unknown as typeof WebSocket
    const responderKeys = generateKeyPair()
    const expectedKeys = generateKeyPair()
    const identity = await loadOrCreateDeviceIdentity(new MemorySecureStorage())
    const port = await startResponder(responderKeys, 1)
    const wire = createTrustedSecureWire(`ws://127.0.0.1:${port}/_lamtools/tunnel`, {
      deviceId: 'desktop-test',
      name: 'Desktop',
      publicKey: toBase64Url(expectedKeys.publicKey),
      accessToken: 'access-token',
    }, identity)
    const states: string[] = []
    wire.onState((state) => states.push(state))

    await expect(wire.connect()).rejects.toThrow('电脑设备身份验证失败')
    expect(states).toEqual(['connecting', 'failed'])
  })

  it('rejects a peer that acknowledges an incompatible remote protocol version', async () => {
    globalThis.WebSocket = NodeWebSocket as unknown as typeof WebSocket
    const desktopKeys = generateKeyPair()
    const identity = await loadOrCreateDeviceIdentity(new MemorySecureStorage())
    const port = await startResponder(desktopKeys, 2)
    const wire = createTrustedSecureWire(`ws://127.0.0.1:${port}/_lamtools/tunnel`, {
      deviceId: 'desktop-test',
      name: 'Desktop',
      publicKey: toBase64Url(desktopKeys.publicKey),
      accessToken: 'access-token',
    }, identity)
    const states: string[] = []
    wire.onState((state) => states.push(state))

    await expect(wire.connect()).rejects.toThrow('协议版本不兼容')
    expect(states).toEqual(['connecting', 'failed'])
  })

  it('fails promptly when the websocket closes during the Noise handshake', async () => {
    globalThis.WebSocket = NodeWebSocket as unknown as typeof WebSocket
    const identity = await loadOrCreateDeviceIdentity(new MemorySecureStorage())
    server = new WebSocketServer({ port: 0 })
    await new Promise<void>((resolve) => server!.once('listening', () => resolve()))
    server.on('connection', (socket) => socket.close())
    const port = (server.address() as { port: number }).port
    const wire = createTrustedSecureWire(`ws://127.0.0.1:${port}/_lamtools/tunnel`, {
      deviceId: 'desktop-test',
      name: 'Desktop',
      publicKey: toBase64Url(generateKeyPair().publicKey),
      accessToken: 'access-token',
    }, identity)

    await expect(wire.connect()).rejects.toThrow(/关闭|失败/)
  })
})

async function startResponder(desktopKeys: ReturnType<typeof generateKeyPair>, ackVersion: number): Promise<number> {
  server = new WebSocketServer({ port: 0 })
  await new Promise<void>((resolve) => server!.once('listening', () => resolve()))
  server.on('connection', (socket) => {
    const responder = new NoiseHandshake('XX', false, desktopKeys)
    responder.initialise(PROLOGUE)
    let handshakeStep = 0
    let send: NoiseCipher | null = null
    let receive: NoiseCipher | null = null
    socket.on('message', (data) => {
      try {
        const input = new Uint8Array(data as ArrayBuffer)
        if (handshakeStep === 0) {
          responder.recv(input)
          socket.send(responder.send())
          handshakeStep = 1
        } else if (handshakeStep === 1) {
          const auth = new TextDecoder().decode(responder.recv(input))
          expect(JSON.parse(auth).mode).toBe('connect')
          send = new NoiseCipher(responder.tx)
          receive = new NoiseCipher(responder.rx)
          socket.send(send.encrypt(new TextEncoder().encode(JSON.stringify({
            status: 'ok', protocol: 'lamtools-remote', version: ackVersion,
          }))))
          handshakeStep = 2
        } else if (send && receive) {
          const decoded = receive.decrypt(input)
          socket.send(send.encrypt(decoded))
        }
      } catch {
        socket.close()
      }
    })
  })
  return (server.address() as { port: number }).port
}

function fromBase64Url(value: string): Uint8Array {
  const normalized = value.replace(/-/g, '+').replace(/_/g, '/')
  return Uint8Array.from(Buffer.from(normalized + '='.repeat((4 - normalized.length % 4) % 4), 'base64'))
}

function toBase64Url(value: Uint8Array): string {
  return Buffer.from(value).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}
