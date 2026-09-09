import { describe, expect, it } from 'vitest'
import { MemorySecureStorage } from '../src/native/secureStorage'
import {
  forgetTrustedDevice,
  listTrustedDevices,
  MemoryTrustedDeviceMetadataStorage,
  saveTrustedDevice,
} from '../src/pairing/TrustedDevices'

describe('trusted device storage', () => {
  it('persists, replaces and forgets a paired desktop', async () => {
    const stores = { secrets: new MemorySecureStorage(), metadata: new MemoryTrustedDeviceMetadataStorage() }
    await saveTrustedDevice({ deviceId: 'desktop-1', name: 'PC', accessToken: 'one' }, stores)
    await saveTrustedDevice({ deviceId: 'desktop-1', name: 'PC', accessToken: 'two' }, stores)
    expect(await listTrustedDevices(stores)).toEqual([
      { deviceId: 'desktop-1', name: 'PC', accessToken: 'two' },
    ])
    await forgetTrustedDevice('desktop-1', stores)
    expect(await listTrustedDevices(stores)).toEqual([])
  })

  it('keeps metadata readable without exposing the credential value', async () => {
    const secrets = new MemorySecureStorage()
    const metadata = new MemoryTrustedDeviceMetadataStorage()
    const stores = { secrets, metadata }
    await saveTrustedDevice({
      deviceId: 'desktop/2',
      name: 'Office PC',
      gatewayUrl: 'ws://192.168.1.2:4000/_lamtools/tunnel',
      accessToken: 'secret-token',
    }, stores)

    const metadataKeys = await metadata.keys('lamtools.mobile.trusted-device.metadata.')
    expect(metadataKeys).toHaveLength(1)
    expect(await metadata.get(metadataKeys[0])).toMatchObject({ deviceId: 'desktop/2', name: 'Office PC' })
    expect(await metadata.get(metadataKeys[0])).not.toHaveProperty('accessToken')
    expect(await listTrustedDevices(stores)).toMatchObject([{ deviceId: 'desktop/2', accessToken: 'secret-token' }])
  })

  it('supports an account workspace device without a local pairing token', async () => {
    const stores = { secrets: new MemorySecureStorage(), metadata: new MemoryTrustedDeviceMetadataStorage() }
    await saveTrustedDevice({
      deviceId: 'workspace-host',
      name: '账号工作环境',
      publicKey: 'host-key',
    }, stores)

    expect(await listTrustedDevices(stores)).toEqual([{
      deviceId: 'workspace-host',
      name: '账号工作环境',
      publicKey: 'host-key',
    }])
  })
})
