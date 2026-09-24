import { beforeEach, describe, expect, it, vi } from 'vitest'

const invoke = vi.hoisted(() => vi.fn())
vi.mock('@tauri-apps/api/core', () => ({ invoke }))

import { TauriSecureStorage } from '../src/native/secureStorage'

describe('restored Android secure storage', () => {
  beforeEach(() => invoke.mockReset())

  it('clears only an invalidated entry so identity can be recreated', async () => {
    invoke.mockRejectedValueOnce('SECURE_STORAGE_KEY_INVALIDATED').mockResolvedValueOnce({})
    const storage = new TauriSecureStorage()
    await expect(storage.get('device-identity')).resolves.toBeNull()
    expect(invoke.mock.calls).toEqual([
      ['secure_storage_get', { key: 'lamtools.mobile.device-identity' }],
      ['secure_storage_remove', { key: 'lamtools.mobile.device-identity' }],
    ])
  })

  it('keeps unrelated read errors visible and preserves the entry', async () => {
    invoke.mockRejectedValueOnce('AndroidKeyStore temporarily unavailable')
    await expect(new TauriSecureStorage().get('device-identity'))
      .rejects.toBe('AndroidKeyStore temporarily unavailable')
    expect(invoke).toHaveBeenCalledTimes(1)
  })
})
