import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isPairingCode,
  normalizePairingCode,
  PairingClient,
  pairingResolveEndpoint,
  trustedGatewayUrl,
} from '../src/pairing/PairingClient'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('numeric pairing', () => {
  it('accepts exactly six ASCII digits and preserves leading zeroes', () => {
    expect(isPairingCode('012345')).toBe(true)
    expect(isPairingCode('12345')).toBe(false)
    expect(isPairingCode('1234567')).toBe(false)
    expect(isPairingCode('12a456')).toBe(false)
  })

  it('normalizes keyboard input to six digits', () => {
    expect(normalizePairingCode(' 0a12-3457 ')).toBe('012345')
  })

  it('derives the HTTP resolve endpoint from a desktop gateway endpoint', () => {
    expect(pairingResolveEndpoint('wss://relay.example.test/v1/relay?old=1#pairing'))
      .toBe('https://relay.example.test/_lamtools/pairing/resolve')
    expect(pairingResolveEndpoint('ws://127.0.0.1:8787/v1/relay'))
      .toBe('http://127.0.0.1:8787/_lamtools/pairing/resolve')
  })

  it('keeps the LAN resolve request within the gateway CORS allowlist', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(new PairingClient({ gatewayUrl: 'ws://192.168.1.5:8787' }).redeem('123456'))
      .rejects.toThrow('网关返回了无效的配对信息')

    const [, init] = fetchMock.mock.calls[0]!
    expect(init?.headers).toEqual({
      Accept: 'application/json',
      'Content-Type': 'application/json',
    })
    expect(init?.cache).toBe('no-store')
  })

  it('persists the direct route that actually completed pairing', () => {
    const pairing = {
      pairingId: 'pair-1',
      desktopDeviceId: 'desktop-1',
      desktopPublicKey: 'public-key',
      gatewayUrl: 'ws://192.168.31.220:55791/_lamtools/tunnel',
      expiresAtMs: Date.now() + 60_000,
      protocol: 'lamtools-remote',
      version: 1,
    }

    expect(trustedGatewayUrl(pairing, {
      gatewayUrl: 'ws://26.225.255.49:55791/_lamtools/tunnel',
    })).toBe('ws://192.168.31.220:55791/_lamtools/tunnel')
  })
})
