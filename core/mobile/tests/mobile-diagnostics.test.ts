import { describe, expect, it } from 'vitest'
import {
  MOBILE_DIAGNOSTIC_EXPORT_LIMIT_BYTES,
  MOBILE_DIAGNOSTIC_RETENTION_LIMIT,
  MobileDiagnostics,
} from '../src/diagnostics/MobileDiagnostics'

describe('mobile diagnostics export', () => {
  it('retains a bounded payload-free allowlist and excludes user identifiers and raw errors', () => {
    const diagnostics = new MobileDiagnostics({
      now: () => new Date('2026-09-24T03:04:05.000Z'),
      limit: 2,
    })

    diagnostics.recordTransport({
      component: 'mobile',
      event: 'rpc_received',
      request_id: 'request-private-id',
      method: 'session.login',
      error: 'Bearer top-secret https://private.example/path?token=private',
      bytes: 42,
      status: 503,
    })
    diagnostics.recordNativeStage({ turnId: 'turn-private-id', stage: 'native_runtime_start' })
    diagnostics.recordTransport({
      component: 'mobile',
      event: 'socket_closed',
      close_reason: 'private-device-name token=hidden',
      close_code: 1006,
      close_was_clean: false,
    })

    const exported = diagnostics.serialize()
    const parsed = JSON.parse(exported) as {
      entries: Array<Record<string, unknown>>
      retention: string
      redaction: string
    }

    expect(parsed.entries).toHaveLength(2)
    expect(parsed.entries[0]).toMatchObject({
      source: 'native',
      event: 'native_runtime_start',
      at: '2026-09-24T03:04:05.000Z',
    })
    expect(parsed.entries[1]).toMatchObject({
      source: 'transport',
      event: 'socket_closed',
      close_code: 1006,
      close_was_clean: false,
    })
    expect(exported).not.toContain('request-private-id')
    expect(exported).not.toContain('turn-private-id')
    expect(exported).not.toContain('private-device-name')
    expect(exported).not.toContain('top-secret')
    expect(exported).not.toContain('private.example')
    expect(exported).not.toContain('session.login')
    expect(parsed.retention).toContain('重新载入后清空')
    expect(parsed.redaction).toContain('网络地址')
    expect(new TextEncoder().encode(exported).byteLength).toBeLessThanOrEqual(MOBILE_DIAGNOSTIC_EXPORT_LIMIT_BYTES)
  })

  it('drops unknown event names and native stages instead of exporting arbitrary strings', () => {
    const diagnostics = new MobileDiagnostics()
    diagnostics.recordTransport({ component: 'mobile', event: 'authorization_header_dump', error: 'key=private' })
    diagnostics.recordNativeStage({ turnId: 'secret-turn', stage: 'provider_response_body' })
    expect(diagnostics.snapshot()).toEqual([])
  })

  it('keeps at most 500 records and notifies subscribers after clearing', () => {
    const diagnostics = new MobileDiagnostics()
    const snapshots: number[] = []
    const unsubscribe = diagnostics.subscribe(entries => snapshots.push(entries.length))

    for (let sequence = 1; sequence <= MOBILE_DIAGNOSTIC_RETENTION_LIMIT + 2; sequence += 1) {
      diagnostics.recordTransport({ component: 'mobile', event: 'frame_sent', sequence, bytes: 10 })
    }

    expect(diagnostics.snapshot()).toHaveLength(MOBILE_DIAGNOSTIC_RETENTION_LIMIT)
    expect(diagnostics.snapshot()[0].sequence).toBe(3)
    diagnostics.clear()
    expect(diagnostics.snapshot()).toEqual([])
    expect(snapshots.at(-1)).toBe(0)
    unsubscribe()
  })

  it('exports only categorized errors without retaining the raw value', () => {
    const diagnostics = new MobileDiagnostics()
    diagnostics.recordTransport({
      component: 'mobile',
      event: 'frame_receive_failed',
      error: 'decrypt failed for key=secret-value',
    })

    const exported = diagnostics.serialize()
    expect(exported).toContain('"error_kind": "protocol"')
    expect(exported).not.toContain('secret-value')
    expect(exported).not.toContain('decrypt failed')
  })
})
