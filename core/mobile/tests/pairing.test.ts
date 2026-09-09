import { describe, expect, it } from 'vitest'
import { isPairingCode, normalizePairingCode, pairingResolveEndpoint } from '../src/pairing/PairingClient'

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
})
